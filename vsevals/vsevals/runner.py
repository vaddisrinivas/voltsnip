"""Core execution engine.

The main entry point is run_one().  Everything else in this file is internal.

Flow
----
                        ┌─────────────────────────────────────────────────────┐
run_one(task, variant)  │ 1. Load task + variant from suite                   │
                        │ 2. Read target file from repo                       │
                        │ 3. [memory variants] retrieve seed snippets         │
                        │ 4. Build prompt via prompt.build_prompt()           │
                        │ 5. Call LLM via dispatch.call_llm()                 │
                        │    • direct/no-tools (P0-P3): single LLM call       │
                        │    • tool-enabled (P4-P6a): LLM call with tool loop │
                        │       (openai: Responses API + remote MCP)          │
                        │       (anthropic: SDK tool loop, Python-side)       │
                        │       (claudecode/codex: subprocess MCP tool loop;  │
                        │        per-turn tool traces are not exposed to this  │
                        │        Python runner)                                │
                        │ 6. Parse output (JSON {code, comments})             │
                        │ 7. Score via scorer.score_one()                     │
                        │ 8. [cfg.auto_apply_patch] run patch+Docker pytest   │
                        │      • materialize overlay (copy repo, no .git)     │
                        │      • write generated code to target file          │
                        │      • docker run --rm -v overlay:/workspace …      │
                        │      • cleanup overlay                              │
                        │ 9. Write artifacts (full_dump.json, summary, etc.)  │
                        └─────────────────────────────────────────────────────┘

Convenience wrappers: run_p0() … run_p6a(), run_hypothesis()
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal

from vsevals.client import VoltSnipClient
from vsevals.dispatch import LLMResult, call_llm, voltsnip_tool_schemas
from vsevals.loader import load_suite
from vsevals.models import (
    GeneratedPayload,
    MessageTrace,
    PromptBundle,
    PytestResult,
    RetrievedSnippet,
    RunArtifactPaths,
    RunConfig,
    RunError,
    RunResult,
    ScoreResult,
    SuiteTask,
    SummaryMetrics,
    TimingInfo,
    TokenUsage,
    ToolTrace,
    VariantConfig,
)
from vsevals.patching import apply_rewrite, cleanup_overlay, materialize_overlay
from vsevals.prompt import DEFAULT_REPO_POLICY, build_prompt
from vsevals.pytest_runner import run_pytest_in_docker
from vsevals.scorer import score_one

LOGGER = logging.getLogger(__name__)

DEFAULT_OUTPUT_ROOT = "./vsevals_runs"
DEFAULT_VOLTSNIP_BASE_URL = "http://localhost:8001"

HypothesisVariantId = Literal["P0", "P1", "P2", "P3", "P4", "P5b", "P5a", "P6b", "P6a"]
HYPOTHESIS_VARIANTS: tuple[str, ...] = ("P0", "P1", "P2", "P3", "P4", "P5b", "P5a", "P6b", "P6a")


# ---------------------------------------------------------------------------
# Convenience wrappers: run_p0() … run_p6a()
# ---------------------------------------------------------------------------


def run_hypothesis(
    *,
    hypothesis: HypothesisVariantId,
    task_id: str,
    model_name: str,
    suite_path: str,
    output_dir: str,
    repo_root: str | None = None,
    cfg: RunConfig | dict | None = None,
) -> RunResult:
    if hypothesis not in HYPOTHESIS_VARIANTS:
        raise ValueError(f"unknown hypothesis: {hypothesis!r}. Must be one of {HYPOTHESIS_VARIANTS}")
    return run_one(
        task_id=task_id,
        variant_id=hypothesis,
        model_name=model_name,
        suite_path=suite_path,
        output_dir=output_dir,
        repo_root=repo_root,
        cfg=cfg,
    )


_VARIANT_DOCS: dict[str, str] = {
    "P0":  "Baseline: direct call, no memory, no tools.",
    "P1":  "Baseline + explicit instruction (no memory, no tools).",
    "P2":  "Memory injected (implicit guidance).",
    "P3":  "Memory injected + explicit instruction.",
    "P4":  "Tools only — raw tool use, zero guidance.",
    "P5b": "Skill docs (no keys) + tools — knows how to use VoltSnip, decides what to fetch.",
    "P5a": "Skill docs + specific keys + tools — knows exactly which keys to fetch.",
    "P6b": "Agents.md sidecar + keys + tools — richer context, no pre-fetched snippets.",
    "P6a": "Full: agents.md sidecar + pre-fetched snippets + tools.",
}
for _vid, _doc in _VARIANT_DOCS.items():
    def _f(*, task_id: str, model_name: str, suite_path: str, output_dir: str, _v: str = _vid, **kw: Any) -> RunResult:
        return run_one(task_id=task_id, variant_id=_v, model_name=model_name, suite_path=suite_path, output_dir=output_dir, **kw)
    _f.__name__ = f"run_{_vid.lower()}"
    _f.__doc__ = _doc
    globals()[f"run_{_vid.lower()}"] = _f
del _vid, _doc, _f


# ---------------------------------------------------------------------------
# Core: run_one
# ---------------------------------------------------------------------------


def run_one(
    *,
    task_id: str,
    variant_id: str,
    model_name: str,
    suite_path: str,
    output_dir: str,
    repo_root: str | None = None,
    cfg: RunConfig | dict | None = None,
) -> RunResult:
    """Execute a single (task × variant × model) cell and return a RunResult."""
    resolved_cfg = cfg if isinstance(cfg, RunConfig) else RunConfig.model_validate(cfg or {})
    suite = load_suite(suite_path)

    # Let usecase.yaml docker settings override RunConfig defaults (not explicit overrides)
    if suite.suite.pytest_docker_image and resolved_cfg.pytest_docker_image == "moltsnip-pytest:latest":
        resolved_cfg = resolved_cfg.model_copy(update={"pytest_docker_image": suite.suite.pytest_docker_image})
    if suite.suite.pytest_docker_workdir and resolved_cfg.pytest_docker_workdir == "/workspace":
        resolved_cfg = resolved_cfg.model_copy(update={"pytest_docker_workdir": suite.suite.pytest_docker_workdir})

    task = suite.task_map.get(task_id)
    if task is None:
        raise ValueError(f"unknown task_id: {task_id!r}. Available: {sorted(suite.task_map)}")
    variant = suite.variant_map.get(variant_id)
    if variant is None:
        raise ValueError(f"unknown variant_id: {variant_id!r}. Available: {sorted(suite.variant_map)}")

    output_root = output_dir or os.environ.get("VSEVAL_OUTPUT_DIR") or DEFAULT_OUTPUT_ROOT
    artifacts = _make_artifact_paths(output_root=output_root, task_id=task_id, variant_id=variant_id, model_name=model_name)
    run_id = Path(artifacts.run_dir).name

    started_at = datetime.now(timezone.utc)
    t0 = time.perf_counter()
    LOGGER.info("run start  run_id=%s  task=%s  variant=%s  model=%s", run_id, task_id, variant_id, model_name)

    # --- Mutable state -------------------------------------------------------
    status = "ok"
    prompt = PromptBundle(system_prompt="", user_prompt="", context_surface=variant.context_surface, visible_sections=[])
    prompt_after_tools: PromptBundle | None = None
    retrieved_snippets: list[RetrievedSnippet] = []
    tool_traces: list[ToolTrace] = []
    llm_result: LLMResult | None = None
    run_error: RunError | None = None
    provider_keys: dict[str, str] = {}
    voltsnip: VoltSnipClient | None = None
    retrieval_latency_ms: int | None = None
    model_latency_ms: int | None = None

    try:
        provider_keys = _load_provider_keys(resolved_cfg)
        voltsnip = _make_client(variant, resolved_cfg)
        repo_root_path = _resolve_repo_root(repo_root or task.task.repo_root, suite_path=suite_path)
        target_file_content = _read_target_file(repo_root=repo_root_path, target_file=task.task.target_file, suite_path=suite_path)
        repo_policy = resolved_cfg.repo_policy_text or DEFAULT_REPO_POLICY

        # Step 3: retrieve seed snippets (memory variants only).
        # Pre-fetch whenever memory_enabled=true, regardless of retrieval_mode.
        #   retrieval_mode=injected  → fetch, inject into prompt, no tools (P2/P3)
        #   retrieval_mode=agent_decides, memory_enabled=true → fetch as seed
        #     AND give tools so agent can retrieve more (P6a = full)
        #   retrieval_mode=agent_decides, memory_enabled=false → no pre-fetch;
        #     agent must use tools to get snippets (P4/P5b/P5a/P6b)
        if variant.memory_enabled:
            t_ret = time.perf_counter()
            retrieved_snippets = _retrieve_snippets(task=task, variant=variant, voltsnip=voltsnip, cfg=resolved_cfg)
            retrieval_latency_ms = int((time.perf_counter() - t_ret) * 1000)

        # Step 4 + 5: build prompt and call model
        # Guardrail:
        # - One-shot path for all non-tool variants (P0-P3 semantics).
        # - Agent/tool loop only when tools are explicitly enabled (P4+).
        t_model = time.perf_counter()
        if variant.mode == "agent" and variant.tools_enabled:
            llm_result, prompt, prompt_after_tools, retrieved_snippets, tool_traces = _run_agent(
                task=task, variant=variant, model_name=model_name,
                cfg=resolved_cfg, provider_keys=provider_keys,
                voltsnip=voltsnip, seed_snippets=retrieved_snippets,
                target_file_content=target_file_content, repo_policy=repo_policy,
            )
        else:
            prompt = build_prompt(
                task=task, variant=variant, retrieved_snippets=retrieved_snippets,
                repo_policy_text=repo_policy, target_file_content=target_file_content,
                voltsnip_base_url=resolved_cfg.voltsnip_base_url,
            )
            llm_result = call_llm(
                model_name=model_name, system_prompt=prompt.system_prompt, user_prompt=prompt.user_prompt,
                cfg=resolved_cfg, provider_keys=provider_keys,
                sidecar_files=prompt.sidecar_files or None,
            )
        model_latency_ms = int((time.perf_counter() - t_model) * 1000)

    except Exception as exc:
        status = "error"
        run_error = RunError(
            type=exc.__class__.__name__,
            message=str(exc),
            error_class=_classify_error(exc),
        )
        LOGGER.exception("run failed  run_id=%s  task=%s  variant=%s  model=%s", run_id, task_id, variant_id, model_name)

    latency_ms = int((time.perf_counter() - t0) * 1000)
    finished_at = datetime.now(timezone.utc)
    llm_result = llm_result or _empty_llm_result()
    provider, model_id = _parse_provider(model_name)

    sys_chars = len(prompt.system_prompt)
    usr_chars = len(prompt.user_prompt)
    snippet_chars = sum(len(s.code) for s in retrieved_snippets)
    voltsnip_retry_count = voltsnip.retry_count_total if voltsnip else 0
    voltsnip_rate_limit_count = voltsnip.rate_limit_error_count if voltsnip else 0
    voltsnip_timeout_count = voltsnip.timeout_error_count if voltsnip else 0
    voltsnip_error_count = voltsnip.error_count_total if voltsnip else 0

    run_result = RunResult(
        run_id=run_id,
        suite_path=str(Path(suite_path).expanduser().resolve()),
        output_root=str(Path(output_root).expanduser().resolve()),
        task_id=task.task.id,
        task_name=task.task.name,
        variant_id=variant.id,
        model_name=model_name,
        status=status,
        # Variant metadata
        variant_mode=variant.mode,
        variant_memory_enabled=variant.memory_enabled,
        variant_tools_enabled=variant.tools_enabled,
        variant_retrieval_mode=variant.retrieval_mode,
        variant_instruction_mode=variant.instruction_mode,
        variant_context_surface=variant.context_surface,
        variant_max_tool_roundtrips=variant.max_tool_roundtrips,
        # Task metadata
        task_category=task.task.category,
        task_difficulty=task.task.difficulty,
        task_line_start=task.task.line_start,
        task_line_end=task.task.line_end,
        required_snippet_keys=list(task.voltsnip.required_snippets),
        prompt=prompt,
        prompt_after_tools=prompt_after_tools,
        retrieved_snippets=retrieved_snippets,
        tool_traces=tool_traces,
        messages=[
            MessageTrace(role="system", content=prompt.system_prompt),
            MessageTrace(role="user", content=prompt.user_prompt),
            MessageTrace(role="assistant", content=llm_result.raw_output),
        ],
        raw_model_output=llm_result.raw_output,
        parsed_output=llm_result.parsed_output,
        token_usage=llm_result.token_usage,
        timings=TimingInfo(started_at=started_at, finished_at=finished_at, latency_ms=latency_ms),
        summary_metrics=SummaryMetrics(
            latency_ms=latency_ms,
            prompt_chars=sys_chars + usr_chars,
            output_chars=len(llm_result.raw_output),
            prompt_system_chars=sys_chars,
            prompt_user_chars=usr_chars,
            snippet_injected_chars=snippet_chars,
            model_provider=provider,
            model_id=model_id,
            snippet_count=len(retrieved_snippets),
            tool_call_count=len(tool_traces),
            tool_error_count=sum(1 for t in tool_traces if t.error),
            used_tools=bool(tool_traces),
            structured_output_attempted=llm_result.structured_output_attempted,
            structured_output_succeeded=llm_result.structured_output_succeeded,
            fallback_parser_used=llm_result.fallback_parser_used,
            retrieval_latency_ms=retrieval_latency_ms,
            voltsnip_retry_count=voltsnip_retry_count,
            voltsnip_rate_limit_count=voltsnip_rate_limit_count,
            voltsnip_timeout_count=voltsnip_timeout_count,
            voltsnip_error_count=voltsnip_error_count,
            model_request_latency_ms=llm_result.request_latency_ms or model_latency_ms,
            model_request_started_at=llm_result.request_started_at,
            model_request_finished_at=llm_result.request_finished_at,
            model_request_id=llm_result.request_id,
            model_finish_reason=llm_result.finish_reason,
            token_usage=llm_result.token_usage,
        ),
        artifacts=artifacts,
        error=run_error,
    )

    # Step 7: score
    score: ScoreResult | None = None
    if status == "ok":
        t_score = time.perf_counter()
        score = score_one(run_result=run_result, oracle=task.oracle, cfg=resolved_cfg, provider_keys=provider_keys)
        run_result.score = score
        run_result.summary_metrics.scoring_latency_ms = int((time.perf_counter() - t_score) * 1000)

    # Step 8: patch + Docker pytest (optional)
    if status == "ok" and resolved_cfg.auto_apply_patch:
        repo_root_for_patch = _resolve_repo_root(
            repo_root or task.task.repo_root, suite_path=suite_path
        )
        run_result.pytest_result = _run_patch_and_test(
            run_result=run_result,
            task=task,
            repo_root=repo_root_for_patch,
            cfg=resolved_cfg,
        )

    # Step 9: artifacts
    t_art = time.perf_counter()
    _write_artifacts(run_result=run_result, score=score)
    run_result.summary_metrics.artifact_write_latency_ms = int((time.perf_counter() - t_art) * 1000)

    LOGGER.info(
        "run finish  run_id=%s  status=%s  latency_ms=%d  snippets=%d  tools=%d  score=%s",
        run_id, status, latency_ms, len(retrieved_snippets), len(tool_traces),
        f"{score.overall_score:.3f}" if score else "n/a",
    )
    return run_result


# ---------------------------------------------------------------------------
# Agent mode
# ---------------------------------------------------------------------------


def _run_agent(
    *,
    task: SuiteTask,
    variant: VariantConfig,
    model_name: str,
    cfg: RunConfig,
    provider_keys: dict[str, str],
    voltsnip: VoltSnipClient | None,
    seed_snippets: list[RetrievedSnippet],
    target_file_content: str | None,
    repo_policy: str,
) -> tuple[LLMResult, PromptBundle, PromptBundle, list[RetrievedSnippet], list[ToolTrace]]:
    snippets = _dedup_snippets(seed_snippets)
    tool_traces: list[ToolTrace] = []
    snippet_limit = cfg.snippet_context_limit or task.voltsnip.snippet_context_limit
    max_chars = cfg.snippet_context_max_chars or task.voltsnip.snippet_context_max_chars
    roundtrip_count = {"n": 0}

    prompt_sent = build_prompt(
        task=task, variant=variant, retrieved_snippets=snippets,
        repo_policy_text=repo_policy, target_file_content=target_file_content,
        voltsnip_base_url=cfg.voltsnip_base_url,
    )

    provider, _ = _parse_provider(model_name)

    # claudecode / codex: subprocess MCP tool loop — tool_traces parsed from stdout JSONL
    if provider in ("claudecode", "codex"):
        from vsevals.dispatch import _call_claudecode, _call_codex, _parse_model
        _, model_id = _parse_model(model_name)
        tools = voltsnip_tool_schemas() if variant.tools_enabled else None
        # Strict guardrail: do not add hidden turn buffers beyond variant budget.
        turns = max(1, variant.max_tool_roundtrips)
        if provider == "claudecode":
            llm_result = _call_claudecode(
                model_id=model_id, system_prompt=prompt_sent.system_prompt,
                user_prompt=prompt_sent.user_prompt, cfg=cfg,
                tool_schemas=tools, max_tool_turns=turns,
                sidecar_files=prompt_sent.sidecar_files or None,
            )
        else:
            llm_result = _call_codex(
                model_id=model_id, system_prompt=prompt_sent.system_prompt,
                user_prompt=prompt_sent.user_prompt, cfg=cfg,
                tool_schemas=tools, max_tool_turns=turns,
                sidecar_files=prompt_sent.sidecar_files or None,
            )
        # Merge tool_traces parsed from the subprocess JSONL stdout
        tool_traces.extend(llm_result.tool_traces)
        # Back-fill retrieved_snippets from any fetch-by-keys calls in tool_traces
        _merge_tool_snippets(tool_traces, snippets, voltsnip, cfg, task)
        prompt_after = build_prompt(
            task=task, variant=variant, retrieved_snippets=snippets,
            repo_policy_text=repo_policy, target_file_content=target_file_content,
            voltsnip_base_url=cfg.voltsnip_base_url,
        )
        return llm_result, prompt_sent, prompt_after, snippets, tool_traces

    # openai: Responses API + native MCP (tool loop is server-side, no tool_handlers needed)
    if provider == "openai" and variant.tools_enabled:
        llm_result = call_llm(
            model_name=model_name,
            system_prompt=prompt_sent.system_prompt,
            user_prompt=prompt_sent.user_prompt,
            cfg=cfg,
            provider_keys=provider_keys,
            tool_schemas=voltsnip_tool_schemas(),  # signals MCP path
            max_tool_turns=max(1, variant.max_tool_roundtrips),
            sidecar_files=prompt_sent.sidecar_files or None,
        )
        prompt_after = build_prompt(task=task, variant=variant, retrieved_snippets=snippets, repo_policy_text=repo_policy, target_file_content=target_file_content, voltsnip_base_url=cfg.voltsnip_base_url)
        return llm_result, prompt_sent, prompt_after, snippets, tool_traces

    # anthropic (and openai without tools): native SDK tool loop with Python-side handlers
    tool_schemas = voltsnip_tool_schemas() if variant.tools_enabled else None
    tool_handlers: dict[str, Callable[[dict], dict]] | None = None

    if variant.tools_enabled and voltsnip:
        def _fetch_handler(payload: dict) -> dict:
            keys = [k for k in (payload.get("canonical_keys") or []) if isinstance(k, str) and k.strip()][:snippet_limit]
            return _invoke_tool(
                name="voltsnip.get_by_canonical_keys", args={"canonical_keys": keys},
                voltsnip=voltsnip, snippets=snippets, tool_traces=tool_traces,
                roundtrip_count=roundtrip_count, max_roundtrips=variant.max_tool_roundtrips,
                fetch=lambda: voltsnip.get_by_canonical_keys(keys, limit=snippet_limit, max_chars=max_chars),
            )

        def _search_handler(payload: dict) -> dict:
            q = payload.get("query", "")
            k = max(1, min(int(payload.get("k", 4) or 4), snippet_limit))
            return _invoke_tool(
                name="voltsnip.semantic_search", args={"q": q, "k": k},
                voltsnip=voltsnip, snippets=snippets, tool_traces=tool_traces,
                roundtrip_count=roundtrip_count, max_roundtrips=variant.max_tool_roundtrips,
                fetch=lambda: voltsnip.semantic_search(q=q, k=k, max_chars=max_chars),
            )

        tool_handlers = {
            "voltsnip_fetch_by_canonical_keys": _fetch_handler,
            "voltsnip_semantic_search": _search_handler,
        }

    llm_result = call_llm(
        model_name=model_name,
        system_prompt=prompt_sent.system_prompt,
        user_prompt=prompt_sent.user_prompt,
        cfg=cfg,
        provider_keys=provider_keys,
        tool_schemas=tool_schemas,
        tool_handlers=tool_handlers,
        max_tool_turns=max(1, variant.max_tool_roundtrips),
        sidecar_files=prompt_sent.sidecar_files or None,
    )
    prompt_after = build_prompt(task=task, variant=variant, retrieved_snippets=snippets, repo_policy_text=repo_policy, target_file_content=target_file_content, voltsnip_base_url=cfg.voltsnip_base_url)
    return llm_result, prompt_sent, prompt_after, snippets, tool_traces


def _merge_tool_snippets(
    tool_traces: list[ToolTrace],
    snippets: list[RetrievedSnippet],
    voltsnip: VoltSnipClient | None,
    cfg: RunConfig,
    task: SuiteTask,
) -> None:
    """Back-fill retrieved_snippets from tool_traces for claudecode/codex providers.

    When claudecode or codex make MCP tool calls, the Python side never executes
    the tool handlers — the subprocess does it directly. After the run we parse
    tool_traces from stdout. This helper looks at the canonical_keys requested
    in each fetch call and fetches them from VoltSnip so retrieved_snippets is
    populated correctly for coverage/memory_signal metrics.
    """
    if not voltsnip or not tool_traces:
        return

    existing_keys = {s.canonical_key or s.id for s in snippets}
    limit = cfg.snippet_context_limit or task.voltsnip.snippet_context_limit
    max_chars = cfg.snippet_context_max_chars or task.voltsnip.snippet_context_max_chars

    keys_to_fetch: list[str] = []
    for trace in tool_traces:
        if "fetch" in (trace.tool_name or "") or "canonical" in (trace.tool_name or ""):
            keys = (trace.tool_args or {}).get("canonical_keys") or []
            for k in keys:
                if isinstance(k, str) and k.strip() and k not in existing_keys:
                    keys_to_fetch.append(k)
                    existing_keys.add(k)

    if not keys_to_fetch:
        return

    try:
        fetched = voltsnip.get_by_canonical_keys(keys_to_fetch, limit=limit, max_chars=max_chars)
        snippets.extend(fetched)
    except Exception as exc:
        LOGGER.debug("_merge_tool_snippets fetch failed: %s", exc)


def _invoke_tool(
    *,
    name: str,
    args: dict,
    voltsnip: VoltSnipClient,
    snippets: list[RetrievedSnippet],
    tool_traces: list[ToolTrace],
    roundtrip_count: dict,
    max_roundtrips: int,
    fetch: Callable[[], list[RetrievedSnippet]],
) -> dict:
    roundtrip_count["n"] += 1
    started = datetime.now(timezone.utc)
    t0 = time.perf_counter()
    error: str | None = None
    new_snippets: list[RetrievedSnippet] = []

    if roundtrip_count["n"] > max_roundtrips:
        error = f"tool budget exceeded (max {max_roundtrips})"
    else:
        try:
            new_snippets = fetch()
            # Merge into shared snippets list in-place
            existing_keys = {s.canonical_key or s.id for s in snippets}
            for s in new_snippets:
                key = s.canonical_key or s.id
                if key not in existing_keys:
                    snippets.append(s)
                    existing_keys.add(key)
        except Exception as exc:
            error = str(exc)
            LOGGER.debug("tool %s failed: %s", name, exc)

    duration_ms = int((time.perf_counter() - t0) * 1000)
    tool_traces.append(ToolTrace(
        roundtrip=roundtrip_count["n"],
        tool_name=name,
        tool_args=args,
        tool_result={"retrieved": len(new_snippets)} if not error else None,
        error=error,
        started_at=started,
        finished_at=datetime.now(timezone.utc),
        duration_ms=duration_ms,
    ))

    if error:
        return {"error": error}
    return {
        "snippets": [
            {"key": s.canonical_key or s.id, "title": s.title, "code": s.code}
            for s in new_snippets
        ]
    }


# ---------------------------------------------------------------------------
# Snippet retrieval (for P2/P3: injected memory)
# ---------------------------------------------------------------------------


def _retrieve_snippets(
    *,
    task: SuiteTask,
    variant: VariantConfig,
    voltsnip: VoltSnipClient | None,
    cfg: RunConfig,
) -> list[RetrievedSnippet]:
    """Pre-fetch snippets to inject into the prompt for P2/P3 variants (oracle injection).

    Uses the ground-truth canonical keys from ``task.voltsnip.required_snippets``
    to fetch exactly the right snippets — this is the *oracle* baseline: "given perfect
    context, does injecting it help?".

    Semantic retrieval (realistic RAG) is a separate variant so both can be compared
    in the paper (P2_sem / P3_sem will be added alongside P2 / P3 oracle variants).
    """
    if not voltsnip:
        return []
    keys: list[str] = list(task.voltsnip.required_snippets or [])
    if not keys:
        return []
    limit = cfg.snippet_context_limit or task.voltsnip.snippet_context_limit
    max_chars = cfg.snippet_context_max_chars or task.voltsnip.snippet_context_max_chars
    try:
        return voltsnip.get_by_canonical_keys(keys, limit=limit, max_chars=max_chars)
    except Exception as exc:
        LOGGER.warning("snippet oracle retrieval failed (P2/P3): %s", exc)
        return []


# ---------------------------------------------------------------------------
# Client / path helpers
# ---------------------------------------------------------------------------


def _make_client(variant: VariantConfig, cfg: RunConfig) -> VoltSnipClient | None:
    if not (variant.memory_enabled or variant.tools_enabled):
        return None
    base_url = cfg.voltsnip_base_url or os.environ.get("VOLTSNIP_BASE_URL") or DEFAULT_VOLTSNIP_BASE_URL
    client = VoltSnipClient(
        base_url=base_url,
        timeout_seconds=cfg.voltsnip_timeout_seconds,
        retry_attempts=cfg.voltsnip_retry_attempts,
    )
    client.preflight_check()
    return client


def _load_provider_keys(cfg: RunConfig) -> dict[str, str]:
    keys: dict[str, str] = {}
    env_map = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}
    for provider, env_key in env_map.items():
        val = os.environ.get(env_key)
        if val:
            keys[provider] = val
    # Config-level keys override env vars
    if cfg.api_key:
        keys["_override"] = cfg.api_key
    keys.update(cfg.provider_api_keys)
    # Also load from .env if present
    keys.update(_load_dotenv_keys())
    return keys


def _load_dotenv_keys() -> dict[str, str]:
    env_map = {"OPENAI_API_KEY": "openai", "ANTHROPIC_API_KEY": "anthropic"}
    result: dict[str, str] = {}
    for candidate in (Path.cwd() / ".env", Path.cwd() / "vsevals" / ".env"):
        if not candidate.exists():
            continue
        for line in candidate.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip()
            if key in env_map and value:
                result[env_map[key]] = value
        break
    return result


def _resolve_repo_root(repo_root: str | None, *, suite_path: str) -> Path | None:
    if not repo_root:
        return None
    candidate = Path(repo_root).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    cwd_try = (Path.cwd() / candidate).resolve()
    if cwd_try.exists():
        return cwd_try
    suite_dir = Path(suite_path).expanduser().resolve().parent
    suite_try = (suite_dir / candidate).resolve()
    return suite_try


def _read_target_file(*, repo_root: Path | None, target_file: str | None, suite_path: str) -> str | None:
    if not target_file or repo_root is None:
        return None
    p = Path(target_file).expanduser()
    if not p.is_absolute():
        p = (repo_root / p).resolve()
    try:
        return p.read_text(encoding="utf-8") if p.exists() else None
    except Exception:
        return None


def _parse_provider(model_name: str) -> tuple[str, str]:
    provider, model_id = model_name.split(":", 1) if ":" in model_name else ("openai", model_name)
    return provider.strip().lower(), model_id.strip()


def _compute_mount_root(*, repo_root: Path, docker_workdir: str) -> Path:
    """Compute the directory to copy into the overlay (= what maps to /workspace in Docker).

    If docker_workdir == "/workspace": mount_root = repo_root (simple case).
    If docker_workdir == "/workspace/foo/bar": the overlay must contain the ancestor
    that is 2 levels above repo_root, because repo_root corresponds to /workspace/foo/bar.
    """
    workdir = docker_workdir.rstrip("/")
    if workdir == "/workspace" or not workdir.startswith("/workspace/"):
        return repo_root
    suffix = workdir[len("/workspace/"):]  # e.g. "voltsnip-evals/usecases/hybrid-example"
    depth = len(Path(suffix).parts)        # number of directories to go up from repo_root
    mount = repo_root.resolve()
    for _ in range(depth):
        mount = mount.parent
    return mount


def _dedup_snippets(snippets: list[RetrievedSnippet]) -> list[RetrievedSnippet]:
    seen: set[str] = set()
    result: list[RetrievedSnippet] = []
    for s in snippets:
        key = s.canonical_key or s.id
        if key not in seen:
            seen.add(key)
            result.append(s)
    return result


def _empty_llm_result() -> LLMResult:
    return LLMResult(
        raw_output="", parsed_output=GeneratedPayload(code="", comments=""),
        token_usage=TokenUsage(),
        structured_output_attempted=False, structured_output_succeeded=False, fallback_parser_used=False,
        request_started_at=None, request_finished_at=None, request_latency_ms=None,
        request_id=None, finish_reason=None,
    )


# ---------------------------------------------------------------------------
# Patch + Docker pytest
# ---------------------------------------------------------------------------


def _run_patch_and_test(
    *,
    run_result: RunResult,
    task: SuiteTask,
    repo_root: Path | None,
    cfg: RunConfig,
) -> PytestResult:
    """Materialize an isolated overlay, apply the rewrite, run pytest in Docker.

    Steps:
      1. Validate prerequisites (repo_root, target_file, test_command).
      2. Determine overlay directory (inside the run artifact dir).
      3. Copy repo into overlay (skipping .git, .venv, etc.).
      4. Write generated code to the target file inside the overlay.
      5. Run pytest in Docker, mounting overlay as workspace.
      6. Cleanup overlay (always, regardless of outcome).
      7. Return PytestResult.
    """
    target_file = task.task.target_file
    test_command = task.task.test_command

    if not repo_root:
        return PytestResult(ran=False, error="no repo_root configured for task — cannot run pytest")
    if not target_file:
        return PytestResult(ran=False, error="no target_file configured for task — cannot apply patch")
    if not test_command:
        return PytestResult(ran=False, error="no test_command configured for task — nothing to run")

    code = run_result.parsed_output.code
    if not code.strip():
        return PytestResult(ran=False, error="generated code is empty — skipping pytest")

    overlay_root = Path(run_result.artifacts.run_dir) / "_pytest_overlay"

    # Determine mount root: if pytest_docker_workdir is a subpath of /workspace,
    # the overlay must contain the ancestor that maps to /workspace.
    # e.g. workdir=/workspace/voltsnip-evals/usecases/hybrid-example → go up 3 levels from repo_root
    mount_root = _compute_mount_root(repo_root=repo_root, docker_workdir=cfg.pytest_docker_workdir)

    try:
        LOGGER.info(
            "patch+test  task=%s  target=%s  mount_root=%s  overlay=%s",
            task.id, target_file, mount_root, overlay_root,
        )
        materialize_overlay(repo_root=mount_root, overlay_root=overlay_root)
        apply_rewrite(
            code=code,
            target_file=target_file,
            repo_root=repo_root,
            overlay_root=overlay_root,
            mount_root=mount_root,
            line_start=task.task.line_start,
            line_end=task.task.line_end,
        )
        result = run_pytest_in_docker(
            test_command=test_command,
            overlay_root=overlay_root,
            cfg=cfg,
        )
    except Exception as exc:
        LOGGER.exception("patch+test failed  task=%s", task.id)
        result = PytestResult(ran=False, error=str(exc), overlay_path=str(overlay_root))
    finally:
        if cfg.unapply_patch_after_test:
            cleanup_overlay(overlay_root)

    return result


# ---------------------------------------------------------------------------
# Artifact writing
# ---------------------------------------------------------------------------


def _classify_error(exc: Exception) -> str:
    """Map an exception to a coarse error class string for filtering/analysis.

    Classes (ordered by specificity):
      AUTH_ERROR         — API key missing, 401/403 from provider
      RATE_LIMIT_ERROR   — 429 / quota exceeded
      TIMEOUT            — subprocess / request timeout
      NETWORK_ERROR      — connection refused, DNS, SSL
      LLM_PARSE_ERROR    — model output could not be parsed
      RETRIEVAL_ERROR    — VoltSnip client failure
      SCORING_ERROR      — judge call / scorer failed
      CONFIG_ERROR       — bad task/variant config (ValueError during setup)
      EMPTY_OUTPUT       — model returned empty/trivial output
      UNKNOWN_ERROR      — anything else
    """
    msg = str(exc).lower()
    name = type(exc).__name__.lower()

    # Auth
    if any(t in msg for t in ("api key", "apikey", "unauthorized", "invalid api", "authentication", "403", "401")):
        return "AUTH_ERROR"
    if "api_key" in name or "autherror" in name:
        return "AUTH_ERROR"

    # Rate limit
    if any(t in msg for t in ("rate limit", "ratelimit", "quota", "too many requests", "429")):
        return "RATE_LIMIT_ERROR"

    # Timeout
    if "timeout" in name or "timeout" in msg or "timed out" in msg:
        return "TIMEOUT"

    # Network
    if any(t in msg for t in ("connection refused", "connection error", "name resolution", "ssl", "network", "unreachable", "eof")):
        return "NETWORK_ERROR"
    if any(t in name for t in ("connectionerror", "networkerror", "sslerror")):
        return "NETWORK_ERROR"

    # Parse
    if any(t in msg for t in ("non-json output", "failed to parse", "parse", "json")):
        return "LLM_PARSE_ERROR"

    # Retrieval / VoltSnip
    if any(t in msg for t in ("voltsnip", "retrieval", "get_by_canonical", "semantic_search")):
        return "RETRIEVAL_ERROR"

    # Config
    if any(t in msg for t in ("unknown task", "unknown variant", "unknown model")):
        return "CONFIG_ERROR"
    if isinstance(exc, (ValueError, KeyError)) and any(t in msg for t in ("not found", "missing")):
        return "CONFIG_ERROR"

    # Empty output
    if any(t in msg for t in ("empty", "no output", "empty code")):
        return "EMPTY_OUTPUT"

    return "UNKNOWN_ERROR"


def _make_artifact_paths(*, output_root: str, task_id: str, variant_id: str, model_name: str) -> RunArtifactPaths:
    root = Path(output_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")

    def sanitize(s: str) -> str:
        return re.sub(r"[^a-zA-Z0-9._-]+", "_", s.strip().lower()).strip("._") or "item"

    token = "__".join([stamp, sanitize(task_id), sanitize(variant_id), sanitize(model_name)])
    run_dir = root / token
    run_dir.mkdir(parents=True, exist_ok=True)
    return RunArtifactPaths(
        run_dir=str(run_dir),
        full_dump_json=str(run_dir / "full_dump.json"),
        summary_dump_json=str(run_dir / "summary_dump.json"),
        code_output=str(run_dir / "generated_code.txt"),
        comments_output=str(run_dir / "generated_comments.txt"),
        rewrite_output=str(run_dir / "generated_rewrite.txt"),
    )


def _write_artifacts(*, run_result: RunResult, score: ScoreResult | None) -> None:
    Path(run_result.artifacts.full_dump_json).write_text(
        json.dumps(run_result.model_dump(mode="json"), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    summary = {
        "run_id": run_result.run_id,
        "task_id": run_result.task_id,
        "task_name": run_result.task_name,
        "variant_id": run_result.variant_id,
        "model_name": run_result.model_name,
        "status": run_result.status,
        "metrics": run_result.summary_metrics.model_dump(mode="json"),
        "score": score.model_dump(mode="json") if score else None,
        "pytest_result": run_result.pytest_result.model_dump(mode="json") if run_result.pytest_result else None,
        "error": run_result.error.model_dump(mode="json") if run_result.error else None,
    }
    Path(run_result.artifacts.summary_dump_json).write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    Path(run_result.artifacts.code_output).write_text(run_result.parsed_output.code, encoding="utf-8")
    Path(run_result.artifacts.comments_output).write_text(run_result.parsed_output.comments, encoding="utf-8")
    Path(run_result.artifacts.rewrite_output).write_text(run_result.parsed_output.code, encoding="utf-8")
    # Pytest stdout/stderr as separate files (mirrors old harness layout)
    if run_result.pytest_result and run_result.pytest_result.ran:
        run_dir = Path(run_result.artifacts.run_dir)
        (run_dir / "pytest.stdout.txt").write_text(run_result.pytest_result.stdout, encoding="utf-8")
        (run_dir / "pytest.stderr.txt").write_text(run_result.pytest_result.stderr, encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI entry point (called by `vseval` script)
# ---------------------------------------------------------------------------


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Run a single vsevals cell")
    parser.add_argument("--task", required=True)
    parser.add_argument("--variant", default="P0")
    parser.add_argument("--model", required=True)
    parser.add_argument("--suite", default="suite.yaml")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--repo-root", default=None)
    parser.add_argument("--judge-model", default="openai:gpt-5-mini")
    parser.add_argument("--judge-model-claudecode", action="store_true", help="Use claudecode for judge model")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING"])
    args = parser.parse_args()

    logging.basicConfig(level=getattr(logging, args.log_level), format="%(levelname)s %(name)s %(message)s")

    judge_model = args.judge_model
    if args.judge_model_claudecode:
        _, model_id = args.model.split(":", 1) if ":" in args.model else ("openai", args.model)
        judge_model = f"claudecode:{model_id}"

    cfg = RunConfig(scoring_judge_model=judge_model)
    result = run_one(
        task_id=args.task,
        variant_id=args.variant,
        model_name=args.model,
        suite_path=args.suite,
        output_dir=args.output_dir,
        repo_root=args.repo_root,
        cfg=cfg,
    )
    print(f"run_id:  {result.run_id}")
    print(f"status:  {result.status}")
    if result.score:
        print(f"score:   {result.score.overall_score:.3f}  passed={result.score.passed}")
    if result.error:
        print(f"error:   {result.error.type}: {result.error.message}")
