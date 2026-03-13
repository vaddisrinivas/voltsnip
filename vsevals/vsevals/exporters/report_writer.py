"""Logic for writing evaluation reports and summaries."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .csv_mapper import safe_float, truthy

LOGGER = logging.getLogger(__name__)

def write_summary(matrix_dir: Path, results: list[dict], suite_path: str, models: str, variants: str, tasks: str, judge_model: str) -> None:
    ok = [r for r in results if r.get("status") == "ok"]
    avg_score = round(sum(safe_float(r.get("overall_score", 0)) for r in ok) / len(ok), 4) if ok else None
    pytest_ok = [r for r in results if truthy(r.get("pytest_ran")) and truthy(r.get("pytest_passed"))]

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "suite": suite_path,
        "models": models,
        "variants": variants or "all",
        "tasks": tasks or "all",
        "judge_model": judge_model,
        "total_cells": len(results),
        "ok_cells": len(ok),
        "passed_cells": sum(1 for r in results if truthy(r.get("full_pass", ""))),
        "pytest_passed_cells": len(pytest_ok),
        "avg_score": avg_score,
        "matrix_dir": str(matrix_dir),
        "csv_path": str(matrix_dir / "matrix_results.csv"),
        "report_path": str(matrix_dir / "matrix_report.md"),
    }
    (matrix_dir / "matrix_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_matrix_report(matrix_dir, results, summary)
    LOGGER.debug("summary written to %s/matrix_summary.json", matrix_dir)

def _escape_cell(value: str) -> str:
    """Escape pipe characters in markdown table cell values."""
    return str(value).replace("|", "\\|")


def _write_matrix_report(matrix_dir: Path, results: list[dict], summary: dict) -> None:
    """Write a markdown table report identical in structure to the old harness."""
    ok = [r for r in results if r.get("status") == "ok"]
    avg_score = summary.get("avg_score")

    lines: list[str] = [
        "# Matrix Evaluation Report",
        "",
        f"- Suite: `{summary.get('suite')}`",
        f"- Total runs: **{summary.get('total_cells')}**",
        f"- Successful runs: **{len(ok)}**",
        f"- Failed runs: **{summary.get('total_cells', 0) - len(ok)}**",
        f"- Avg oracle score: **{avg_score:.4f}**" if avg_score is not None else "- Avg score: n/a",
        "",
        "## Per-Run Table",
        "",
        "| task | variant | model | status | score | memory_signal | req_coverage | snippets | tools | latency_ms | prompt_tokens | completion_tokens | pytest |",
        "|---|---|---|---|---:|---|---:|---:|---:|---:|---:|---:|---|",
    ]

    sorted_results = sorted(results, key=lambda x: (x.get("task_id", ""), x.get("variant_id", ""), x.get("model_name", "")))
    for r in sorted_results:
        score = r.get("overall_score", "")
        score_str = f"{safe_float(score):.4f}" if score not in ("", None) else "-"
        pytest_str = "ok" if truthy(r.get("pytest_passed")) else ("fail" if truthy(r.get("pytest_ran")) else "-")
        coverage = r.get("required_snippet_coverage", "")
        cov_str = f"{safe_float(coverage):.2f}" if coverage not in ("", None) else "-"
        lines.append(
            f"| {_escape_cell(r.get('task_id', ''))} "
            f"| {_escape_cell(r.get('variant_id', ''))} "
            f"| `{_escape_cell(r.get('model_name', ''))}` "
            f"| {_escape_cell(r.get('status', ''))} "
            f"| {_escape_cell(score_str)} "
            f"| {_escape_cell(r.get('memory_signal', '-'))} "
            f"| {_escape_cell(cov_str)} "
            f"| {_escape_cell(str(r.get('snippet_count', 0)))} "
            f"| {_escape_cell(str(r.get('tool_call_count', 0)))} "
            f"| {_escape_cell(str(r.get('latency_ms', '-')))} "
            f"| {_escape_cell(str(r.get('prompt_tokens', '-')))} "
            f"| {_escape_cell(str(r.get('completion_tokens', '-')))} "
            f"| {_escape_cell(pytest_str)} |"
        )

    (matrix_dir / "matrix_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    LOGGER.debug("matrix report written to %s/matrix_report.md", matrix_dir)
