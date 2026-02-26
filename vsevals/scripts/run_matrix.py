#!/usr/bin/env python3
"""Matrix runner: run all (task × variant × model) combinations.

Usage examples
--------------
# Smoke test with mock model
python scripts/run_matrix.py --suite suite.yaml --models mock:echo --variants P0

# Standard run: two models, all variants
python scripts/run_matrix.py \\
    --suite suite.yaml \\
    --models openai:gpt-5-nano,claudecode:claude-haiku-4-5 \\
    --variants P0,P1,P2,P3,P4,P5b,P5a,P6b,P6a

# Full scale run with cross-judge ensemble (default — no API keys needed)
python scripts/run_matrix.py \\
    --suite suite.yaml \\
    --models claudecode:claude-sonnet-4-6,codex:gpt-5.1-codex \\
    --output-dir ./vsevals_runs \\
    --spacing 1.25 \\
    --log-level INFO

# Resume an interrupted run (re-run missing rows only)
python scripts/run_matrix.py \\
    --suite suite.yaml \\
    --models openai:gpt-5-nano \\
    --resume ./vsevals_runs/matrix_20260225T140000Z
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NamedTuple

try:
    import fcntl as _fcntl
    _HAS_FCNTL = True
except ImportError:
    _HAS_FCNTL = False  # Windows — no flock, parallel writes are best-effort

# Ensure vsevals package is importable when run directly from repo root
_here = Path(__file__).resolve().parent.parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

from vsevals.loader import load_suite
from vsevals.models import RunConfig, RunResult
from vsevals.runner import run_one

LOGGER = logging.getLogger(__name__)
_PYTEST_SUMMARY_ITEM_RE = re.compile(
    r"(?P<count>\d+)\s+(?P<label>passed|failed|skipped|xfailed|xpassed|error|errors|deselected)\b",
    flags=re.IGNORECASE,
)
_PYTEST_COLLECTED_RE = re.compile(r"\bcollected\s+(?P<count>\d+)\s+items?\b", flags=re.IGNORECASE)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Run a matrix of (task × variant × model) evaluations.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Required
    p.add_argument("--suite", required=True, help="Path to suite YAML (e.g. suite.yaml)")
    p.add_argument("--models", default=None, help="Comma-separated model list (e.g. openai:gpt-5-nano,claudecode:claude-haiku-4-5). Default: all models listed in the suite YAML.")

    # Filters
    p.add_argument("--variants", default=None, help="Comma-separated variant IDs to run (default: all in suite)")
    p.add_argument("--tasks", default=None, help="Comma-separated task IDs to run (default: all in suite)")

    # Output
    p.add_argument("--output-dir", default="./vsevals_runs", help="Root directory for run artifacts")
    p.add_argument(
        "--matrix-dir", default=None,
        help="Use this exact path as the matrix output directory, bypassing the auto-generated "
             "matrix_TIMESTAMP name. Useful for parallel terminal runs that must share one dir. "
             "Created if it does not exist. Takes precedence over --output-dir.",
    )

    # Model & scoring
    p.add_argument(
        "--judge-model",
        default="openai:gpt-5.2+anthropic:claude-opus-4-6",
        help=(
            "Scoring judge model(s). Use '+' for a cross-provider ensemble. "
            "Default 'openai:gpt-5.2+anthropic:claude-opus-4-6' eliminates self-judging bias: "
            "claudecode cells judged by OpenAI, codex cells by Anthropic. "
            "Requires OPENAI_API_KEY + ANTHROPIC_API_KEY when --scoring-mode is 'hybrid' or 'llm'. "
            "For a key-free fallback use '--judge-model claudecode:claude-sonnet-4-6' (stored OAuth). "
            "Ensemble verdicts merged: LENIENT for positive checks, STRICT for failure checks. "
            "Ignored entirely when --scoring-mode is 'lexical'."
        ),
    )
    p.add_argument("--scoring-mode", default="lexical", choices=["lexical", "hybrid", "llm"],
                   help="Scoring mode during matrix run. Default is 'lexical' — no LLM judge calls. "
                        "Use 'hybrid' or 'llm' only for post-hoc re-scoring; judgement is a separate step.")
    p.add_argument("--constraint-threshold", type=float, default=0.7)

    # Runtime
    p.add_argument("--repo-root", default=None, help="Override repo root for all tasks")
    p.add_argument("--voltsnip-url", default=None, help="VoltSnip base URL (default: $VOLTSNIP_BASE_URL or http://localhost:8001)")
    p.add_argument("--spacing", type=float, default=0.35, help="Seconds to wait between same-provider calls")
    p.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING"])

    # Pytest / Docker
    p.add_argument("--auto-apply-patch", action="store_true", default=False,
                   help="After each run, write generated code to target file and run pytest in Docker")
    p.add_argument("--pytest-docker-image", default=None,
                   help="Docker image for pytest runs (default: moltsnip-pytest:latest or from usecase.yaml)")
    p.add_argument("--pytest-timeout", type=int, default=300,
                   help="pytest Docker timeout in seconds (default: 300)")

    # LLM call limits
    p.add_argument("--max-tokens", type=int, default=None,
                   help="Max output tokens per LLM call (default: model default). "
                        "Maps to max_completion_tokens (OpenAI) / max_tokens (Anthropic).")
    p.add_argument("--llm-timeout", type=int, default=300,
                   help="LLM call timeout in seconds for single-shot paths (default: 300). "
                        "MCP/tool-loop paths use max(600, timeout*2).")
    p.add_argument(
        "--max-tool-roundtrips",
        type=int,
        default=None,
        help="Override variant max_tool_roundtrips for tool-enabled variants (default: from suite).",
    )

    # Resume
    p.add_argument("--resume", default=None, help="Path to existing matrix dir to resume incomplete runs")

    return p


# ---------------------------------------------------------------------------
# Matrix cell
# ---------------------------------------------------------------------------


class Cell(NamedTuple):
    task_id: str
    variant_id: str
    model_name: str


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%H:%M:%S",
    )

    suite = load_suite(args.suite)
    if args.models:
        models = [m.strip() for m in args.models.split(",") if m.strip()]
    else:
        models = suite.model_names
        LOGGER.info("no --models specified, using all %d models from suite: %s", len(models), models)
    variants = [v.strip() for v in args.variants.split(",")] if args.variants else list(suite.variant_map)
    tasks = [t.strip() for t in args.tasks.split(",")] if args.tasks else list(suite.task_map)
    judge_specs = [m.strip() for m in args.judge_model.split("+") if m.strip()]
    judge_model_count = len(judge_specs)
    suite_sha256 = _sha256_file(Path(args.suite))
    task_spec_hashes = _task_spec_hashes(suite)
    variant_spec_hashes = _variant_spec_hashes(suite)
    git_meta = _git_metadata(Path(args.suite).expanduser().resolve().parent)

    # Validate filters
    for v in variants:
        if v not in suite.variant_map:
            parser.error(f"Unknown variant_id: {v!r}. Available: {sorted(suite.variant_map)}")
    for t in tasks:
        if t not in suite.task_map:
            parser.error(f"Unknown task_id: {t!r}. Available: {sorted(suite.task_map)}")

    if args.max_tool_roundtrips is not None:
        if args.max_tool_roundtrips < 1:
            parser.error("--max-tool-roundtrips must be >= 1")
        overridden = 0
        for variant in suite.variants:
            if variant.tools_enabled:
                variant.max_tool_roundtrips = args.max_tool_roundtrips
                overridden += 1
        LOGGER.info(
            "overriding max_tool_roundtrips=%d for %d tool-enabled variant(s)",
            args.max_tool_roundtrips,
            overridden,
        )

    cfg_kwargs: dict = dict(
        voltsnip_base_url=args.voltsnip_url,
        scoring_judge_model=args.judge_model,
        scoring_match_mode=args.scoring_mode,
        constraint_pass_threshold=args.constraint_threshold,
        auto_apply_patch=args.auto_apply_patch,
        pytest_timeout_seconds=args.pytest_timeout,
        llm_timeout_seconds=args.llm_timeout,
    )
    if args.max_tokens:
        cfg_kwargs["max_tokens"] = args.max_tokens
    if args.pytest_docker_image:
        cfg_kwargs["pytest_docker_image"] = args.pytest_docker_image
    cfg = RunConfig(**cfg_kwargs)

    # Build planned cells
    all_cells = [Cell(t, v, m) for t in tasks for v in variants for m in models]
    total = len(all_cells)
    LOGGER.info("matrix plan: %d cells (%d tasks × %d variants × %d models)", total, len(tasks), len(variants), len(models))

    # Setup matrix output dir — priority: --resume > --matrix-dir > auto-timestamp
    if args.resume:
        matrix_dir = Path(args.resume)
        LOGGER.info("resuming from %s", matrix_dir)
    elif args.matrix_dir:
        matrix_dir = Path(args.matrix_dir)
        LOGGER.info("using explicit matrix-dir=%s", matrix_dir)
    else:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        matrix_dir = Path(args.output_dir) / f"matrix_{stamp}"
    matrix_dir.mkdir(parents=True, exist_ok=True)

    # Resume: skip already-completed cells
    completed = _load_completed(matrix_dir)
    cells_to_run = [c for c in all_cells if _cell_key(c) not in completed]
    skipped = total - len(cells_to_run)
    if skipped:
        LOGGER.info("skipping %d completed cells, running %d remaining", skipped, len(cells_to_run))

    # How often to refresh the live scoreboard (every ~5% of cells, min 1)
    scoreboard_interval = max(1, total // 20)

    # Run
    results: list[dict] = list(completed.values())
    last_provider: dict[str, float] = {}

    for i, cell in enumerate(cells_to_run, 1):
        provider = cell.model_name.split(":")[0].lower()
        last_call = last_provider.get(provider, 0.0)
        wait = args.spacing - (time.time() - last_call)
        if wait > 0:
            time.sleep(wait)

        LOGGER.info("[%d/%d] task=%s variant=%s model=%s", i, len(cells_to_run), cell.task_id, cell.variant_id, cell.model_name)
        t0 = time.time()
        try:
            result = run_one(
                task_id=cell.task_id,
                variant_id=cell.variant_id,
                model_name=cell.model_name,
                suite_path=args.suite,
                output_dir=str(matrix_dir / "runs"),
                repo_root=args.repo_root,
                cfg=cfg,
            )
            row = _result_to_row(result)
        except Exception as exc:
            LOGGER.error("cell failed task=%s variant=%s model=%s: %s", cell.task_id, cell.variant_id, cell.model_name, exc)
            row = _error_row(cell, exc)

        # Persist scoring/runtime config per row so mixed-judge/mixed-mode runs
        # remain analyzable without relying on matrix-level summary files.
        row["scoring_judge_model"] = args.judge_model
        row["scoring_mode"] = args.scoring_mode
        row["judge_model_count"] = judge_model_count
        row["judge_ensemble_used"] = judge_model_count > 1
        row["git_commit"] = git_meta.get("git_commit")
        row["git_branch"] = git_meta.get("git_branch")
        row["git_dirty"] = git_meta.get("git_dirty")
        row["suite_sha256"] = suite_sha256
        row["task_spec_hash"] = task_spec_hashes.get(cell.task_id)
        row["variant_spec_hash"] = variant_spec_hashes.get(cell.variant_id)

        last_provider[provider] = time.time()
        results.append(row)
        _append_csv_row(matrix_dir / "matrix_results.csv", row)

        elapsed = time.time() - t0
        score_str = f"score={row.get('overall_score', 'n/a')}" if "overall_score" in row else ""
        LOGGER.info("  → %s %s  %.1fs", row.get("status", "?"), score_str, elapsed)

        if i % scoreboard_interval == 0:
            _print_scoreboard(results, total)

    # Write final summary + print scoreboard
    _write_summary(matrix_dir, results, args)
    _print_scoreboard(results, total)
    print(f"  CSV:    {matrix_dir}/matrix_results.csv")
    print(f"  Report: {matrix_dir}/matrix_report.md")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cell_key(cell: Cell) -> str:
    return f"{cell.task_id}/{cell.variant_id}/{cell.model_name}"


def _load_completed(matrix_dir: Path) -> dict[str, dict]:
    csv_path = matrix_dir / "matrix_results.csv"
    if not csv_path.exists():
        return {}
    completed: dict[str, dict] = {}
    try:
        with csv_path.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                key = f"{row['task_id']}/{row['variant_id']}/{row['model_name']}"
                completed[key] = row
    except Exception as exc:
        LOGGER.warning("could not load completed cells from %s: %s", csv_path, exc)
    return completed


def _result_to_row(result: RunResult) -> dict:
    """Build a flat dict row with all metrics for the matrix CSV."""
    m = result.summary_metrics
    provider, model_id = result.model_name.split(":", 1) if ":" in result.model_name else ("openai", result.model_name)
    total_tokens = (result.token_usage.total_tokens or 0) or (
        (result.token_usage.prompt_tokens or 0) + (result.token_usage.completion_tokens or 0)
    )
    latency_s = m.latency_ms / 1000.0 if m.latency_ms else 0
    # Tokens per second: use completion tokens (output throughput) as primary signal
    completion_tokens = result.token_usage.completion_tokens or 0
    model_latency_s = (m.model_request_latency_ms or 0) / 1000.0
    tok_per_sec = round(completion_tokens / model_latency_s, 2) if model_latency_s > 0 and completion_tokens else None
    chars_per_sec = round(m.output_chars / latency_s, 2) if latency_s > 0 and m.output_chars else None

    # Tool aggregation
    tool_names = sorted({t.tool_name for t in result.tool_traces if t.tool_name})
    tool_durations = [t.duration_ms for t in result.tool_traces if t.duration_ms is not None]
    tool_dur_total = sum(tool_durations) if tool_durations else None
    tool_dur_max = max(tool_durations) if tool_durations else None
    tool_dur_avg = round(sum(tool_durations) / len(tool_durations)) if tool_durations else None
    # Tool roundtrip detail (for post-hoc analysis of agent behaviour)
    tool_roundtrips_used = max((t.roundtrip for t in result.tool_traces), default=0)
    tool_errors = [t.error for t in result.tool_traces if t.error]
    tool_first_error = tool_errors[0][:300] if tool_errors else None

    # Snippet coverage
    required = result.required_snippet_keys
    retrieved_keys = {s.canonical_key or s.id for s in result.retrieved_snippets}
    hit_keys = [k for k in required if k in retrieved_keys]
    missing_keys = [k for k in required if k not in retrieved_keys]
    coverage = round(len(hit_keys) / len(required), 4) if required else None
    # Retrieved snippet metadata (language, tags, titles for semantic analysis)
    snippet_titles = ";".join(s.title for s in result.retrieved_snippets if s.title)
    snippet_langs  = ";".join(s.language for s in result.retrieved_snippets if s.language)
    snippet_tags   = ";".join(tag for s in result.retrieved_snippets for tag in s.tags)

    # Conversation metrics (for prompt effectiveness / multi-turn analysis)
    messages_count = len(result.messages)
    assistant_chars = sum(len(msg.content) for msg in result.messages if msg.role == "assistant")

    # Raw + parsed output size signals
    raw_output_preview   = result.raw_model_output[:400] if result.raw_model_output else ""
    parsed_code_chars    = len(result.parsed_output.code)
    parsed_comments_chars = len(result.parsed_output.comments)

    # Memory signal
    memory_signal = _compute_memory_signal(result)

    # Task line range coverage (how many lines does this task target)
    line_range_size: int | None = None
    if result.task_line_start is not None and result.task_line_end is not None:
        line_range_size = result.task_line_end - result.task_line_start + 1
    tool_budget_utilization = (
        round(m.tool_call_count / result.variant_max_tool_roundtrips, 4)
        if result.variant_max_tool_roundtrips > 0
        else None
    )
    tool_success_count = max(0, m.tool_call_count - m.tool_error_count)
    tool_success_rate = (
        round(tool_success_count / m.tool_call_count, 4)
        if m.tool_call_count > 0 else None
    )
    reliability = _reliability_counts(result)

    # New research metrics — collected now, incorporated into overall_score later
    generated_code = result.parsed_output.code or ""
    _vs_constraints  = _voltsnip_constraint_split(
        result.score.constraint_results if result.score else []
    )
    _snippet_util    = _snippet_code_utilization(result.retrieved_snippets, generated_code)
    _code_size       = _code_size_metrics(generated_code)

    row: dict = {
        # Identity
        "run_id": result.run_id,
        "task_id": result.task_id,
        "variant_id": result.variant_id,
        "model_name": result.model_name,
        "model_provider": provider,
        "model_id": model_id,
        "status": result.status,
        # Task metadata (for grouping/filtering in hypothesis analysis)
        "task_name": result.task_name,
        "task_category": result.task_category,
        "task_difficulty": result.task_difficulty,
        "task_line_start": result.task_line_start,
        "task_line_end": result.task_line_end,
        "task_line_range_size": line_range_size,
        # Variant metadata (critical for P0–P6 hypothesis)
        "variant_mode": result.variant_mode,
        "variant_memory_enabled": result.variant_memory_enabled,
        "variant_tools_enabled": result.variant_tools_enabled,
        "variant_retrieval_mode": result.variant_retrieval_mode,
        "variant_instruction_mode": result.variant_instruction_mode,
        "variant_context_surface": result.variant_context_surface,
        "variant_max_tool_roundtrips": result.variant_max_tool_roundtrips,
        # Timestamps
        "run_started_at": result.timings.started_at.isoformat(),
        "run_finished_at": result.timings.finished_at.isoformat(),
        # Latency breakdown
        "latency_ms": m.latency_ms,
        "model_request_latency_ms": m.model_request_latency_ms,
        "retrieval_latency_ms": m.retrieval_latency_ms,
        "scoring_latency_ms": m.scoring_latency_ms,
        "artifact_write_latency_ms": m.artifact_write_latency_ms,
        "model_request_started_at": m.model_request_started_at.isoformat() if m.model_request_started_at else None,
        "model_request_finished_at": m.model_request_finished_at.isoformat() if m.model_request_finished_at else None,
        # Token usage
        "prompt_tokens": result.token_usage.prompt_tokens,
        "completion_tokens": result.token_usage.completion_tokens,
        "total_tokens": total_tokens or None,
        "cached_tokens": result.token_usage.cached_tokens or None,
        "thinking_tokens": result.token_usage.thinking_tokens,
        "cost_usd": result.token_usage.cost_usd,
        "completion_tokens_per_second": tok_per_sec,  # output throughput
        "output_chars_per_second": chars_per_sec,
        "model_request_id": m.model_request_id,
        "model_finish_reason": m.model_finish_reason,
        # Prompt size breakdown
        "prompt_chars": m.prompt_chars,
        "prompt_system_chars": m.prompt_system_chars,
        "prompt_user_chars": m.prompt_user_chars,
        "snippet_injected_chars": m.snippet_injected_chars,
        "output_chars": m.output_chars,
        # Tools
        "tool_call_count": m.tool_call_count,
        "tool_error_count": m.tool_error_count,
        "tool_success_count": tool_success_count,
        "tool_success_rate": tool_success_rate,
        "used_tools": m.used_tools,
        "tool_budget_utilization": tool_budget_utilization,
        "tool_names": ";".join(tool_names),
        "tool_duration_total_ms": tool_dur_total,
        "tool_duration_max_ms": tool_dur_max,
        "tool_duration_avg_ms": tool_dur_avg,
        # Reliability / retry telemetry
        "provider_retry_count": m.voltsnip_retry_count,
        "voltsnip_retry_count": m.voltsnip_retry_count,
        "voltsnip_rate_limit_count": m.voltsnip_rate_limit_count,
        "voltsnip_timeout_count": m.voltsnip_timeout_count,
        "voltsnip_error_count": m.voltsnip_error_count,
        "rate_limit_count": reliability["rate_limit_count"],
        "timeout_count": reliability["timeout_count"],
        "mcp_error_count": reliability["mcp_error_count"],
        # Structured output
        "structured_output_attempted": m.structured_output_attempted,
        "structured_output_succeeded": m.structured_output_succeeded,
        "fallback_parser_used": m.fallback_parser_used,
        # Snippets
        "snippet_count": m.snippet_count,
        "snippet_injected_count": len(result.prompt.injected_snippet_keys),
        "retrieved_snippet_keys": ";".join(sorted(retrieved_keys)),
        "required_snippet_count": len(required),
        "required_snippet_keys": ";".join(required),
        "required_snippet_hit_keys": ";".join(hit_keys),
        "required_snippet_missing_keys": ";".join(missing_keys),
        "required_snippet_retrieved_count": len(hit_keys),
        "required_snippet_missing_count": len(missing_keys),
        "required_snippet_coverage": coverage,
        # Memory / retrieval signal (key hypothesis metric)
        "memory_expected": result.variant_memory_enabled,
        "memory_signal": memory_signal,
        # Retrieved snippet metadata
        "snippet_retrieved_titles": snippet_titles,
        "snippet_retrieved_languages": snippet_langs,
        "snippet_retrieved_tags": snippet_tags,
        # Snippet utilization in generated code — did the model incorporate snippet text?
        # High utilization + high voltsnip_constraint_pass_rate = VoltSnip was the source.
        # Low  utilization + high voltsnip_constraint_pass_rate = model knew it independently.
        "snippet_utilized_count":    _snippet_util["snippet_utilized_count"],
        "snippet_utilized_fraction": _snippet_util["snippet_utilized_fraction"],
        "snippet_utilized_ids":      _snippet_util["snippet_utilized_ids"],
        # Generated code size (surgical patch vs whole-file rewrite)
        "generated_code_lines":          _code_size["generated_code_lines"],
        "generated_code_nonempty_lines": _code_size["generated_code_nonempty_lines"],
        "generated_code_comment_lines":  _code_size["generated_code_comment_lines"],
        # Tool roundtrip detail
        "tool_roundtrips_used": tool_roundtrips_used,
        "tool_first_error": tool_first_error,
        # Conversation metrics
        "messages_count": messages_count,
        "assistant_messages_chars": assistant_chars,
        # Output signals (for post-hoc judging without re-running)
        "raw_output_preview": raw_output_preview,
        "parsed_code_chars": parsed_code_chars,
        "parsed_comments_chars": parsed_comments_chars,
        # Reproducibility
        "suite_path": result.suite_path,
        # Artifacts (full set)
        "run_dir": result.artifacts.run_dir,
        "full_dump_json": result.artifacts.full_dump_json,
        "summary_dump_json": result.artifacts.summary_dump_json,
        "code_output": result.artifacts.code_output,
        "comments_output": result.artifacts.comments_output,
        "rewrite_output": result.artifacts.rewrite_output,
    }

    # Scoring
    if result.score:
        s = result.score
        # Per-constraint detail as semicolon-separated IDs (pass/fail lists)
        passed_constraint_ids = ";".join(r["id"] for r in s.constraint_results if r.get("passed"))
        failed_constraint_ids = ";".join(r["id"] for r in s.constraint_results if not r.get("passed"))
        # Constraints that hit via lexical vs llm only
        lexical_only_ids = ";".join(
            r["id"] for r in s.constraint_results
            if r.get("passed") and r.get("lexical_hit") and not r.get("llm_verdict")
        )
        llm_only_ids = ";".join(
            r["id"] for r in s.constraint_results
            if r.get("passed") and not r.get("lexical_hit") and r.get("llm_verdict")
        )
        # Compact per-constraint JSON for post-hoc judge replay
        # Fields: id, passed, lexical_hit, llm_verdict, expected, voltsnip_key
        _keep = {"id", "passed", "lexical_hit", "llm_verdict", "expected", "voltsnip_key"}
        constraint_results_json = json.dumps(
            [{k: v for k, v in r.items() if k in _keep} for r in s.constraint_results],
            separators=(",", ":"),
        )
        lexical_hit_count  = sum(1 for r in s.constraint_results if r.get("lexical_hit"))
        llm_verdict_count  = sum(1 for r in s.constraint_results if r.get("llm_verdict") is not None)
        row.update({
            "overall_score": s.overall_score,
            "passed": s.passed,
            "constraint_scoring_used": s.constraint_scoring_used,
            "constraint_checks_passed": s.constraint_checks_passed,
            "constraint_checks_total": s.constraint_checks_total,
            "constraint_failed_count": (
                (s.constraint_checks_total - s.constraint_checks_passed)
                if s.constraint_checks_total is not None and s.constraint_checks_passed is not None
                else None
            ),
            "constraint_pass_rate": (
                round(s.constraint_checks_passed / s.constraint_checks_total, 4)
                if s.constraint_checks_total
                and s.constraint_checks_passed is not None
                else None
            ),
            "constraint_pass_threshold": s.constraint_pass_threshold,
            "constraint_passed_ids": passed_constraint_ids,
            "constraint_failed_ids": failed_constraint_ids,
            "constraint_lexical_only_ids": lexical_only_ids,
            "constraint_llm_only_ids": llm_only_ids,
            "constraint_results_json": constraint_results_json,
            "constraint_lexical_hit_count": lexical_hit_count,
            "constraint_llm_verdict_count": llm_verdict_count,
            # VoltSnip vs generic constraint decomposition — core of the research claim.
            # voltsnip_constraint_pass_rate: "did the fix follow org-specific VoltSnip policies?"
            # generic_constraint_pass_rate:  "did the fix satisfy baseline quality checks?"
            # A model scoring high on generic but low on voltsnip fixed the bug without
            # VoltSnip patterns — suggesting VoltSnip wasn't needed for that cell.
            **_vs_constraints,
            "hidden_requirements_score": s.hidden_requirements.score,
            "hidden_requirements_matched": s.hidden_requirements.matched,
            "hidden_requirements_total": s.hidden_requirements.total,
            "success_indicators_score": s.success_indicators.score,
            "success_indicators_matched": s.success_indicators.matched,
            "success_indicators_total": s.success_indicators.total,
            "failure_modes_score": s.failure_modes.score,
            "failure_modes_matched": s.failure_modes.matched,
            "failure_modes_total": s.failure_modes.total,
            "evaluation_criteria_score": s.evaluation_criteria.score,
            "evaluation_criteria_matched": s.evaluation_criteria.matched,
            "evaluation_criteria_total": s.evaluation_criteria.total,
            "evaluation_criteria_notes": ";".join(s.evaluation_criteria_notes),
        })

    # Pytest
    if result.pytest_result:
        pr = result.pytest_result
        pytest_counts = _parse_pytest_counts(pr.stdout, pr.stderr)
        row.update({
            "pytest_ran": pr.ran,
            "pytest_passed": pr.passed,
            "pytest_returncode": pr.returncode,
            "pytest_duration_ms": pr.duration_ms,
            "pytest_docker_image": pr.docker_image,
            "pytest_error": (pr.error or "")[:300],
            "pytest_stdout_file": result.artifacts.run_dir + "/pytest.stdout.txt" if pr.ran else None,
            "pytest_stderr_file": result.artifacts.run_dir + "/pytest.stderr.txt" if pr.ran else None,
            "pytest_total": pytest_counts["total"],
            "pytest_passed_count": pytest_counts["passed"],
            "pytest_failed_count": pytest_counts["failed"],
            "pytest_skipped_count": pytest_counts["skipped"],
            "pytest_xfailed_count": pytest_counts["xfailed"],
            "pytest_xpassed_count": pytest_counts["xpassed"],
            "pytest_errors_count": pytest_counts["errors"],
            "pytest_deselected_count": pytest_counts["deselected"],
        })

    # Errors
    if result.error:
        row["error_type"] = result.error.type
        row["error_class"] = result.error.error_class
        row["error_message"] = result.error.message[:300]

    return row


def _compute_memory_signal(result: RunResult) -> str:
    """Classify how memory/snippet retrieval went for this run.

    Signal values (mirrors old harness):
      NO_MEMORY_EXPECTED         — variant doesn't use memory (P0/P1)
      RETRIEVAL_OK               — all required snippets retrieved
      RETRIEVAL_PARTIAL          — some required snippets retrieved
      RETRIEVAL_ATTEMPTED_NO_HITS — tools used but none of the required keys fetched
      RETRIEVAL_MISSED           — memory expected but nothing retrieved
    """
    if not result.variant_memory_enabled and not result.variant_tools_enabled:
        return "NO_MEMORY_EXPECTED"

    required = set(result.required_snippet_keys)
    if not required:
        return "NO_MEMORY_EXPECTED"

    retrieved_keys = {s.canonical_key or s.id for s in result.retrieved_snippets}
    hits = required.intersection(retrieved_keys)

    if hits == required:
        return "RETRIEVAL_OK"
    if hits:
        return "RETRIEVAL_PARTIAL"
    if result.summary_metrics.tool_call_count > 0 or result.summary_metrics.snippet_count > 0:
        return "RETRIEVAL_ATTEMPTED_NO_HITS"
    return "RETRIEVAL_MISSED"


def _reliability_counts(result: RunResult) -> dict[str, int]:
    """Derive coarse reliability counters from run-level telemetry."""
    m = result.summary_metrics
    rate_limit_count = m.voltsnip_rate_limit_count
    timeout_count = m.voltsnip_timeout_count
    mcp_error_count = 0

    err = result.error
    if err:
        if err.error_class == "RATE_LIMIT_ERROR":
            rate_limit_count += 1
        if err.error_class == "TIMEOUT":
            timeout_count += 1
        msg = (err.message or "").lower()
        if "mcp" in msg:
            mcp_error_count += 1

    mcp_error_count += sum(
        1
        for trace in result.tool_traces
        if trace.error and (
            "mcp" in (trace.error or "").lower()
            or "voltsnip" in (trace.tool_name or "").lower()
            or "fetch" in (trace.tool_name or "").lower()
        )
    )

    pr = result.pytest_result
    if pr and pr.error:
        msg = pr.error.lower()
        if "timeout" in msg or "timed out" in msg:
            timeout_count += 1

    return {
        "rate_limit_count": int(rate_limit_count),
        "timeout_count": int(timeout_count),
        "mcp_error_count": int(mcp_error_count),
    }


def _voltsnip_constraint_split(constraint_results: list[dict]) -> dict[str, int | float | str | None]:
    """Split constraint results into VoltSnip-attributed vs generic.

    A constraint is "VoltSnip-attributed" when it carries a non-empty voltsnip_key,
    meaning the expected fix pattern is explicitly sourced from a VoltSnip snippet.
    Generic constraints encode general code-quality requirements that a model could
    satisfy without ever consulting VoltSnip.

    This decomposition is the core of the research claim:
      voltsnip_constraint_pass_rate  → "did the fix follow VoltSnip org policies?"
      generic_constraint_pass_rate   → "did the fix satisfy baseline quality checks?"

    A model scoring high on generic but low on voltsnip means it fixed the bug
    without the org-specific VoltSnip patterns — i.e. VoltSnip wasn't needed.
    A model scoring high on both means VoltSnip context was absorbed and applied.
    """
    vs_all      = [r for r in constraint_results if r.get("voltsnip_key")]
    gen_all     = [r for r in constraint_results if not r.get("voltsnip_key")]
    vs_passed   = [r for r in vs_all  if r.get("passed")]
    gen_passed  = [r for r in gen_all if r.get("passed")]

    vs_total    = len(vs_all)
    gen_total   = len(gen_all)

    return {
        "voltsnip_constraints_total":       vs_total,
        "voltsnip_constraints_passed":      len(vs_passed),
        "voltsnip_constraint_pass_rate":    round(len(vs_passed) / vs_total, 4) if vs_total else None,
        "voltsnip_constraint_passed_ids":   ";".join(r["id"] for r in vs_passed),
        "voltsnip_constraint_failed_ids":   ";".join(r["id"] for r in vs_all if not r.get("passed")),
        "generic_constraints_total":        gen_total,
        "generic_constraints_passed":       len(gen_passed),
        "generic_constraint_pass_rate":     round(len(gen_passed) / gen_total, 4) if gen_total else None,
    }


_SNIPPET_UTIL_SKIP = frozenset({
    "return", "import", "class", "def", "self", "None", "True", "False",
    "raise", "except", "finally", "continue", "break", "lambda", "assert",
    "yield", "async", "await", "with", "from", "pass", "elif", "else", "if",
    "for", "while", "try", "not", "and", "or", "in", "is", "as", "global",
    "nonlocal", "print", "super", "object", "list", "dict", "set", "tuple",
    "str", "int", "float", "bool", "type", "None", "True", "False",
})


def _snippet_code_utilization(snippets: list, generated_code: str) -> dict[str, int | float | None]:
    """Measure how many injected/retrieved snippets left lexical traces in the generated code.

    A snippet is "utilized" when ≥1 distinctive identifier from its code
    (identifier ≥ 6 chars, not a common Python keyword) appears verbatim in
    the generated code output.

    This is distinct from constraint_pass_rate:
      - Constraints ask "does the output satisfy the policy spec?"
      - Utilization asks "did the model copy/adapt text from the snippet itself?"

    High utilization + high voltsnip_constraint_pass_rate  → snippet was the source.
    High utilization + low  voltsnip_constraint_pass_rate  → model referenced snippets
                                                             but misapplied the pattern.
    Low  utilization + high voltsnip_constraint_pass_rate  → model knew the pattern
                                                             independently (no VoltSnip needed).
    Low  utilization + low  voltsnip_constraint_pass_rate  → snippet context unused.
    """
    total = len(snippets)
    if not total or not generated_code:
        return {
            "snippet_utilized_count": 0,
            "snippet_utilized_fraction": None,
            "snippet_utilized_ids": "",
        }

    utilized_ids: list[str] = []
    for snip in snippets:
        code = (getattr(snip, "code", None) or "").strip()
        if not code:
            continue
        # Extract identifiers of 6+ chars that aren't common keywords
        tokens = [
            t for t in re.findall(r'\b([a-zA-Z_][a-zA-Z0-9_]{5,})\b', code)
            if t not in _SNIPPET_UTIL_SKIP
        ]
        if not tokens:
            continue
        # Check the first 30 distinctive tokens — avoid false positives from long files
        if any(tok in generated_code for tok in tokens[:30]):
            snip_id = getattr(snip, "canonical_key", None) or getattr(snip, "id", None) or ""
            utilized_ids.append(snip_id)

    utilized = len(utilized_ids)
    return {
        "snippet_utilized_count":    utilized,
        "snippet_utilized_fraction": round(utilized / total, 4) if total else None,
        "snippet_utilized_ids":      ";".join(utilized_ids),
    }


def _code_size_metrics(generated_code: str) -> dict[str, int | None]:
    """Measure the size and structure of the generated code output.

    Surgical patches that change only the necessary lines are better evidence
    of VoltSnip utility than whole-file rewrites that incidentally satisfy
    constraint checks.  These metrics let us control for output verbosity when
    comparing scores across models.
    """
    if not generated_code or not generated_code.strip():
        return {
            "generated_code_lines":        0,
            "generated_code_nonempty_lines": 0,
            "generated_code_comment_lines":  0,
        }
    lines = generated_code.splitlines()
    nonempty = sum(1 for ln in lines if ln.strip())
    comment  = sum(1 for ln in lines if ln.strip().startswith(("#", "//", "/*", "*", "'''", '"""')))
    return {
        "generated_code_lines":          len(lines),
        "generated_code_nonempty_lines": nonempty,
        "generated_code_comment_lines":  comment,
    }


def _parse_pytest_counts(stdout: str, stderr: str) -> dict[str, int | None]:
    """Parse pytest summary counts from stdout/stderr."""
    text = "\n".join([stdout or "", stderr or ""])
    counts: dict[str, int] = {}

    # Look from bottom up so we prefer the final pytest summary line.
    for line in reversed(text.splitlines()):
        line = line.strip()
        if not line:
            continue
        matches = list(_PYTEST_SUMMARY_ITEM_RE.finditer(line))
        if not matches:
            continue
        parsed: dict[str, int] = {}
        for match in matches:
            label = match.group("label").lower()
            if label == "error":
                label = "errors"
            parsed[label] = parsed.get(label, 0) + int(match.group("count"))
        if parsed:
            counts = parsed
            break

    total = (
        counts.get("passed", 0)
        + counts.get("failed", 0)
        + counts.get("skipped", 0)
        + counts.get("xfailed", 0)
        + counts.get("xpassed", 0)
        + counts.get("errors", 0)
    )

    if total == 0:
        collected_total: int | None = None
        for line in reversed(text.splitlines()):
            match = _PYTEST_COLLECTED_RE.search(line)
            if match:
                collected_total = int(match.group("count"))
                break
        total_or_none = collected_total
    else:
        total_or_none = total

    # Some pytest summaries place deselected/xfailed/xpassed on a different line.
    # Back-fill them if we did not see them on the chosen summary line.
    if "deselected" not in counts:
        m = re.search(r"\b(\d+)\s+deselected\b", text, flags=re.IGNORECASE)
        if m:
            counts["deselected"] = int(m.group(1))
    if "xfailed" not in counts:
        m = re.search(r"\b(\d+)\s+xfailed\b", text, flags=re.IGNORECASE)
        if m:
            counts["xfailed"] = int(m.group(1))
    if "xpassed" not in counts:
        m = re.search(r"\b(\d+)\s+xpassed\b", text, flags=re.IGNORECASE)
        if m:
            counts["xpassed"] = int(m.group(1))
    if "errors" not in counts:
        m = re.search(r"\b(\d+)\s+errors?\b", text, flags=re.IGNORECASE)
        if m:
            counts["errors"] = int(m.group(1))

    return {
        "total": total_or_none,
        "passed": counts.get("passed"),
        "failed": counts.get("failed"),
        "skipped": counts.get("skipped"),
        "xfailed": counts.get("xfailed"),
        "xpassed": counts.get("xpassed"),
        "errors": counts.get("errors"),
        "deselected": counts.get("deselected"),
    }


def _classify_exc(exc: Exception) -> str:
    """Lightweight error classifier for unhandled matrix-level exceptions."""
    msg = str(exc).lower()
    if any(t in msg for t in ("api key", "unauthorized", "401", "403", "authentication")):
        return "AUTH_ERROR"
    if any(t in msg for t in ("rate limit", "429", "quota")):
        return "RATE_LIMIT_ERROR"
    if "timeout" in msg or "timed out" in msg:
        return "TIMEOUT"
    if any(t in msg for t in ("connection refused", "connection error", "network")):
        return "NETWORK_ERROR"
    if any(t in msg for t in ("unknown task", "unknown variant")):
        return "CONFIG_ERROR"
    return "UNKNOWN_ERROR"


def _error_row(cell: Cell, exc: Exception) -> dict:
    error_class = _classify_exc(exc)
    return {
        "task_id": cell.task_id,
        "variant_id": cell.variant_id,
        "model_name": cell.model_name,
        "status": "error",
        "error_type": type(exc).__name__,
        "error_class": error_class,
        "error_message": str(exc)[:300],
        "latency_ms": 0,
        "rate_limit_count": 1 if error_class == "RATE_LIMIT_ERROR" else 0,
        "timeout_count": 1 if error_class == "TIMEOUT" else 0,
        "mcp_error_count": 1 if "mcp" in str(exc).lower() else 0,
    }


def _sha256_file(path: Path) -> str | None:
    try:
        data = path.expanduser().resolve().read_bytes()
    except Exception:
        return None
    return hashlib.sha256(data).hexdigest()


def _json_sha256(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _task_spec_hashes(suite: Any) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for task in suite.tasks:
        hashes[task.id] = _json_sha256(task.model_dump(mode="json"))
    return hashes


def _variant_spec_hashes(suite: Any) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for variant in suite.variants:
        hashes[variant.id] = _json_sha256(variant.model_dump(mode="json"))
    return hashes


def _git_metadata(cwd: Path) -> dict[str, Any]:
    """Best-effort git provenance. Returns None values outside git repos."""
    def _run_git(args: list[str], *, check: bool = True) -> str | None:
        try:
            proc = subprocess.run(
                ["git", *args],
                cwd=str(cwd),
                capture_output=True,
                text=True,
                check=check,
            )
            return proc.stdout.strip()
        except Exception:
            return None

    root = _run_git(["rev-parse", "--show-toplevel"])
    if not root:
        return {"git_commit": None, "git_branch": None, "git_dirty": None}

    root_path = Path(root)
    commit = _run_git(["rev-parse", "HEAD"])
    branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"])
    status = _run_git(["status", "--porcelain"], check=False) or ""
    return {
        "git_commit": commit,
        "git_branch": branch,
        "git_dirty": bool(status.strip()),
        "git_root": str(root_path),
    }


# ---------------------------------------------------------------------------
# Canonical CSV schema
# ---------------------------------------------------------------------------
# Fixed column order for all matrix CSV output.  Every row — success, error,
# resumed — uses this schema.  Missing fields default to "".  This prevents:
#   • Schema drift when the first row is an error row (fewer keys)
#   • Column misalignment when resumed rows have a different key set
#   • float() / bool() crashes on wrong-column values during report generation
# If you add new metrics, append them here.
_CANONICAL_COLUMNS: list[str] = [
    # Identity
    "run_id", "task_id", "variant_id", "model_name", "model_provider", "model_id", "status",
    # Provenance / reproducibility
    "git_commit", "git_branch", "git_dirty",
    "suite_sha256", "suite_path", "task_spec_hash", "variant_spec_hash",
    # Task metadata
    "task_name", "task_category", "task_difficulty",
    "task_line_start", "task_line_end", "task_line_range_size",
    # Variant metadata (P0-P6 hypothesis)
    "variant_mode", "variant_memory_enabled", "variant_tools_enabled",
    "variant_retrieval_mode", "variant_instruction_mode",
    "variant_context_surface", "variant_max_tool_roundtrips",
    # Timestamps
    "run_started_at", "run_finished_at",
    "model_request_started_at", "model_request_finished_at",
    # Latency breakdown
    "latency_ms", "model_request_latency_ms", "retrieval_latency_ms",
    "scoring_latency_ms", "artifact_write_latency_ms",
    # Token usage
    "prompt_tokens", "completion_tokens", "total_tokens",
    "cached_tokens",       # server-side prompt cache hits (OpenAI auto / Anthropic cache_control)
    "thinking_tokens",     # reasoning / extended-thinking tokens (o-series, extended thinking)
    "cost_usd",            # estimated cost in USD from pricing table
    "completion_tokens_per_second", "output_chars_per_second",
    "model_request_id", "model_finish_reason",
    # Prompt size breakdown
    "prompt_chars", "prompt_system_chars", "prompt_user_chars",
    "snippet_injected_chars", "output_chars",
    # Tools
    "tool_call_count", "tool_error_count", "tool_success_count", "tool_success_rate",
    "used_tools", "tool_names",
    "tool_budget_utilization",
    "tool_duration_total_ms", "tool_duration_max_ms", "tool_duration_avg_ms",
    "tool_roundtrips_used", "tool_first_error",
    # Reliability / retry telemetry
    "provider_retry_count",
    "voltsnip_retry_count", "voltsnip_rate_limit_count", "voltsnip_timeout_count", "voltsnip_error_count",
    "rate_limit_count", "timeout_count", "mcp_error_count",
    # Structured output
    "structured_output_attempted", "structured_output_succeeded", "fallback_parser_used",
    # Snippets
    "snippet_count", "snippet_injected_count",
    "retrieved_snippet_keys", "required_snippet_count", "required_snippet_keys",
    "required_snippet_hit_keys", "required_snippet_missing_keys",
    "required_snippet_retrieved_count", "required_snippet_missing_count",
    "required_snippet_coverage",
    "snippet_retrieved_titles", "snippet_retrieved_languages", "snippet_retrieved_tags",
    # Snippet utilization in generated code — did the model absorb the snippet text?
    "snippet_utilized_count", "snippet_utilized_fraction", "snippet_utilized_ids",
    # Generated code size (surgical fix vs whole-file rewrite)
    "generated_code_lines", "generated_code_nonempty_lines", "generated_code_comment_lines",
    # Memory / retrieval signal (key hypothesis metric)
    "memory_expected", "memory_signal",
    # Conversation metrics
    "messages_count", "assistant_messages_chars",
    # Output signals (for post-hoc judging without re-running)
    "raw_output_preview", "parsed_code_chars", "parsed_comments_chars",
    # Scoring
    "scoring_judge_model", "scoring_mode", "judge_model_count", "judge_ensemble_used",
    "overall_score", "passed",
    "constraint_scoring_used", "constraint_checks_passed", "constraint_checks_total",
    "constraint_failed_count", "constraint_pass_rate",
    "constraint_pass_threshold",
    "constraint_passed_ids", "constraint_failed_ids",
    "constraint_lexical_only_ids", "constraint_llm_only_ids",
    "hidden_requirements_score", "hidden_requirements_matched", "hidden_requirements_total",
    "success_indicators_score", "success_indicators_matched", "success_indicators_total",
    "failure_modes_score", "failure_modes_matched", "failure_modes_total",
    "evaluation_criteria_score", "evaluation_criteria_matched", "evaluation_criteria_total",
    "evaluation_criteria_notes",
    "constraint_results_json", "constraint_lexical_hit_count", "constraint_llm_verdict_count",
    # VoltSnip vs generic constraint decomposition (core of the research claim)
    # voltsnip_constraint_pass_rate: follows org-specific VoltSnip patterns?
    # generic_constraint_pass_rate:  satisfies baseline quality checks independently?
    "voltsnip_constraints_total", "voltsnip_constraints_passed", "voltsnip_constraint_pass_rate",
    "voltsnip_constraint_passed_ids", "voltsnip_constraint_failed_ids",
    "generic_constraints_total", "generic_constraints_passed", "generic_constraint_pass_rate",
    # Pytest
    "pytest_ran", "pytest_passed", "pytest_returncode", "pytest_duration_ms",
    "pytest_total", "pytest_passed_count", "pytest_failed_count", "pytest_skipped_count",
    "pytest_xfailed_count", "pytest_xpassed_count", "pytest_errors_count", "pytest_deselected_count",
    "pytest_docker_image", "pytest_error", "pytest_stdout_file", "pytest_stderr_file",
    # Errors
    "error_type", "error_class", "error_message",
    # Artifacts
    "run_dir", "full_dump_json", "summary_dump_json", "rewrite_output",
    "code_output", "comments_output",
]


def _truthy(val: object) -> bool:
    """Safely coerce a value to bool, handling CSV string round-trips.

    CSV always round-trips booleans as strings ("True" / "False").
    The Python expression ``bool("False")`` evaluates to True (non-empty string),
    which would make every resumed failed row appear as passed.
    """
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.strip().lower() in ("true", "1", "yes")
    return bool(val)


def _safe_float(val: object, default: float = 0.0) -> float:
    """Convert to float without raising — handles "", None, misaligned CSV values."""
    try:
        return float(val)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _append_csv_row(path: Path, row: dict) -> None:
    """Append one row to the matrix CSV using the canonical fixed schema.

    Always writes all _CANONICAL_COLUMNS (missing values become "").
    Uses an exclusive flock (macOS/Linux) so two parallel terminal runs
    that share the same --matrix-dir don't interleave their writes or
    double-write the CSV header.
    """
    with path.open("a", newline="", encoding="utf-8") as f:
        if _HAS_FCNTL:
            _fcntl.flock(f, _fcntl.LOCK_EX)
        # Re-check header need after acquiring lock (another process may have
        # just written it between our open() and flock()).
        write_header = path.stat().st_size == 0
        writer = csv.DictWriter(
            f,
            fieldnames=_CANONICAL_COLUMNS,
            extrasaction="ignore",   # silently drop keys not in schema
            restval="",              # fill missing keys with ""
        )
        if write_header:
            writer.writeheader()
        writer.writerow(row)
        if _HAS_FCNTL:
            _fcntl.flock(f, _fcntl.LOCK_UN)


def _write_summary(matrix_dir: Path, results: list[dict], args: argparse.Namespace) -> None:
    ok = [r for r in results if r.get("status") == "ok"]
    passed = [r for r in ok if _truthy(r.get("passed"))]
    avg_score = round(sum(_safe_float(r.get("overall_score", 0)) for r in ok) / len(ok), 4) if ok else None
    pytest_ok = [r for r in results if _truthy(r.get("pytest_ran")) and _truthy(r.get("pytest_passed"))]

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "suite": args.suite,
        "models": args.models,
        "variants": args.variants or "all",
        "tasks": args.tasks or "all",
        "judge_model": args.judge_model,
        "total_cells": len(results),
        "ok_cells": len(ok),
        "passed_cells": len(passed),
        "pytest_passed_cells": len(pytest_ok),
        "avg_score": avg_score,
        "matrix_dir": str(matrix_dir),
        "csv_path": str(matrix_dir / "matrix_results.csv"),
        "report_path": str(matrix_dir / "matrix_report.md"),
    }
    (matrix_dir / "matrix_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_matrix_report(matrix_dir, results, args, summary)
    LOGGER.debug("summary written to %s/matrix_summary.json", matrix_dir)


def _write_matrix_report(matrix_dir: Path, results: list[dict], args: argparse.Namespace, summary: dict) -> None:
    """Write a markdown table report identical in structure to the old harness."""
    ok = [r for r in results if r.get("status") == "ok"]
    passed = [r for r in ok if _truthy(r.get("passed"))]
    avg_score = summary.get("avg_score")

    lines: list[str] = [
        "# Matrix Evaluation Report",
        "",
        f"- Suite: `{args.suite}`",
        f"- Total runs: **{len(results)}**",
        f"- Successful runs: **{len(ok)}**",
        f"- Failed runs: **{len(results) - len(ok)}**",
        f"- Avg oracle score: **{avg_score:.4f}**" if avg_score is not None else "- Avg score: n/a",
        f"- Primary pass rate: **{len(passed)/len(ok):.4f}**" if ok else "",
        "",
        "## Per-Run Table",
        "",
        "| task | variant | model | status | score | passed | memory_signal | req_coverage | snippets | tools | latency_ms | prompt_tokens | completion_tokens | pytest |",
        "|---|---|---|---|---:|---|---|---:|---:|---:|---:|---:|---:|---|",
    ]

    for r in sorted(results, key=lambda x: (x.get("task_id", ""), x.get("variant_id", ""), x.get("model_name", ""))):
        score = r.get("overall_score", "")
        # _safe_float prevents crash on misaligned columns from resumed runs
        score_str = f"{_safe_float(score):.4f}" if score not in ("", None) else "-"
        # _truthy prevents "False" string being treated as truthy
        passed_str = "yes" if _truthy(r.get("passed")) else ("no" if r.get("passed") not in ("", None) else "-")
        pytest_str = "ok" if _truthy(r.get("pytest_passed")) else ("fail" if _truthy(r.get("pytest_ran")) else "-")
        coverage = r.get("required_snippet_coverage", "")
        cov_str = f"{_safe_float(coverage):.2f}" if coverage not in ("", None) else "-"
        lines.append(
            f"| {r.get('task_id','')} "
            f"| {r.get('variant_id','')} "
            f"| `{r.get('model_name','')}` "
            f"| {r.get('status','')} "
            f"| {score_str} "
            f"| {passed_str} "
            f"| {r.get('memory_signal', '-')} "
            f"| {cov_str} "
            f"| {r.get('snippet_count', 0)} "
            f"| {r.get('tool_call_count', 0)} "
            f"| {r.get('latency_ms', '-')} "
            f"| {r.get('prompt_tokens', '-')} "
            f"| {r.get('completion_tokens', '-')} "
            f"| {pytest_str} |"
        )

    (matrix_dir / "matrix_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    LOGGER.debug("matrix report written to %s/matrix_report.md", matrix_dir)


_ANSI_G = "\033[32m"   # green
_ANSI_Y = "\033[33m"   # yellow
_ANSI_R = "\033[31m"   # red
_ANSI_C = "\033[36m"   # cyan
_ANSI_B = "\033[1m"    # bold
_ANSI_D = "\033[2m"    # dim
_ANSI_W = "\033[0m"    # reset


def _print_scoreboard(results: list[dict], total_planned: int) -> None:
    """Print a live model × variant pass-rate scoreboard to stdout.

    Columns = variants (P0–P6a), rows = models.
    Each cell shows pass-rate as a decimal (e.g. 0.73) or '·' if no data yet.
    Color: green ≥ 0.70, yellow 0.40–0.69, red < 0.40.
    Printed every ~5% of cells during the run and once at completion.
    """
    if not results:
        return

    # Stable insertion-order dedup of models / variants seen so far
    models: list[str] = list(dict.fromkeys(
        r["model_name"] for r in results if r.get("model_name")
    ))
    variants: list[str] = list(dict.fromkeys(
        r["variant_id"] for r in results if r.get("variant_id")
    ))
    if not models or not variants:
        return

    # Per-cell stats: (model, variant) → {ok, passed, errors, count}
    cell: dict[tuple[str, str], dict[str, int]] = {}
    for r in results:
        m, v = r.get("model_name", ""), r.get("variant_id", "")
        if not m or not v:
            continue
        key = (m, v)
        if key not in cell:
            cell[key] = {"ok": 0, "passed": 0, "err": 0, "count": 0}
        s = cell[key]
        s["count"] += 1
        if r.get("status") == "ok":
            s["ok"] += 1
            if _truthy(r.get("passed")):
                s["passed"] += 1
        elif r.get("status") == "error":
            s["err"] += 1

    # Global stats
    ok_rows = [r for r in results if r.get("status") == "ok"]
    passed_rows = [r for r in ok_rows if _truthy(r.get("passed"))]
    avg_score = (
        sum(_safe_float(r.get("overall_score", 0)) for r in ok_rows) / len(ok_rows)
        if ok_rows else 0.0
    )
    pct_done = len(results) / total_planned * 100 if total_planned else 0.0

    # Latency p95
    lats = sorted(_safe_float(r.get("latency_ms", 0)) for r in ok_rows if r.get("latency_ms") not in ("", None))
    p95 = lats[int(len(lats) * 0.95)] if len(lats) >= 5 else (lats[-1] if lats else 0)
    p95_str = f"{p95/1000:.0f}s" if p95 else "—"

    # Snippet coverage avg
    cov_vals = [_safe_float(r["required_snippet_coverage"]) for r in ok_rows if r.get("required_snippet_coverage") not in ("", None)]
    cov_str = f"{sum(cov_vals)/len(cov_vals):.2f}" if cov_vals else "—"

    # Shorten model names: remove prefix and common substrings
    def _short(name: str) -> str:
        _, _, tail = name.partition(":")
        return (tail
                .replace("claude-", "")
                .replace("-codex", "")
                .replace("gpt-", "gpt"))[:18]

    short_models = [_short(m) for m in models]
    model_col_w = max(len(s) for s in short_models) + 1

    # Column width for each variant (at least 5)
    var_w = max(5, max(len(v) for v in variants) + 1)

    # Bar: completed / total
    bar_filled = int(pct_done / 5)  # 20-char bar
    bar = "█" * bar_filled + "░" * (20 - bar_filled)

    # Assemble ─ separator
    total_w = model_col_w + len(variants) * var_w + 4
    sep = "─" * total_w

    def _color(rate: float) -> str:
        if rate >= 0.70:
            return _ANSI_G
        if rate >= 0.40:
            return _ANSI_Y
        return _ANSI_R

    lines: list[str] = [""]

    # ── Header ──────────────────────────────────────────────────────────────
    lines.append(
        f"{_ANSI_B}{'━' * total_w}{_ANSI_W}"
    )
    lines.append(
        f"  {_ANSI_B}vsevals{_ANSI_W}  "
        f"{len(results)}/{total_planned} ({pct_done:.0f}%)  "
        f"{_ANSI_C}[{bar}]{_ANSI_W}  "
        f"{_ANSI_G}✓ {len(passed_rows)}/{len(ok_rows)} passed{_ANSI_W}  "
        f"avg {avg_score:.3f}  cov {cov_str}  p95 {p95_str}"
    )
    lines.append(f"{_ANSI_B}{'━' * total_w}{_ANSI_W}")

    # ── Variant header row ───────────────────────────────────────────────────
    hdr = f"  {'':<{model_col_w}}"
    for v in variants:
        hdr += f"{_ANSI_D}{v:^{var_w}}{_ANSI_W}"
    lines.append(hdr)
    lines.append(f"  {_ANSI_D}{sep}{_ANSI_W}")

    # ── Per-model rows ────────────────────────────────────────────────────────
    for m, short in zip(models, short_models):
        row_parts = f"  {short:<{model_col_w}}"
        for v in variants:
            s = cell.get((m, v))
            if s is None or s["count"] == 0:
                row_parts += f"{_ANSI_D}{'·':^{var_w}}{_ANSI_W}"
            elif s["ok"] == 0:
                row_parts += f"{_ANSI_R}{'err':^{var_w}}{_ANSI_W}"
            else:
                rate = s["passed"] / s["ok"]
                val = f"{rate:.2f}"
                row_parts += f"{_color(rate)}{val:^{var_w}}{_ANSI_W}"
        lines.append(row_parts)

    lines.append(f"{_ANSI_B}{'━' * total_w}{_ANSI_W}")
    lines.append("")

    print("\n".join(lines), flush=True)


if __name__ == "__main__":
    main()
