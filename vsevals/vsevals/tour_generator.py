"""Auto-generate debug tours for failed/interesting runs using execution traces.

Instead of hardcoded line numbers, we read the ExecutionTrace embedded in each RunResult.
The trace records what actually executed, so tours are generated dynamically from real data.
"""

from __future__ import annotations

import json
from pathlib import Path

from vsevals.models import RunResult

# Fallback: if trace is None, use these. (Deprecated, but kept for backwards compatibility)
_FALLBACK_LINES = {
    "retrieval_fork": 97,
    "mode_fork": 104,
    "provider_dispatch": 267,
    "scoring_fork": 209,
    "pytest_fork": 215,
}


def generate_debug_tour(run_result: RunResult, artifact_dir: Path) -> Path:
    """Generate a CodeTour from the execution trace + RunResult.

    Each step is either:
    - A content step (narrative: what happened, with actual values)
    - A file+line step (code: extracted from trace, or fallback line numbers)

    Args:
        run_result: The completed RunResult with embedded execution_trace
        artifact_dir: Directory where artifacts were written

    Returns:
        Path to the generated .tour file
    """
    trace = run_result.execution_trace
    task_id = run_result.task_id
    variant_id = run_result.variant_id
    model_name = run_result.model_name
    failure_category = _classify_failure(run_result)

    steps = []

    # ── 1. Orientation ────────────────────────────────────────────────────────
    steps.append({
        "title": f"Debug: {task_id} / {variant_id} / {model_name}",
        "description": _orientation_text(run_result, failure_category),
    })

    # ── 2. Retrieval Fork (from trace or fallback) ────────────────────────────
    retrieval_step = _find_trace_step(trace, "retrieval_fork")
    steps.append({
        "file": retrieval_step.get("file", "vsevals/runner.py"),
        "line": retrieval_step.get("line", _FALLBACK_LINES["retrieval_fork"]),
        "title": f"Fork 1 — Retrieval: {'ENABLED' if run_result.variant_memory_enabled else 'SKIPPED'}",
        "description": _retrieval_fork_text(run_result),
    })

    # ── 3. Mode Fork (Agent vs Direct) ─────────────────────────────────────────
    mode_step = _find_trace_step(trace, "mode_fork")
    mode_label = "AGENT →" if run_result.variant_mode == "agent" else "DIRECT →"
    steps.append({
        "file": mode_step.get("file", "vsevals/runner.py"),
        "line": mode_step.get("line", _FALLBACK_LINES["mode_fork"]),
        "title": f"Fork 2 — Mode: {mode_label}",
        "description": _mode_fork_text(run_result),
    })

    # ── 4. Provider Dispatch (if agent) ────────────────────────────────────────
    if run_result.variant_mode == "agent":
        provider_step = _find_trace_step(trace, "provider_dispatch")
        provider = run_result.summary_metrics.model_provider or "unknown"
        steps.append({
            "file": provider_step.get("file", "vsevals/runner.py"),
            "line": provider_step.get("line", _FALLBACK_LINES["provider_dispatch"]),
            "title": f"Provider dispatch → {provider}",
            "description": _provider_dispatch_text(run_result),
        })

    # ── 5. Prompt Surface Dispatch ────────────────────────────────────────────
    steps.append({
        "file": "vsevals/prompt.py",
        "line": 145,
        "title": f"Prompt surface → '{run_result.variant_context_surface}'",
        "description": _prompt_surface_text(run_result),
    })

    # ── 6. Scoring Fork ───────────────────────────────────────────────────────
    scoring_step = _find_trace_step(trace, "scoring_fork")
    scoring_label = "RAN" if run_result.score else "SKIPPED"
    steps.append({
        "file": scoring_step.get("file", "vsevals/runner.py"),
        "line": scoring_step.get("line", _FALLBACK_LINES["scoring_fork"]),
        "title": f"Fork 3 — Scoring: {scoring_label}",
        "description": _scoring_fork_text(run_result),
    })

    # ── 7. Pytest Fork ────────────────────────────────────────────────────────
    pytest_step = _find_trace_step(trace, "pytest_fork")
    pytest_label = "RAN" if run_result.pytest_result else "SKIPPED"
    steps.append({
        "file": pytest_step.get("file", "vsevals/runner.py"),
        "line": pytest_step.get("line", _FALLBACK_LINES["pytest_fork"]),
        "title": f"Fork 4 — Pytest: {pytest_label}",
        "description": _pytest_fork_text(run_result, artifact_dir),
    })

    # ── 8. Artifacts ──────────────────────────────────────────────────────────
    steps.append({
        "title": "Artifacts written",
        "description": _artifacts_text(artifact_dir),
    })

    # ── 9. Debug Strategy ─────────────────────────────────────────────────────
    steps.append({
        "title": "What to do next",
        "description": _debug_strategy_text(run_result, failure_category),
    })

    tour = {
        "$schema": "https://aka.ms/codetour-schema",
        "title": f"Debug: {task_id} {variant_id} {model_name}",
        "description": f"Auto-generated debug tour — {failure_category}",
        "isPrimary": False,
        "steps": steps,
    }

    tour_path = artifact_dir / "debug-tour.tour"
    tour_path.write_text(json.dumps(tour, indent=2))
    return tour_path


# ── Helpers ─────────────────────────────────────────────────────────────────

def _find_trace_step(trace: object, decision_point: str) -> dict:
    """Extract file + line from trace for a decision point.

    Args:
        trace: ExecutionTrace object (or None)
        decision_point: e.g., "retrieval_fork", "mode_fork"

    Returns:
        {"file": "...", "line": N} or empty dict if not found
    """
    if trace is None:
        return {}

    # ExecutionTrace has a .steps attribute (list of ExecutionStep)
    if not hasattr(trace, "steps"):
        return {}

    for step in trace.steps:
        if hasattr(step, "decision_point") and step.decision_point == decision_point:
            return {
                "file": step.file_path if hasattr(step, "file_path") else "vsevals/runner.py",
                "line": step.line_number if hasattr(step, "line_number") else 0,
            }

    return {}


def _classify_failure(result: RunResult) -> str:
    """Classify the type of failure/outcome."""
    if result.status == "error":
        if result.error:
            msg = result.error.message.lower()
            if "EmptyOutput" in result.error.type:
                return "empty_output"
            if "indentation" in msg or "syntaxerror" in msg:
                return "syntax_error"
            if "timeout" in msg:
                return "timeout"
            return f"error_{result.error.error_class}"
        return "error_unknown"

    if result.pytest_result and not result.pytest_result.passed:
        return "pytest_failure"

    if result.score and result.score.overall_score < 0.5:
        return "low_judge_score"

    if result.summary_metrics.snippet_count == 0 and result.variant_memory_enabled:
        return "no_snippets_retrieved"

    if result.status == "ok":
        return "passed"

    return "unknown"


def _orientation_text(result: RunResult, category: str) -> str:
    """Generate orientation step text."""
    icons = {
        "passed": "✅ PASSED",
        "empty_output": "❌ EMPTY OUTPUT — model produced no code",
        "syntax_error": "❌ SYNTAX ERROR — generated code is unparseable",
        "pytest_failure": "❌ PYTEST FAILED — code didn't pass tests",
        "low_judge_score": "⚠️ LOW JUDGE SCORE — passed tests but judge scored < 0.5",
        "no_snippets_retrieved": "❌ NO SNIPPETS — retrieval enabled but nothing fetched",
        "timeout": "⏱️ TIMEOUT",
    }
    status_line = icons.get(category, f"❓ {category.upper()}")

    return (
        f"{status_line}\n\n"
        f"| | |\n"
        f"|---|---|\n"
        f"| **Task** | {result.task_id} |\n"
        f"| **Variant** | {result.variant_id} |\n"
        f"| **Model** | {result.model_name} |\n"
        f"| **Mode** | {result.variant_mode} |\n"
        f"| **Tools** | {result.variant_tools_enabled} |\n"
        f"| **Retrieval** | {result.variant_memory_enabled} |\n"
        f"| **Latency** | {result.summary_metrics.latency_ms}ms |\n\n"
        f"This tour links to the exact harness lines that ran for this cell."
    )


def _retrieval_fork_text(result: RunResult) -> str:
    """Retrieval fork explanation."""
    if not result.variant_memory_enabled:
        return (
            "Retrieval disabled (P0, P1 baselines). Model receives no snippets.\n\n"
            "This is expected for zero-shot baselines."
        )

    count = result.summary_metrics.snippet_count
    required = result.required_snippet_keys or []
    retrieved_keys = {s.canonical_key for s in (result.retrieved_snippets or []) if s.canonical_key}
    hits = [k for k in required if k in retrieved_keys]
    misses = [k for k in required if k not in retrieved_keys]

    coverage = f"{len(hits)}/{len(required)}" if required else "n/a"
    lines = [
        f"Retrieval enabled (`{result.variant_retrieval_mode}`)\n",
        f"- Snippets fetched: **{count}**",
        f"- Required key coverage: **{coverage}**",
        f"- Latency: `{result.summary_metrics.retrieval_latency_ms}ms`",
    ]
    if hits:
        lines.append(f"- ✓ Hit: `{'`, `'.join(hits[:3])}`")
    if misses:
        lines.append(f"- ✗ **Missed**: `{'`, `'.join(misses[:3])}`")
        lines.append("\n⚠️ Missing required snippets is the most common cause of org-API misses.")
    return "\n".join(lines)


def _mode_fork_text(result: RunResult) -> str:
    """Mode fork explanation."""
    if result.variant_mode == "agent":
        tool_note = (
            f"✓ {result.summary_metrics.tool_call_count} tool calls made "
            f"({result.summary_metrics.voltsnip_tool_call_count} VoltSnip)"
            if result.summary_metrics.tool_call_count > 0
            else "⚠️ **Zero tool calls** despite tools being enabled"
        )
        return (
            f"Agent mode with tools enabled. Model can fetch snippets on demand "
            f"over up to `{result.variant_max_tool_roundtrips}` roundtrips.\n\n"
            f"{tool_note}"
        )
    else:
        snippet_note = (
            f"Snippets pre-injected into system prompt "
            f"({result.summary_metrics.snippet_injected_chars} chars)."
            if result.variant_memory_enabled
            else "No snippets — pure zero-shot."
        )
        return (
            f"Direct mode (single prompt, no tools).\n\n"
            f"{snippet_note}\n\n"
            f"Prompt: `{result.summary_metrics.prompt_system_chars}` system + "
            f"`{result.summary_metrics.prompt_user_chars}` user chars"
        )


def _provider_dispatch_text(result: RunResult) -> str:
    """Provider dispatch explanation."""
    provider = result.summary_metrics.model_provider or "unknown"
    if provider in ("claudecode", "codex"):
        return (
            f"Using **{provider}** with internal tool loop.\n\n"
            f"The harness delegates tool handling to the provider subprocess."
        )
    else:
        return (
            f"Using **{provider}** with harness-managed tool loop.\n\n"
            f"The harness drives each tool call/response cycle."
        )


def _prompt_surface_text(result: RunResult) -> str:
    """Prompt surface dispatch explanation."""
    surface = result.variant_context_surface
    surface_notes = {
        "system": "Snippets injected into **system prompt** (P2).",
        "user": "Snippets injected into **user turn** (P0, P1).",
        "tools_only": "No snippets injected — model must fetch via tools (P3).",
        "skills_md_no_keys": "SKILL.md sidecar written; no key hints (P4).",
        "agents_md_no_keys": "AGENTS.md sidecar written; no key hints (P5).",
        "skills_agents_md_no_keys": "Both SKILL.md + AGENTS.md sidecars (P6).",
    }
    note = surface_notes.get(surface, f"Surface `{surface}` (check prompt.py)")
    return f"**Context surface**: `{surface}`\n\n{note}"


def _scoring_fork_text(result: RunResult) -> str:
    """Scoring fork explanation."""
    if not result.score:
        return (
            "Scoring skipped. Either `skip_scoring=True` or judge API failed.\n\n"
            "Check that OPENAI_API_KEY and ANTHROPIC_API_KEY are set, "
            "or re-run with `scripts/rescore_scoring.py`."
        )

    score = result.score
    verdict = "✅ PASS" if score.passed else "❌ FAIL"
    lines = [
        f"Scoring ran.\n",
        f"| | |",
        f"|---|---|",
        f"| **Overall score** | `{score.overall_score:.3f}` |",
        f"| **Verdict** | {verdict} |",
    ]
    if score.constraint_checks_total is not None:
        lines.append(f"| **Constraints** | {score.constraint_checks_passed}/{score.constraint_checks_total} passed |")

    if score.constraint_results:
        lines.append(f"\n**Constraint details**:")
        for i, c in enumerate(score.constraint_results[:5]):
            if isinstance(c, dict):
                icon = "✓" if c.get("passed") else "✗"
                name = c.get("name", f"constraint_{i}")
                lines.append(f"- {icon} {name}")

    return "\n".join(lines)


def _pytest_fork_text(result: RunResult, artifact_dir: Path) -> str:
    """Pytest fork explanation."""
    if not result.pytest_result:
        return (
            "Pytest skipped. Either `auto_apply_patch=False` or model produced no code.\n\n"
            "Tests were not run."
        )

    pr = result.pytest_result
    verdict = "✅ PASSED" if pr.passed else "❌ FAILED"
    text = f"Pytest ran.\n\n**Result: {verdict}**\n"

    stdout_path = artifact_dir / "pytest.stdout.txt"
    stderr_path = artifact_dir / "pytest.stderr.txt"
    if stdout_path.exists():
        text += f"\n📄 `pytest.stdout.txt` — full test output"
    if stderr_path.exists():
        text += f"\n📄 `pytest.stderr.txt` — test errors"

    return text


def _artifacts_text(artifact_dir: Path) -> str:
    """Artifacts explanation."""
    return (
        f"All artifacts for this cell in:\n"
        f"`{artifact_dir}`\n\n"
        f"Key files:\n"
        f"- `full_dump.json` — complete RunResult\n"
        f"- `generated_code.txt` — model's code output\n"
        f"- `prompt.json` — exact prompt sent\n"
        f"- `pytest.stdout.txt` / `pytest.stderr.txt` — test output\n"
        f"- `debug-tour.tour` — this file"
    )


def _debug_strategy_text(result: RunResult, category: str) -> str:
    """Debug next-steps based on failure category."""
    strategies = {
        "passed": (
            "✅ This cell succeeded.\n\n"
            "Compare its retrieval/tool patterns to failing cells to understand what worked."
        ),
        "empty_output": (
            "❌ Model produced no code.\n\n"
            "1. Check `model_request_latency_ms` — timeout?\n"
            "2. Inspect `raw_model_output` in `full_dump.json`\n"
            "3. Check prompt size\n"
            "4. For Claude Code: check subprocess errors"
        ),
        "syntax_error": (
            "❌ Generated code has invalid syntax.\n\n"
            "1. Read `generated_code.txt` — fragment without `def`?\n"
            "2. Check `codex.py` splice logic\n"
            "3. Verify `line_start`/`line_end` in task YAML\n"
            "4. Run: `python -m py_compile generated_code.txt`"
        ),
        "pytest_failure": (
            "❌ Tests failed.\n\n"
            "1. Read `pytest.stdout.txt` — which assertion failed?\n"
            "2. Read `generated_code.txt` — is the required `orgops.*` call present?\n"
            "3. Check task oracle constraints\n"
            "4. Look at `constraint_results` in scoring"
        ),
        "low_judge_score": (
            "⚠️ Passed tests but judge scored low.\n\n"
            "1. Read `constraint_results` — which constraint failed?\n"
            "2. Most common: correct logic but missing `orgops.*` API call\n"
            "3. Re-run judge: `python scripts/rescore_scoring.py --force`"
        ),
        "no_snippets_retrieved": (
            "❌ Retrieval enabled but no snippets fetched.\n\n"
            "1. Is VoltSnip running? `curl http://localhost:8000/health`\n"
            "2. Are snippets seeded? `python scripts/seed_snippets.py`\n"
            "3. Check `tool_traces` — did model try semantic_search?\n"
            "4. Check VoltSnip logs for errors"
        ),
        "timeout": (
            "⏱️ Run timed out.\n\n"
            "1. Check `retrieval_latency_ms` vs `model_request_latency_ms`\n"
            "2. Increase: `--llm-timeout 600` or `--pytest-timeout 600`"
        ),
    }
    return strategies.get(
        category,
        (
            f"❓ Failure: `{category}`\n\n"
            "1. Check `status` and `error` in `full_dump.json`\n"
            "2. Read `pytest.stdout.txt` and `pytest.stderr.txt`\n"
            "3. Read `prompt.json` to see model input\n"
            "4. Read `generated_code.txt` to see model output"
        ),
    )


def should_generate_tour(run_result: RunResult) -> bool:
    """Generate tours for failures and anomalies; skip clean passes."""
    if run_result.status != "ok":
        return True
    if run_result.score and run_result.score.overall_score < 0.5:
        return True
    if run_result.variant_tools_enabled and run_result.summary_metrics.tool_call_count == 0:
        return True
    if run_result.summary_metrics.snippet_count == 0 and run_result.variant_memory_enabled:
        return True
    return False
