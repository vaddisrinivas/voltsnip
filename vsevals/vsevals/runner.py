"""Core execution engine. Entry point: run_one(). Convenience wrapper: run_hypothesis()."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal

from vsevals.client import VoltSnipClient
from vsevals.dispatch import call_llm, voltsnip_tool_schemas
from vsevals.execution_trace import ExecutionTrace, get_current_trace, set_current_trace, trace_execution
from vsevals.loader import load_suite
from vsevals.models import (
    GeneratedPayload, MessageTrace, PromptBundle, PytestResult,
    RetrievedSnippet, RunArtifactPaths, RunConfig, RunError, RunResult,
    ScoreResult, SuiteTask, SummaryMetrics, TimingInfo, TokenUsage,
    ToolTrace, VariantConfig, LLMResult,
)
from vsevals.patching import apply_line_range_rewrite, apply_rewrite, cleanup_overlay, materialize_overlay
from vsevals.prompt import DEFAULT_REPO_POLICY, build_prompt
from vsevals.pytest_runner import run_pytest_in_docker, start_test_container, stop_test_container
from vsevals.scorer import score_one
from vsevals.tour_generator import generate_debug_tour, should_generate_tour

LOGGER = logging.getLogger(__name__)
DEFAULT_OUTPUT_ROOT = "./vsevals_runs"
DEFAULT_VOLTSNIP_BASE_URL = "http://localhost:8000"
HypothesisVariantId = Literal["P0", "P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8"]
HYPOTHESIS_VARIANTS: tuple[str, ...] = ("P0", "P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8")


def run_hypothesis(*, hypothesis: HypothesisVariantId, task_id: str, model_name: str,
                   suite_path: str, output_dir: str, repo_root: str | None = None,
                   cfg: RunConfig | dict | None = None) -> RunResult:
    if hypothesis not in HYPOTHESIS_VARIANTS:
        raise ValueError(f"unknown hypothesis: {hypothesis!r}. Must be one of {HYPOTHESIS_VARIANTS}")
    return run_one(task_id=task_id, variant_id=hypothesis, model_name=model_name,
                   suite_path=suite_path, output_dir=output_dir, repo_root=repo_root, cfg=cfg)


def run_one(*, task_id: str, variant_id: str, model_name: str, suite_path: str,
            output_dir: str, repo_root: str | None = None,
            cfg: RunConfig | dict | None = None) -> RunResult:
    resolved_cfg = cfg if isinstance(cfg, RunConfig) else RunConfig.model_validate(cfg or {})
    suite = load_suite(suite_path)

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

    status = "ok"
    prompt = PromptBundle(system_prompt="", user_prompt="", context_surface=variant.context_surface, visible_sections=[])
    prompt_after_tools: PromptBundle | None = None
    retrieved_snippets: list[RetrievedSnippet] = []
    tool_traces: list[ToolTrace] = []
    llm_result: LLMResult | None = None
    run_error: RunError | None = None
    voltsnip: VoltSnipClient | None = None
    retrieval_latency_ms: int | None = None
    model_latency_ms: int | None = None

    # Initialize execution trace for this cell
    execution_trace = ExecutionTrace(task_id=task_id, variant_id=variant_id, model_name=model_name)
    set_current_trace(execution_trace)

    try:
        provider, _ = _parse_provider(model_name)
        provider_keys = _load_provider_keys(resolved_cfg)
        voltsnip = _make_client(variant, resolved_cfg)
        repo_root_path = _resolve_repo_root(
            repo_root or task.task.repo_root or suite.suite.default_repo_root, suite_path=suite_path)
        target_file_content = _read_target_file(repo_root=repo_root_path, target_file=task.task.target_file, suite_path=suite_path)
        repo_policy = resolved_cfg.repo_policy_text or DEFAULT_REPO_POLICY

        if variant.memory_enabled:
            execution_trace.record(
                function_name="_retrieve_snippets",
                file_path="vsevals/runner.py",
                line_number=97,  # inline tracking
                decision_point="retrieval_fork",
                context={"enabled": variant.memory_enabled, "retrieval_mode": variant.retrieval_mode},
            )
            t_ret = time.perf_counter()
            retrieved_snippets = _retrieve_snippets(task=task, variant=variant, voltsnip=voltsnip, cfg=resolved_cfg)
            retrieval_latency_ms = int((time.perf_counter() - t_ret) * 1000)

        t_model = time.perf_counter()
        execution_trace.record(
            function_name="_mode_fork",
            file_path="vsevals/runner.py",
            line_number=104,
            decision_point="mode_fork",
            context={"mode": variant.mode, "tools_enabled": variant.tools_enabled},
        )
        if variant.mode == "agent" and variant.tools_enabled:
            llm_result, prompt, prompt_after_tools, retrieved_snippets, tool_traces = _run_agent(
                task=task, variant=variant, model_name=model_name, cfg=resolved_cfg,
                provider_keys=provider_keys, voltsnip=voltsnip, seed_snippets=retrieved_snippets,
                target_file_content=target_file_content, repo_policy=repo_policy,
                repo_root=repo_root_path, run_dir=artifacts.run_dir,
            )
        else:
            prompt = build_prompt(task=task, variant=variant, retrieved_snippets=retrieved_snippets,
                                  repo_policy_text=repo_policy, target_file_content=target_file_content,
                                  voltsnip_base_url=resolved_cfg.voltsnip_base_url)
            llm_result = call_llm(model_name=model_name, system_prompt=prompt.system_prompt,
                                  user_prompt=prompt.user_prompt, cfg=resolved_cfg,
                                  provider_keys=provider_keys, sidecar_files=prompt.sidecar_files or None)
        model_latency_ms = int((time.perf_counter() - t_model) * 1000)

    except Exception as exc:
        status = "error"
        run_error = RunError(type=exc.__class__.__name__, message=str(exc), error_class=_classify_error(exc))
        LOGGER.exception("run failed  run_id=%s  task=%s  variant=%s  model=%s", run_id, task_id, variant_id, model_name)
    finally:
        set_current_trace(None)

    latency_ms = int((time.perf_counter() - t0) * 1000)
    finished_at = datetime.now(timezone.utc)
    llm_result = llm_result or _empty_llm_result()

    if status == "ok" and not llm_result.parsed_output.code.strip():
        status = "error"
        run_error = RunError(type="EmptyOutput", message="model returned ok status but produced no code",
                             error_class="provider_empty_output")

    provider, model_id = _parse_provider(model_name)
    _write_raw_llm_artifacts(llm_result=llm_result, run_dir=artifacts.run_dir, provider=provider)

    sys_chars = len(prompt.system_prompt)
    usr_chars = len(prompt.user_prompt)
    vs_tool = lambda t: (t.tool_name or "").startswith("mcp__voltsnip__")

    run_result = RunResult(
        run_id=run_id,
        suite_path=str(Path(suite_path).expanduser().resolve()),
        output_root=str(Path(output_root).expanduser().resolve()),
        task_id=task.task.id, task_name=task.task.name,
        variant_id=variant.id, model_name=model_name, status=status,
        variant_mode=variant.mode, variant_memory_enabled=variant.memory_enabled,
        variant_tools_enabled=variant.tools_enabled, variant_retrieval_mode=variant.retrieval_mode,
        variant_instruction_mode=variant.instruction_mode, variant_context_surface=variant.context_surface,
        variant_max_tool_roundtrips=variant.max_tool_roundtrips,
        task_category=task.task.category, task_difficulty=task.task.difficulty,
        task_line_start=task.task.line_start, task_line_end=task.task.line_end,
        required_snippet_keys=list(task.voltsnip.required_snippets),
        prompt=prompt, prompt_after_tools=prompt_after_tools,
        retrieved_snippets=retrieved_snippets, tool_traces=tool_traces,
        messages=[
            MessageTrace(role="system", content=prompt.system_prompt),
            MessageTrace(role="user", content=prompt.user_prompt),
            MessageTrace(role="assistant", content=llm_result.raw_output),
        ],
        raw_model_output=llm_result.raw_output, parsed_output=llm_result.parsed_output,
        token_usage=llm_result.token_usage,
        execution_trace=execution_trace,
        timings=TimingInfo(started_at=started_at, finished_at=finished_at, latency_ms=latency_ms),
        summary_metrics=SummaryMetrics(
            latency_ms=latency_ms,
            prompt_chars=sys_chars + usr_chars, output_chars=len(llm_result.raw_output),
            prompt_system_chars=sys_chars, prompt_user_chars=usr_chars,
            snippet_injected_chars=sum(len(s.code) for s in retrieved_snippets),
            model_provider=provider, model_id=model_id,
            snippet_count=len(retrieved_snippets), tool_call_count=len(tool_traces),
            voltsnip_tool_call_count=sum(1 for t in tool_traces if vs_tool(t)),
            native_tool_call_count=sum(1 for t in tool_traces if not vs_tool(t)),
            tool_error_count=sum(1 for t in tool_traces if t.error),
            used_tools=bool(tool_traces), used_voltsnip_tools=any(vs_tool(t) for t in tool_traces),
            structured_output_attempted=llm_result.structured_output_attempted,
            structured_output_succeeded=llm_result.structured_output_succeeded,
            fallback_parser_used=llm_result.fallback_parser_used,
            retrieval_latency_ms=retrieval_latency_ms,
            voltsnip_retry_count=voltsnip.retry_count_total if voltsnip else 0,
            voltsnip_rate_limit_count=voltsnip.rate_limit_error_count if voltsnip else 0,
            voltsnip_timeout_count=voltsnip.timeout_error_count if voltsnip else 0,
            voltsnip_error_count=voltsnip.error_count_total if voltsnip else 0,
            model_request_latency_ms=llm_result.request_latency_ms or model_latency_ms,
            model_request_started_at=llm_result.request_started_at,
            model_request_finished_at=llm_result.request_finished_at,
            model_request_id=llm_result.request_id, model_finish_reason=llm_result.finish_reason,
            token_usage=llm_result.token_usage,
        ),
        artifacts=artifacts, error=run_error,
    )

    score: ScoreResult | None = None
    execution_trace.record(
        function_name="_scoring_fork",
        file_path="vsevals/runner.py",
        line_number=209,
        decision_point="scoring_fork",
        context={"skip_scoring": resolved_cfg.skip_scoring, "status": status},
    )
    if status == "ok" and not resolved_cfg.skip_scoring:
        t_score = time.perf_counter()
        score = score_one(run_result=run_result, oracle=task.oracle, cfg=resolved_cfg, provider_keys=provider_keys)
        run_result.score = score
        run_result.summary_metrics.scoring_latency_ms = int((time.perf_counter() - t_score) * 1000)

    execution_trace.record(
        function_name="_pytest_fork",
        file_path="vsevals/runner.py",
        line_number=215,
        decision_point="pytest_fork",
        context={"auto_apply_patch": resolved_cfg.auto_apply_patch, "status": status},
    )
    if status == "ok" and resolved_cfg.auto_apply_patch:
        run_result.pytest_result = _run_patch_and_test(
            run_result=run_result, task=task,
            repo_root=_resolve_repo_root(repo_root or task.task.repo_root or suite.suite.default_repo_root, suite_path=suite_path),
            cfg=resolved_cfg,
        )

    t_art = time.perf_counter()
    _write_artifacts(run_result=run_result, score=score)
    run_result.summary_metrics.artifact_write_latency_ms = int((time.perf_counter() - t_art) * 1000)

    vs_calls = sum(1 for t in tool_traces if vs_tool(t))
    LOGGER.info("run finish  run_id=%s  status=%s  latency_ms=%d  snippets=%d  vs_tools=%d  native_tools=%d  score=%s",
                run_id, status, latency_ms, len(retrieved_snippets), vs_calls, len(tool_traces) - vs_calls,
                f"{score.overall_score:.3f}" if score else "n/a")
    return run_result


def _run_agent(*, task: SuiteTask, variant: VariantConfig, model_name: str, cfg: RunConfig,
               provider_keys: dict[str, str], voltsnip: VoltSnipClient | None,
               seed_snippets: list[RetrievedSnippet], target_file_content: str | None,
               repo_policy: str, repo_root: "Path | None" = None,
               run_dir: str | None = None,
               ) -> tuple[LLMResult, PromptBundle, PromptBundle, list[RetrievedSnippet], list[ToolTrace]]:
    snippets = _dedup_snippets(seed_snippets)
    tool_traces: list[ToolTrace] = []
    snippet_limit = cfg.snippet_context_limit or task.voltsnip.snippet_context_limit
    max_chars = cfg.snippet_context_max_chars or task.voltsnip.snippet_context_max_chars
    roundtrip_count = {"n": 0}

    def _build_prompt_after():
        return build_prompt(task=task, variant=variant, retrieved_snippets=snippets,
                            repo_policy_text=repo_policy, target_file_content=target_file_content,
                            voltsnip_base_url=cfg.voltsnip_base_url)

    prompt_sent = _build_prompt_after()
    provider, model_id = _parse_provider(model_name)

    trace = get_current_trace()
    if trace:
        trace.record(
            function_name="_provider_dispatch",
            file_path="vsevals/runner.py",
            line_number=267,
            decision_point="provider_dispatch",
            context={"provider": provider, "model_id": model_id},
        )

    if provider in ("claudecode", "codex"):
        from vsevals.providers.claudecode import call_claudecode
        from vsevals.providers.codex import call_codex
        tools = voltsnip_tool_schemas() if variant.tools_enabled else None
        turns = max(1, variant.max_tool_roundtrips)
        repo_root_str = str(repo_root) if repo_root else None
        call_fn = call_claudecode if provider == "claudecode" else call_codex
        llm_result = call_fn(
            model_id=model_id, system_prompt=prompt_sent.system_prompt,
            user_prompt=prompt_sent.user_prompt, cfg=cfg,
            tool_schemas=tools, max_tool_turns=turns,
            sidecar_files=prompt_sent.sidecar_files or None,
            run_dir=run_dir, repo_root=repo_root_str,
        )
        tool_traces.extend(llm_result.tool_traces)
        _merge_tool_snippets(tool_traces, snippets, voltsnip, cfg, task)
        return llm_result, prompt_sent, _build_prompt_after(), snippets, tool_traces

    if provider == "openai" and variant.tools_enabled:
        llm_result = call_llm(
            model_name=model_name, system_prompt=prompt_sent.system_prompt,
            user_prompt=prompt_sent.user_prompt, cfg=cfg, provider_keys=provider_keys,
            tool_schemas=voltsnip_tool_schemas(), max_tool_turns=max(1, variant.max_tool_roundtrips),
            sidecar_files=prompt_sent.sidecar_files or None,
        )
        return llm_result, prompt_sent, _build_prompt_after(), snippets, tool_traces

    tool_schemas = voltsnip_tool_schemas() if variant.tools_enabled else None
    tool_handlers: dict[str, Callable[[dict], dict]] | None = None

    if variant.tools_enabled and voltsnip:
        def _fetch_handler(payload: dict) -> dict:
            keys = [k for k in (payload.get("canonical_keys") or []) if isinstance(k, str) and k.strip()]
            if single := (payload.get("key") or payload.get("canonical_key")):
                if isinstance(single, str) and single.strip():
                    keys.append(single)
            return _invoke_tool(
                name="voltsnip.get_by_canonical_keys", args={"canonical_keys": keys[:snippet_limit]},
                voltsnip=voltsnip, snippets=snippets, tool_traces=tool_traces,
                roundtrip_count=roundtrip_count, max_roundtrips=variant.max_tool_roundtrips,
                fetch=lambda: voltsnip.get_by_canonical_keys(keys[:snippet_limit], limit=snippet_limit, max_chars=max_chars),
            )

        def _search_handler(payload: dict) -> dict:
            q = payload.get("query") or payload.get("intent") or ""
            k = max(1, min(int(payload.get("k", 4) or 4), snippet_limit))
            return _invoke_tool(
                name="voltsnip.semantic_search", args={"q": q, "k": k},
                voltsnip=voltsnip, snippets=snippets, tool_traces=tool_traces,
                roundtrip_count=roundtrip_count, max_roundtrips=variant.max_tool_roundtrips,
                fetch=lambda: voltsnip.semantic_search(q=q, k=k, max_chars=max_chars),
            )

        tool_handlers = {
            "get_snippet_by_canonical_key": _fetch_handler, "get_snippet_by_key": _fetch_handler,
            "search_memory": _search_handler, "search_snippets": _search_handler,
            "voltsnip_fetch_by_canonical_keys": _fetch_handler, "voltsnip_semantic_search": _search_handler,
        }

    llm_result = call_llm(
        model_name=model_name, system_prompt=prompt_sent.system_prompt,
        user_prompt=prompt_sent.user_prompt, cfg=cfg, provider_keys=provider_keys,
        tool_schemas=tool_schemas, tool_handlers=tool_handlers,
        max_tool_turns=max(1, variant.max_tool_roundtrips), sidecar_files=prompt_sent.sidecar_files or None,
    )
    return llm_result, prompt_sent, _build_prompt_after(), snippets, tool_traces


def _merge_tool_snippets(tool_traces: list[ToolTrace], snippets: list[RetrievedSnippet],
                         voltsnip: VoltSnipClient | None, cfg: RunConfig, task: SuiteTask) -> None:
    if not voltsnip or not tool_traces:
        return
    existing_keys = {s.canonical_key or s.id for s in snippets}
    limit = cfg.snippet_context_limit or task.voltsnip.snippet_context_limit
    max_chars = cfg.snippet_context_max_chars or task.voltsnip.snippet_context_max_chars
    keys_to_fetch: list[str] = []
    search_queries: list[str] = []

    for trace in tool_traces:
        tool_name = trace.tool_name or ""
        args = trace.tool_args or {}
        if any(t in tool_name for t in ("fetch", "canonical", "get_snippet_by_canonical_key", "get_snippet_by_key")):
            keys = list(args.get("canonical_keys") or [])
            if isinstance(args.get("canonical_key"), str): keys.append(args["canonical_key"])
            if isinstance(args.get("key"), str): keys.append(args["key"])
            for k in keys:
                if isinstance(k, str) and k.strip() and k not in existing_keys:
                    keys_to_fetch.append(k)
                    existing_keys.add(k)
        elif "search" in tool_name:
            if q := (args.get("intent") or args.get("query") or ""):
                if isinstance(q, str):
                    search_queries.append(q)

    if keys_to_fetch:
        try:
            snippets.extend(voltsnip.get_by_canonical_keys(keys_to_fetch, limit=limit, max_chars=max_chars))
        except Exception as exc:
            LOGGER.debug("_merge_tool_snippets fetch-by-key failed: %s", exc)

    for q in search_queries:
        try:
            for s in voltsnip.semantic_search(q=q, k=limit, max_chars=max_chars):
                if (key := s.canonical_key or s.id) not in existing_keys:
                    snippets.append(s)
                    existing_keys.add(key)
        except Exception as exc:
            LOGGER.debug("_merge_tool_snippets search failed q=%r: %s", q, exc)


def _invoke_tool(*, name: str, args: dict, voltsnip: VoltSnipClient, snippets: list[RetrievedSnippet],
                 tool_traces: list[ToolTrace], roundtrip_count: dict, max_roundtrips: int,
                 fetch: Callable[[], list[RetrievedSnippet]]) -> dict:
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
            existing_keys = {s.canonical_key or s.id for s in snippets}
            for s in new_snippets:
                if (key := s.canonical_key or s.id) not in existing_keys:
                    snippets.append(s)
                    existing_keys.add(key)
        except Exception as exc:
            error = str(exc)
            LOGGER.debug("tool %s failed: %s", name, exc)

    tool_traces.append(ToolTrace(
        roundtrip=roundtrip_count["n"], tool_name=name, tool_args=args,
        tool_result={"retrieved": len(new_snippets)} if not error else None,
        error=error, started_at=started, finished_at=datetime.now(timezone.utc),
        duration_ms=int((time.perf_counter() - t0) * 1000),
    ))
    return {"error": error} if error else {
        "snippets": [{"key": s.canonical_key or s.id, "title": s.title, "code": s.code} for s in new_snippets]
    }


def _retrieve_snippets(*, task: SuiteTask, variant: VariantConfig,
                       voltsnip: VoltSnipClient | None, cfg: RunConfig) -> list[RetrievedSnippet]:
    if not voltsnip or not (keys := list(task.voltsnip.required_snippets or [])):
        return []
    limit = cfg.snippet_context_limit or task.voltsnip.snippet_context_limit
    max_chars = cfg.snippet_context_max_chars or task.voltsnip.snippet_context_max_chars
    return voltsnip.get_by_canonical_keys(keys, limit=limit, max_chars=max_chars)


def _make_client(variant: VariantConfig, cfg: RunConfig) -> VoltSnipClient | None:
    if not (variant.memory_enabled or variant.tools_enabled):
        return None
    base_url = cfg.voltsnip_base_url or os.environ.get("VOLTSNIP_BASE_URL") or DEFAULT_VOLTSNIP_BASE_URL
    client = VoltSnipClient(base_url=base_url, timeout_seconds=cfg.voltsnip_timeout_seconds,
                            retry_attempts=cfg.voltsnip_retry_attempts)
    if not client.preflight_check():
        raise RuntimeError(f"VoltSnip preflight check failed. Cannot reach API at {base_url}")
    return client


def _load_provider_keys(cfg: RunConfig) -> dict[str, str]:
    env_map = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}
    keys = {p: v for p, k in env_map.items() if (v := os.environ.get(k))}
    if cfg.api_key:
        keys["_override"] = cfg.api_key
    keys.update(cfg.provider_api_keys)
    dotenv_map = {v: k for k, v in env_map.items()}
    for candidate in (Path.cwd() / ".env", Path.cwd() / "vsevals" / ".env"):
        if not candidate.exists():
            continue
        for line in candidate.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip("\"'")
            if k in dotenv_map and v:
                keys[dotenv_map[k]] = v
        break
    return keys


def _resolve_repo_root(repo_root: str | None, *, suite_path: str) -> Path | None:
    if not repo_root:
        return None
    candidate = Path(repo_root).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    if (cwd_try := (Path.cwd() / candidate).resolve()).exists():
        return cwd_try
    return (Path(suite_path).expanduser().resolve().parent / candidate).resolve()


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


def _dedup_snippets(snippets: list[RetrievedSnippet]) -> list[RetrievedSnippet]:
    seen: set[str] = set()
    result = []
    for s in snippets:
        if (key := s.canonical_key or s.id) not in seen:
            seen.add(key)
            result.append(s)
    return result


def _empty_llm_result() -> LLMResult:
    return LLMResult(
        raw_output="", parsed_output=GeneratedPayload(code="", comments=""),
        token_usage=TokenUsage(), structured_output_attempted=False,
        structured_output_succeeded=False, fallback_parser_used=False,
        request_started_at=None, request_finished_at=None,
        request_latency_ms=None, request_id=None, finish_reason=None,
    )


def _run_patch_and_test(*, run_result: RunResult, task: SuiteTask,
                        repo_root: Path | None, cfg: RunConfig) -> PytestResult:
    target_file = task.task.target_file
    test_command = task.task.test_command
    if not repo_root:
        return PytestResult(ran=False, error="no repo_root configured for task — cannot run pytest")
    if not target_file:
        return PytestResult(ran=False, error="no target_file configured for task — cannot apply patch")
    if not test_command:
        return PytestResult(ran=False, error="no test_command configured for task — nothing to run")
    if not (code := run_result.parsed_output.code).strip():
        return PytestResult(ran=False, error="generated code is empty — skipping pytest")

    try:
        patched_content = apply_line_range_rewrite(
            code=code, original_path=(Path(repo_root) / target_file).resolve(),
            line_start=task.task.line_start, line_end=task.task.line_end,
        )
    except Exception as exc:
        return PytestResult(ran=False, error=f"could not produce patched file: {exc}")

    patched_host_path = Path(run_result.artifacts.run_dir) / ("patched_" + Path(target_file).name)
    patched_host_path.write_text(patched_content, encoding="utf-8")
    LOGGER.info("patch+test  task=%s  target=%s", task.id, target_file)

    overlay_root: Path | None = None
    container: str | None = None
    try:
        overlay_root = Path(tempfile.mkdtemp(prefix="vsevals_overlay_"))
        materialize_overlay(repo_root=Path(repo_root), overlay_root=overlay_root)
        if (repo_venv := Path(repo_root) / ".venv").is_dir():
            shutil.copytree(str(repo_venv), str(overlay_root / ".venv"), symlinks=True)
        apply_rewrite(code=patched_content, target_file=target_file,
                      repo_root=Path(repo_root), overlay_root=overlay_root)
        try:
            container = start_test_container(image=cfg.pytest_docker_image, workdir=cfg.pytest_docker_workdir,
                                             timeout_seconds=cfg.pytest_timeout_seconds, host_workdir=str(overlay_root))
        except FileNotFoundError:
            return PytestResult(ran=False, error="docker not found — is Docker installed and running?")
        except RuntimeError as exc:
            return PytestResult(ran=False, error=str(exc))
        return run_pytest_in_docker(container_name=container, test_command=test_command, cfg=cfg)
    except Exception as exc:
        LOGGER.exception("patch+test failed  task=%s", task.id)
        return PytestResult(ran=False, error=str(exc))
    finally:
        if container: stop_test_container(container)
        if overlay_root: cleanup_overlay(overlay_root)


def _classify_error(exc: Exception) -> str:
    msg = str(exc).lower()
    name = type(exc).__name__.lower()
    checks = [
        ("AUTH_ERROR",        lambda: any(t in msg for t in ("api key", "apikey", "unauthorized", "invalid api", "authentication", "403", "401")) or any(t in name for t in ("api_key", "autherror"))),
        ("RATE_LIMIT_ERROR",  lambda: any(t in msg for t in ("rate limit", "ratelimit", "quota", "too many requests", "429"))),
        ("TIMEOUT",           lambda: "timeout" in name or "timeout" in msg or "timed out" in msg),
        ("NETWORK_ERROR",     lambda: any(t in msg for t in ("connection refused", "connection error", "name resolution", "ssl", "network", "unreachable", "eof")) or any(t in name for t in ("connectionerror", "networkerror", "sslerror"))),
        ("LLM_PARSE_ERROR",   lambda: any(t in msg for t in ("non-json output", "failed to parse", "parse", "json"))),
        ("RETRIEVAL_ERROR",   lambda: any(t in msg for t in ("voltsnip", "retrieval", "get_by_canonical", "semantic_search"))),
        ("CONFIG_ERROR",      lambda: any(t in msg for t in ("unknown task", "unknown variant", "unknown model")) or (isinstance(exc, (ValueError, KeyError)) and any(t in msg for t in ("not found", "missing")))),
        ("EMPTY_OUTPUT",      lambda: any(t in msg for t in ("empty", "no output", "empty code"))),
    ]
    for class_name, check in checks:
        if check():
            return class_name
    return "UNKNOWN_ERROR"


def _write_raw_llm_artifacts(*, llm_result: LLMResult, run_dir: str, provider: str = "") -> None:
    rd = Path(run_dir)
    p = f".{provider}" if provider else ""
    stdout = getattr(llm_result, "subprocess_stdout", "") or ""
    stderr = getattr(llm_result, "subprocess_stderr", "") or ""
    api_raw = getattr(llm_result, "api_response_raw", "") or ""
    stdout_file = rd / f"subprocess.stdout{p}.jsonl"
    stderr_file = rd / f"subprocess.stderr{p}.txt"
    if stdout and not stdout_file.exists():
        stdout_file.write_text(stdout, encoding="utf-8")
    if stderr and not stderr_file.exists():
        stderr_file.write_text(stderr, encoding="utf-8")
    if api_raw:
        (rd / f"llm_response{p}.json").write_text(api_raw, encoding="utf-8")


def _make_artifact_paths(*, output_root: str, task_id: str, variant_id: str, model_name: str) -> RunArtifactPaths:
    root = Path(output_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    sanitize = lambda s: re.sub(r"[^a-zA-Z0-9._-]+", "_", s.strip().lower()).strip("._") or "item"
    run_dir = root / "__".join([stamp, sanitize(task_id), sanitize(variant_id), sanitize(model_name)])
    run_dir.mkdir(parents=True, exist_ok=True)
    return RunArtifactPaths(
        run_dir=str(run_dir), full_dump_json=str(run_dir / "full_dump.json"),
        summary_dump_json=str(run_dir / "summary_dump.json"),
        code_output=str(run_dir / "generated_code.txt"),
        comments_output=str(run_dir / "generated_comments.txt"),
    )


def _write_artifacts(*, run_result: RunResult, score: ScoreResult | None) -> None:
    Path(run_result.artifacts.full_dump_json).write_text(
        json.dumps(run_result.model_dump(mode="json"), indent=2, ensure_ascii=False), encoding="utf-8")
    summary = {
        "run_id": run_result.run_id, "task_id": run_result.task_id, "task_name": run_result.task_name,
        "variant_id": run_result.variant_id, "model_name": run_result.model_name, "status": run_result.status,
        "metrics": run_result.summary_metrics.model_dump(mode="json"),
        "score": score.model_dump(mode="json") if score else None,
        "pytest_result": run_result.pytest_result.model_dump(mode="json") if run_result.pytest_result else None,
        "error": run_result.error.model_dump(mode="json") if run_result.error else None,
    }
    Path(run_result.artifacts.summary_dump_json).write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    Path(run_result.artifacts.code_output).write_text(run_result.parsed_output.code, encoding="utf-8")
    Path(run_result.artifacts.comments_output).write_text(run_result.parsed_output.comments, encoding="utf-8")

    run_dir = Path(run_result.artifacts.run_dir)
    prompt_data: dict = {"system": run_result.prompt.system_prompt, "user": run_result.prompt.user_prompt,
                         "context_surface": run_result.prompt.context_surface}
    if run_result.prompt_after_tools:
        prompt_data["system_after_tools"] = run_result.prompt_after_tools.system_prompt
        prompt_data["user_after_tools"] = run_result.prompt_after_tools.user_prompt
    (run_dir / "prompt.json").write_text(json.dumps(prompt_data, indent=2, ensure_ascii=False), encoding="utf-8")

    if score:
        (run_dir / "score_result.json").write_text(
            json.dumps(score.model_dump(mode="json"), indent=2, ensure_ascii=False), encoding="utf-8")

    if run_result.pytest_result and run_result.pytest_result.ran:
        (run_dir / "pytest.stdout.txt").write_text(run_result.pytest_result.stdout, encoding="utf-8")
        (run_dir / "pytest.stderr.txt").write_text(run_result.pytest_result.stderr, encoding="utf-8")

    # Auto-generate debug tour for failures and anomalies
    try:
        if should_generate_tour(run_result):
            tour_path = generate_debug_tour(run_result, run_dir)
            LOGGER.info("debug tour generated: %s", tour_path)
    except Exception as exc:
        LOGGER.warning("failed to generate debug tour: %s", exc)


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
    parser.add_argument("--judge-model-claudecode", action="store_true")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING"])
    args = parser.parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(levelname)s %(name)s %(message)s")

    judge_model = args.judge_model
    if args.judge_model_claudecode:
        _, model_id = args.model.split(":", 1) if ":" in args.model else ("openai", args.model)
        judge_model = f"claudecode:{model_id}"

    result = run_one(task_id=args.task, variant_id=args.variant, model_name=args.model,
                     suite_path=args.suite, output_dir=args.output_dir, repo_root=args.repo_root,
                     cfg=RunConfig(scoring_judge_model=judge_model))
    print(f"run_id:  {result.run_id}")
    print(f"status:  {result.status}")
    if result.score:
        print(f"score:   {result.score.overall_score:.3f}")
    if result.error:
        print(f"error:   {result.error.type}: {result.error.message}")
