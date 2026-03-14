"""Logic for mapping RunResult objects to flat CSV rows and managing the CSV schema."""

from __future__ import annotations

import csv
import json
import logging
import re
from pathlib import Path
from typing import Any

try:
    import fcntl as _fcntl
    _HAS_FCNTL = True
except ImportError:
    _HAS_FCNTL = False

from vsevals.models import RunResult

LOGGER = logging.getLogger(__name__)

_PYTEST_SUMMARY_ITEM_RE = re.compile(
    r"(?P<count>\d+)\s+(?P<label>passed|failed|skipped|xfailed|xpassed|error|errors|deselected)\b",
    flags=re.IGNORECASE,
)
_PYTEST_COLLECTED_RE = re.compile(r"\bcollected\s+(?P<count>\d+)\s+items?\b", flags=re.IGNORECASE)

_SNIPPET_UTIL_SKIP = frozenset({
    "return", "import", "class", "def", "self", "None", "True", "False",
    "raise", "except", "finally", "continue", "break", "lambda", "assert",
    "yield", "async", "await", "with", "from", "pass", "elif", "else", "if",
    "for", "while", "try", "not", "and", "or", "in", "is", "as", "global",
    "nonlocal", "print", "super", "object", "list", "dict", "set", "tuple",
    "str", "int", "float", "bool", "type",
})

CANONICAL_COLUMNS: list[str] = [
    "run_id", "task_id", "variant_id", "model_name", "model_provider", "model_id", "status",
    "git_commit", "git_branch", "git_dirty",
    "suite_sha256", "suite_path", "task_spec_hash", "variant_spec_hash",
    "task_name", "task_category", "task_difficulty",
    "task_line_start", "task_line_end", "task_line_range_size",
    "variant_mode", "variant_memory_enabled", "variant_tools_enabled",
    "variant_retrieval_mode", "variant_instruction_mode",
    "variant_context_surface", "variant_max_tool_roundtrips",
    "run_started_at", "run_finished_at",
    "model_request_started_at", "model_request_finished_at",
    "latency_ms", "model_request_latency_ms", "retrieval_latency_ms",
    "scoring_latency_ms", "artifact_write_latency_ms",
    "prompt_tokens", "completion_tokens", "total_tokens",
    "cached_tokens", "thinking_tokens", "cost_usd",
    "completion_tokens_per_second", "output_chars_per_second",
    "model_request_id", "model_finish_reason",
    "prompt_chars", "prompt_system_chars", "prompt_user_chars",
    "snippet_injected_chars", "output_chars",
    "tool_call_count", "tool_error_count", "tool_success_count", "tool_success_rate",
    "used_tools", "tool_names",
    "tool_budget_utilization",
    "tool_duration_total_ms", "tool_duration_max_ms", "tool_duration_avg_ms",
    "tool_roundtrips_used", "tool_first_error",
    "voltsnip_retry_count", "voltsnip_rate_limit_count",
    "voltsnip_timeout_count", "voltsnip_error_count",
    "rate_limit_count", "timeout_count", "mcp_error_count",
    "structured_output_attempted", "structured_output_succeeded", "fallback_parser_used",
    "snippet_count", "snippet_injected_count",
    "retrieved_snippet_keys", "required_snippet_count", "required_snippet_keys",
    "required_snippet_hit_keys", "required_snippet_missing_keys",
    "required_snippet_retrieved_count", "required_snippet_missing_count",
    "required_snippet_coverage",
    "snippet_retrieved_titles", "snippet_retrieved_languages", "snippet_retrieved_tags",
    "snippet_utilized_count", "snippet_utilized_fraction", "snippet_utilized_ids",
    "generated_code_lines", "generated_code_nonempty_lines", "generated_code_comment_lines",
    "memory_expected", "memory_signal",
    "messages_count", "assistant_messages_chars",
    "raw_output_preview", "parsed_code_chars", "parsed_comments_chars",
    "scoring_judge_model", "scoring_mode", "judge_model_count", "judge_ensemble_used",
    "overall_score",
    "constraint_scoring_used", "constraint_checks_passed", "constraint_checks_total",
    "constraint_failed_count", "constraint_pass_rate",
    "constraint_pass_threshold",
    "constraint_passed_ids", "constraint_failed_ids",
    "constraint_llm_verdict_ids",
    "hidden_requirements_score", "hidden_requirements_matched", "hidden_requirements_total",
    "success_indicators_score", "success_indicators_matched", "success_indicators_total",
    "failure_modes_score", "failure_modes_matched", "failure_modes_total",
    "evaluation_criteria_score", "evaluation_criteria_matched", "evaluation_criteria_total",
    "evaluation_criteria_notes",
    "constraint_results_json", "constraint_llm_verdict_count",
    "voltsnip_constraints_total", "voltsnip_constraints_passed", "voltsnip_constraint_pass_rate",
    "voltsnip_constraint_passed_ids", "voltsnip_constraint_failed_ids",
    "generic_constraints_total", "generic_constraints_passed", "generic_constraint_pass_rate",
    "pytest_ran", "pytest_passed", "pytest_returncode", "pytest_duration_ms",
    "pytest_total", "pytest_passed_count", "pytest_failed_count", "pytest_skipped_count",
    "pytest_xfailed_count", "pytest_xpassed_count", "pytest_errors_count", "pytest_deselected_count",
    "pytest_docker_image", "pytest_error", "pytest_stdout_file", "pytest_stderr_file",
    "error_type", "error_class", "error_message",
    "run_dir", "full_dump_json", "summary_dump_json",
    "code_output", "comments_output",
    "subprocess_stdout_jsonl", "subprocess_stderr_txt", "llm_response_json", "prompt_json",
    "process_passed", "process_fail_reason", "full_pass",
]


def result_to_row(result: RunResult) -> dict:
    provider, model_id = result.model_name.split(":", 1) if ":" in result.model_name else ("openai", result.model_name)
    m = result.summary_metrics
    tu = result.token_usage
    rd = result.artifacts.run_dir
    is_subprocess = provider in ("claudecode", "codex")

    line_range = (result.task_line_end - result.task_line_start + 1
                  if result.task_line_start is not None and result.task_line_end is not None else None)

    row: dict = {
        "run_id": result.run_id, "task_id": result.task_id, "variant_id": result.variant_id,
        "model_name": result.model_name, "model_provider": provider, "model_id": model_id,
        "status": result.status, "task_name": result.task_name, "task_category": result.task_category,
        "task_difficulty": result.task_difficulty, "task_line_start": result.task_line_start,
        "task_line_end": result.task_line_end, "task_line_range_size": line_range,
        "suite_path": result.suite_path, "variant_mode": result.variant_mode,
        "variant_memory_enabled": result.variant_memory_enabled,
        "variant_tools_enabled": result.variant_tools_enabled,
        "variant_retrieval_mode": result.variant_retrieval_mode,
        "variant_instruction_mode": result.variant_instruction_mode,
        "variant_context_surface": result.variant_context_surface,
        "variant_max_tool_roundtrips": result.variant_max_tool_roundtrips,
        "memory_expected": result.variant_memory_enabled,
        "memory_signal": _compute_memory_signal(result),
        "structured_output_attempted": m.structured_output_attempted,
        "structured_output_succeeded": m.structured_output_succeeded,
        "fallback_parser_used": m.fallback_parser_used,
        "run_started_at": result.timings.started_at.isoformat(),
        "run_finished_at": result.timings.finished_at.isoformat(),
        "latency_ms": m.latency_ms, "model_request_latency_ms": m.model_request_latency_ms,
        "retrieval_latency_ms": m.retrieval_latency_ms, "scoring_latency_ms": m.scoring_latency_ms,
        "artifact_write_latency_ms": m.artifact_write_latency_ms,
        "model_request_started_at": m.model_request_started_at.isoformat() if m.model_request_started_at else None,
        "model_request_finished_at": m.model_request_finished_at.isoformat() if m.model_request_finished_at else None,
        "prompt_tokens": tu.prompt_tokens, "completion_tokens": tu.completion_tokens,
        "total_tokens": tu.total_tokens or ((tu.prompt_tokens or 0) + (tu.completion_tokens or 0)) or None,
        "cached_tokens": tu.cached_tokens or None, "thinking_tokens": tu.thinking_tokens,
        "cost_usd": tu.cost_usd,
        "completion_tokens_per_second": round((tu.completion_tokens or 0) / ((m.model_request_latency_ms or 0) / 1000.0), 2) if (m.model_request_latency_ms or 0) > 0 and (tu.completion_tokens or 0) else None,
        "output_chars_per_second": round(m.output_chars / (m.latency_ms / 1000.0), 2) if m.latency_ms and m.output_chars else None,
        "model_request_id": m.model_request_id, "model_finish_reason": m.model_finish_reason,
        "prompt_chars": m.prompt_chars, "prompt_system_chars": m.prompt_system_chars,
        "prompt_user_chars": m.prompt_user_chars, "snippet_injected_chars": m.snippet_injected_chars,
        "output_chars": m.output_chars,
    }

    tool_names = sorted({t.tool_name for t in result.tool_traces if t.tool_name})
    durations = [t.duration_ms for t in result.tool_traces if t.duration_ms is not None]
    errors = [t.error for t in result.tool_traces if t.error]
    tool_success_count = max(0, m.tool_call_count - m.tool_error_count)
    row.update({
        "tool_call_count": m.tool_call_count, "tool_error_count": m.tool_error_count,
        "tool_success_count": tool_success_count,
        "tool_success_rate": round(tool_success_count / m.tool_call_count, 4) if m.tool_call_count > 0 else None,
        "used_tools": m.used_tools, "tool_names": ";".join(tool_names),
        "tool_budget_utilization": round(m.tool_call_count / result.variant_max_tool_roundtrips, 4) if result.variant_max_tool_roundtrips > 0 else None,
        "tool_duration_total_ms": sum(durations) if durations else None,
        "tool_duration_max_ms": max(durations) if durations else None,
        "tool_duration_avg_ms": round(sum(durations) / len(durations)) if durations else None,
        "tool_roundtrips_used": max((t.roundtrip for t in result.tool_traces), default=0),
        "tool_first_error": errors[0][:300] if errors else None,
    })

    counts = _reliability_counts(result)
    row.update({
        "voltsnip_retry_count": m.voltsnip_retry_count, "voltsnip_rate_limit_count": m.voltsnip_rate_limit_count,
        "voltsnip_timeout_count": m.voltsnip_timeout_count, "voltsnip_error_count": m.voltsnip_error_count,
        **counts,
    })

    required = result.required_snippet_keys
    retrieved_keys = {s.canonical_key or s.id for s in result.retrieved_snippets}
    hit_keys = [k for k in required if k in retrieved_keys]
    missing_keys = [k for k in required if k not in retrieved_keys]
    row.update({
        "snippet_count": m.snippet_count,
        "snippet_injected_count": len(result.prompt.injected_snippet_keys),
        "retrieved_snippet_keys": ";".join(sorted(retrieved_keys)),
        "required_snippet_count": len(required), "required_snippet_keys": ";".join(required),
        "required_snippet_hit_keys": ";".join(hit_keys),
        "required_snippet_missing_keys": ";".join(missing_keys),
        "required_snippet_retrieved_count": len(hit_keys), "required_snippet_missing_count": len(missing_keys),
        "required_snippet_coverage": round(len(hit_keys) / len(required), 4) if required else None,
        "snippet_retrieved_titles": ";".join(s.title for s in result.retrieved_snippets if s.title),
        "snippet_retrieved_languages": ";".join(s.language for s in result.retrieved_snippets if s.language),
        "snippet_retrieved_tags": ";".join(tag for s in result.retrieved_snippets for tag in s.tags),
        **_snippet_code_utilization(result.retrieved_snippets, result.parsed_output.code or ""),
    })

    generated_code = result.parsed_output.code or ""
    msgs = result.messages
    row.update({
        "raw_output_preview": result.raw_model_output[:400] if result.raw_model_output else "",
        "parsed_code_chars": len(generated_code),
        "parsed_comments_chars": len(result.parsed_output.comments),
        "messages_count": len(msgs),
        "assistant_messages_chars": sum(len(msg.content) for msg in msgs if msg.role == "assistant"),
        **_code_size_metrics(generated_code),
    })

    row.update({
        "run_dir": result.artifacts.run_dir, "full_dump_json": result.artifacts.full_dump_json,
        "summary_dump_json": result.artifacts.summary_dump_json,
        "code_output": result.artifacts.code_output, "comments_output": result.artifacts.comments_output,
        "subprocess_stdout_jsonl": str(Path(rd) / f"subprocess.stdout.{provider}.jsonl") if is_subprocess else None,
        "subprocess_stderr_txt": str(Path(rd) / f"subprocess.stderr.{provider}.txt") if is_subprocess else None,
        "llm_response_json": str(Path(rd) / f"llm_response.{provider}.json") if not is_subprocess else None,
        "prompt_json": str(Path(rd) / "prompt.json"),
    })

    if result.score:
        s = result.score
        passed_ids = ";".join(r["id"] for r in s.constraint_results if r.get("passed"))
        failed_ids = ";".join(r["id"] for r in s.constraint_results if not r.get("passed"))
        llm_verdict_ids = ";".join(r["id"] for r in s.constraint_results if r.get("llm_verdict"))
        _keep = {"id", "passed", "llm_verdict", "expected", "voltsnip_key"}
        row.update({
            "overall_score": s.overall_score, "constraint_scoring_used": s.constraint_scoring_used,
            "constraint_checks_passed": s.constraint_checks_passed, "constraint_checks_total": s.constraint_checks_total,
            "constraint_failed_count": (s.constraint_checks_total - s.constraint_checks_passed) if s.constraint_checks_total is not None and s.constraint_checks_passed is not None else None,
            "constraint_pass_rate": round(s.constraint_checks_passed / s.constraint_checks_total, 4) if s.constraint_checks_total and s.constraint_checks_passed is not None else None,
            "constraint_pass_threshold": s.constraint_pass_threshold,
            "constraint_passed_ids": passed_ids, "constraint_failed_ids": failed_ids,
            "constraint_llm_verdict_ids": llm_verdict_ids,
            "constraint_results_json": json.dumps([{k: v for k, v in r.items() if k in _keep} for r in s.constraint_results], separators=(",", ":")),
            "constraint_llm_verdict_count": sum(1 for r in s.constraint_results if r.get("llm_verdict") is not None),
            **_voltsnip_constraint_split(s.constraint_results),
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

    if result.pytest_result:
        pr = result.pytest_result
        pytest_counts = _parse_pytest_counts(pr.stdout, pr.stderr)
        row.update({
            "pytest_ran": pr.ran, "pytest_passed": pr.passed, "pytest_returncode": pr.returncode,
            "pytest_duration_ms": pr.duration_ms, "pytest_docker_image": pr.docker_image,
            "pytest_error": (pr.error or "")[:300],
            "pytest_stdout_file": rd + "/pytest.stdout.txt" if pr.ran else None,
            "pytest_stderr_file": rd + "/pytest.stderr.txt" if pr.ran else None,
            "pytest_total": pytest_counts["total"], "pytest_passed_count": pytest_counts["passed"],
            "pytest_failed_count": pytest_counts["failed"], "pytest_skipped_count": pytest_counts["skipped"],
            "pytest_xfailed_count": pytest_counts["xfailed"], "pytest_xpassed_count": pytest_counts["xpassed"],
            "pytest_errors_count": pytest_counts["errors"], "pytest_deselected_count": pytest_counts["deselected"],
        })

    if result.error:
        row.update({
            "error_type": result.error.type, "error_class": result.error.error_class,
            "error_message": result.error.message[:300],
        })

    process_passed, process_fail_reason = _compute_process_passed(result)
    row.update({
        "process_passed": process_passed, "process_fail_reason": process_fail_reason,
        "full_pass": bool(result.score and result.score.passed and process_passed),
    })
    return row


def _compute_memory_signal(result: RunResult) -> str:
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
    m = result.summary_metrics
    return "RETRIEVAL_ATTEMPTED_NO_HITS" if m.tool_call_count > 0 or m.snippet_count > 0 else "RETRIEVAL_MISSED"


def _reliability_counts(result: RunResult) -> dict[str, int]:
    m = result.summary_metrics
    rate_limit_count = m.voltsnip_rate_limit_count
    timeout_count = m.voltsnip_timeout_count
    mcp_error_count = 0
    if result.error:
        err = result.error
        if err.error_class == "RATE_LIMIT_ERROR":
            rate_limit_count += 1
        if err.error_class == "TIMEOUT":
            timeout_count += 1
        if "mcp" in (err.message or "").lower():
            mcp_error_count += 1
    mcp_error_count += sum(
        1 for trace in result.tool_traces
        if trace.error and (
            "mcp" in (trace.error or "").lower()
            or "voltsnip" in (trace.tool_name or "").lower()
            or "fetch" in (trace.tool_name or "").lower()
        )
    )
    if result.pytest_result and result.pytest_result.error:
        msg = result.pytest_result.error.lower()
        if "timeout" in msg or "timed out" in msg:
            timeout_count += 1
    return {"rate_limit_count": int(rate_limit_count), "timeout_count": int(timeout_count), "mcp_error_count": int(mcp_error_count)}


def _compute_process_passed(result: RunResult) -> tuple[bool, str]:
    if not (result.score and result.score.passed):
        return False, "outcome_failed"
    m = result.summary_metrics
    failures: list[str] = []
    if result.variant_memory_enabled and result.required_snippet_keys:
        required = set(result.required_snippet_keys)
        retrieved = {s.canonical_key or s.id for s in result.retrieved_snippets}
        missing = required - retrieved
        if missing:
            failures.append(f"retrieval_incomplete(coverage={round(len(required & retrieved) / len(required), 3)})")
    if result.variant_tools_enabled:
        if m.tool_call_count == 0:
            failures.append("no_tool_calls")
        elif m.tool_call_count == m.tool_error_count:
            failures.append(f"all_tool_calls_failed({m.tool_error_count} errors)")
    return (True, "") if not failures else (False, ";".join(failures))


def _voltsnip_constraint_split(results: list[dict]) -> dict[str, Any]:
    vs_all = [r for r in results if r.get("voltsnip_key")]
    gen_all = [r for r in results if not r.get("voltsnip_key")]
    vs_passed = [r for r in vs_all if r.get("passed")]
    gen_passed = [r for r in gen_all if r.get("passed")]
    vs_total, gen_total = len(vs_all), len(gen_all)
    return {
        "voltsnip_constraints_total": vs_total,
        "voltsnip_constraints_passed": len(vs_passed),
        "voltsnip_constraint_pass_rate": round(len(vs_passed) / vs_total, 4) if vs_total else None,
        "voltsnip_constraint_passed_ids": ";".join(r["id"] for r in vs_passed),
        "voltsnip_constraint_failed_ids": ";".join(r["id"] for r in vs_all if not r.get("passed")),
        "generic_constraints_total": gen_total,
        "generic_constraints_passed": len(gen_passed),
        "generic_constraint_pass_rate": round(len(gen_passed) / gen_total, 4) if gen_total else None,
    }


def _snippet_code_utilization(snippets: list, code: str) -> dict[str, Any]:
    total = len(snippets)
    if not total or not code:
        return {"snippet_utilized_count": 0, "snippet_utilized_fraction": None, "snippet_utilized_ids": ""}
    utilized_ids: list[str] = []
    for snip in snippets:
        s_code = (getattr(snip, "code", None) or "").strip()
        if not s_code:
            continue
        tokens = [t for t in re.findall(r'\b([a-zA-Z_][a-zA-Z0-9_]{5,})\b', s_code) if t not in _SNIPPET_UTIL_SKIP]
        if tokens and any(tok in code for tok in tokens[:30]):
            utilized_ids.append(getattr(snip, "canonical_key", None) or getattr(snip, "id", None) or "")
    utilized = len(utilized_ids)
    return {
        "snippet_utilized_count": utilized,
        "snippet_utilized_fraction": round(utilized / total, 4) if total else None,
        "snippet_utilized_ids": ";".join(utilized_ids),
    }


def _code_size_metrics(code: str) -> dict[str, int]:
    if not code or not code.strip():
        return {"generated_code_lines": 0, "generated_code_nonempty_lines": 0, "generated_code_comment_lines": 0}
    lines = code.splitlines()
    return {
        "generated_code_lines": len(lines),
        "generated_code_nonempty_lines": sum(1 for ln in lines if ln.strip()),
        "generated_code_comment_lines": sum(1 for ln in lines if ln.strip().startswith(("#", "//", "/*", "*", "'''", '"""'))),
    }


def _parse_pytest_counts(stdout: str, stderr: str) -> dict[str, int | None]:
    lines = (stdout or "").splitlines() + (stderr or "").splitlines()
    counts: dict[str, int] = {}
    for line in reversed(lines):
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

    total: int | None = sum(counts.get(k, 0) for k in ("passed", "failed", "skipped", "xfailed", "xpassed", "errors"))
    if not total:
        total = next(
            (int(m.group("count")) for line in reversed(lines) if (m := _PYTEST_COLLECTED_RE.search(line))),
            None,
        )
    for k in ("deselected", "xfailed", "xpassed", "errors"):
        if k not in counts:
            pattern = r"\b(\d+)\s+" + ("errors?" if k == "errors" else k) + r"\b"
            m = re.search(pattern, "\n".join(lines), flags=re.IGNORECASE)
            if m:
                counts[k] = int(m.group(1))
    return {
        "total": total, "passed": counts.get("passed"), "failed": counts.get("failed"),
        "skipped": counts.get("skipped"), "xfailed": counts.get("xfailed"),
        "xpassed": counts.get("xpassed"), "errors": counts.get("errors"),
        "deselected": counts.get("deselected"),
    }


def append_csv_row(path: Path, row: dict) -> None:
    with path.open("a", newline="", encoding="utf-8") as f:
        if _HAS_FCNTL:
            _fcntl.flock(f, _fcntl.LOCK_EX)
        write_header = path.stat().st_size == 0
        writer = csv.DictWriter(f, fieldnames=CANONICAL_COLUMNS, extrasaction="ignore", restval="")
        if write_header:
            writer.writeheader()
        writer.writerow(row)
        if _HAS_FCNTL:
            f.flush()
            _fcntl.flock(f, _fcntl.LOCK_UN)


def append_completed_entry(path: Path, entry: dict) -> None:
    with path.open("a", encoding="utf-8") as f:
        if _HAS_FCNTL:
            _fcntl.flock(f, _fcntl.LOCK_EX)
        f.write(json.dumps(entry, separators=(",", ":"), ensure_ascii=False) + "\n")
        if _HAS_FCNTL:
            f.flush()
            _fcntl.flock(f, _fcntl.LOCK_UN)


def load_completed(matrix_dir: Path) -> dict[str, dict]:
    jsonl_path = matrix_dir / "completed.jsonl"
    if jsonl_path.exists():
        return _load_completed_from_jsonl(jsonl_path)
    csv_path = matrix_dir / "matrix_results.csv"
    if csv_path.exists():
        return _load_completed_from_csv(csv_path)
    return {}


def _load_completed_from_jsonl(path: Path) -> dict[str, dict]:
    completed: dict[str, dict] = {}
    try:
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    tid, vid, mn = entry.get("task_id", ""), entry.get("variant_id", ""), entry.get("model_name", "")
                    if tid and vid and mn and entry.get("status") == "ok":
                        completed[f"{tid}/{vid}/{mn}"] = entry
                except Exception:
                    pass
    except Exception as exc:
        LOGGER.warning("could not load completed.jsonl from %s: %s", path, exc)
    return completed


def _load_completed_from_csv(path: Path) -> dict[str, dict]:
    completed: dict[str, dict] = {}
    try:
        with path.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                tid, vid, mn = row.get("task_id", ""), row.get("variant_id", ""), row.get("model_name", "")
                if tid and vid and mn and row.get("status") == "ok":
                    completed[f"{tid}/{vid}/{mn}"] = row
    except Exception as exc:
        LOGGER.warning("could not load completed cells from %s: %s", path, exc)
    return completed


def load_run_result(dump_path: Path):
    from vsevals.models import RunResult
    return RunResult.model_validate(json.loads(dump_path.read_text(encoding="utf-8")))


def row_from_dump(dump_path: Path) -> dict:
    return result_to_row(load_run_result(dump_path))


def classify_exc(exc: Exception) -> str:
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


def error_row(task_id: str, variant_id: str, model_name: str, exc: Exception) -> dict:
    error_class = classify_exc(exc)
    return {
        "task_id": task_id, "variant_id": variant_id, "model_name": model_name,
        "status": "error", "error_type": type(exc).__name__,
        "error_class": error_class, "error_message": str(exc)[:300],
        "latency_ms": 0,
        "rate_limit_count": 1 if error_class == "RATE_LIMIT_ERROR" else 0,
        "timeout_count": 1 if error_class == "TIMEOUT" else 0,
        "mcp_error_count": 1 if "mcp" in str(exc).lower() else 0,
    }


def truthy(val: object) -> bool:
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.strip().lower() in ("true", "1", "yes")
    return bool(val)


def safe_float(val: object, default: float = 0.0) -> float:
    try:
        return float(val) if val is not None else default
    except (TypeError, ValueError):
        return default
