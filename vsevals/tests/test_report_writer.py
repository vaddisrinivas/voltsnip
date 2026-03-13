"""Tests for vsevals.exporters.report_writer — summary JSON and markdown report."""

from __future__ import annotations

import json

import pytest

from vsevals.exporters.report_writer import _write_matrix_report, write_summary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_result(
    task_id: str = "BUG01",
    variant_id: str = "P0",
    model_name: str = "mock:default",
    status: str = "ok",
    overall_score: float | str | None = 0.85,
    pytest_ran: bool | str = "",
    pytest_passed: bool | str = "",
    full_pass: bool | str = "",
    required_snippet_coverage: float | str | None = None,
    latency_ms: float | str | None = None,
    memory_signal: str = "-",
    snippet_count: int = 0,
    tool_call_count: int = 0,
    prompt_tokens: int | str = "-",
    completion_tokens: int | str = "-",
) -> dict:
    return {
        "task_id": task_id,
        "variant_id": variant_id,
        "model_name": model_name,
        "status": status,
        "overall_score": overall_score,
        "pytest_ran": pytest_ran,
        "pytest_passed": pytest_passed,
        "full_pass": full_pass,
        "required_snippet_coverage": required_snippet_coverage,
        "latency_ms": latency_ms,
        "memory_signal": memory_signal,
        "snippet_count": snippet_count,
        "tool_call_count": tool_call_count,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
    }


def _load_summary(matrix_dir):
    return json.loads((matrix_dir / "matrix_summary.json").read_text(encoding="utf-8"))


def _load_report(matrix_dir):
    return (matrix_dir / "matrix_report.md").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# write_summary
# ---------------------------------------------------------------------------


def test_write_summary_basic(tmp_path):
    """Verify JSON content has all required keys with correct values."""
    results = [_make_result()]
    write_summary(
        tmp_path, results,
        suite_path="suite.yaml",
        models="mock:default",
        variants="P0",
        tasks="BUG01",
        judge_model="mock:judge",
    )
    summary = _load_summary(tmp_path)
    assert summary["suite"] == "suite.yaml"
    assert summary["models"] == "mock:default"
    assert summary["variants"] == "P0"
    assert summary["tasks"] == "BUG01"
    assert summary["judge_model"] == "mock:judge"
    assert summary["total_cells"] == 1
    assert summary["ok_cells"] == 1
    assert "generated_at" in summary
    assert "avg_score" in summary
    assert "matrix_dir" in summary


def test_write_summary_no_ok_results(tmp_path):
    """When no results have status=ok, avg_score should be None."""
    results = [_make_result(status="error", overall_score="")]
    write_summary(
        tmp_path, results,
        suite_path="suite.yaml",
        models="mock:default",
        variants="P0",
        tasks="BUG01",
        judge_model="mock:judge",
    )
    summary = _load_summary(tmp_path)
    assert summary["avg_score"] is None
    assert summary["ok_cells"] == 0
    assert summary["total_cells"] == 1


def test_write_summary_with_scores(tmp_path):
    """avg_score should be correctly computed from ok results."""
    results = [
        _make_result(task_id="BUG01", overall_score=0.80),
        _make_result(task_id="BUG02", overall_score=0.60),
        _make_result(task_id="BUG03", status="error", overall_score=""),
    ]
    write_summary(
        tmp_path, results,
        suite_path="suite.yaml",
        models="mock:default",
        variants="P0",
        tasks="all",
        judge_model="mock:judge",
    )
    summary = _load_summary(tmp_path)
    # avg of 0.80 and 0.60 = 0.70, rounded to 4 decimal places
    assert summary["avg_score"] == 0.7
    assert summary["ok_cells"] == 2
    assert summary["total_cells"] == 3


@pytest.mark.parametrize(
    "scores,expected_avg",
    [
        ([1.0, 1.0, 1.0], 1.0),
        ([0.0, 0.0], 0.0),
        ([0.3333, 0.6667], 0.5),
    ],
    ids=["all-perfect", "all-zero", "fractional"],
)
def test_write_summary_with_scores_parametrized(tmp_path, scores, expected_avg):
    """Parametrized avg_score computation for various score distributions."""
    results = [
        _make_result(task_id=f"BUG{i:02d}", overall_score=s)
        for i, s in enumerate(scores)
    ]
    write_summary(
        tmp_path, results,
        suite_path="s.yaml",
        models="m",
        variants="v",
        tasks="t",
        judge_model="j",
    )
    summary = _load_summary(tmp_path)
    assert summary["avg_score"] == round(expected_avg, 4)


def test_write_summary_with_pytest(tmp_path):
    """pytest_passed_cells should count results where pytest_ran and pytest_passed are truthy."""
    results = [
        _make_result(task_id="BUG01", pytest_ran=True, pytest_passed=True),
        _make_result(task_id="BUG02", pytest_ran=True, pytest_passed=False),
        _make_result(task_id="BUG03", pytest_ran="", pytest_passed=""),
    ]
    write_summary(
        tmp_path, results,
        suite_path="suite.yaml",
        models="mock:default",
        variants="P0",
        tasks="all",
        judge_model="mock:judge",
    )
    summary = _load_summary(tmp_path)
    assert summary["pytest_passed_cells"] == 1


def test_write_summary_with_full_pass(tmp_path):
    """passed_cells should count results where full_pass is truthy."""
    results = [
        _make_result(task_id="BUG01", full_pass=True),
        _make_result(task_id="BUG02", full_pass="true"),
        _make_result(task_id="BUG03", full_pass=False),
        _make_result(task_id="BUG04", full_pass=""),
    ]
    write_summary(
        tmp_path, results,
        suite_path="suite.yaml",
        models="mock:default",
        variants="P0",
        tasks="all",
        judge_model="mock:judge",
    )
    summary = _load_summary(tmp_path)
    assert summary["passed_cells"] == 2


def test_write_summary_variants_default(tmp_path):
    """When variants is empty string, summary should default to 'all'."""
    results = [_make_result()]
    write_summary(
        tmp_path, results,
        suite_path="s.yaml",
        models="m",
        variants="",
        tasks="",
        judge_model="j",
    )
    summary = _load_summary(tmp_path)
    assert summary["variants"] == "all"
    assert summary["tasks"] == "all"


# ---------------------------------------------------------------------------
# _write_matrix_report
# ---------------------------------------------------------------------------


def test_write_matrix_report_basic(tmp_path):
    """Verify markdown report file is created with expected structure."""
    results = [_make_result()]
    summary = {
        "suite": "suite.yaml",
        "total_cells": 1,
        "avg_score": 0.85,
    }
    _write_matrix_report(tmp_path, results, summary)
    report = _load_report(tmp_path)
    assert "# Matrix Evaluation Report" in report
    assert "## Per-Run Table" in report
    assert "suite.yaml" in report
    assert "BUG01" in report
    assert "mock:default" in report
    assert "| task |" in report


def test_write_matrix_report_sorted(tmp_path):
    """Results should be sorted by task_id, variant_id, model_name."""
    results = [
        _make_result(task_id="BUG03", variant_id="P0", model_name="mock:b"),
        _make_result(task_id="BUG01", variant_id="P2", model_name="mock:a"),
        _make_result(task_id="BUG01", variant_id="P0", model_name="mock:a"),
        _make_result(task_id="BUG02", variant_id="P0", model_name="mock:a"),
    ]
    summary = {"suite": "s.yaml", "total_cells": 4, "avg_score": 0.85}
    _write_matrix_report(tmp_path, results, summary)
    report = _load_report(tmp_path)
    lines = [ln for ln in report.splitlines() if ln.startswith("| BUG")]
    # Extract task_ids from each row
    task_ids = [ln.split("|")[1].strip() for ln in lines]
    assert task_ids == ["BUG01", "BUG01", "BUG02", "BUG03"]
    # Check variant sort within BUG01
    variants_bug01 = [ln.split("|")[2].strip() for ln in lines[:2]]
    assert variants_bug01 == ["P0", "P2"]


def test_write_matrix_report_score_formatting(tmp_path):
    """Scores should be formatted to 4 decimal places."""
    results = [
        _make_result(task_id="BUG01", overall_score=0.123456789),
        _make_result(task_id="BUG02", overall_score=1.0),
        _make_result(task_id="BUG03", overall_score=""),
    ]
    summary = {"suite": "s.yaml", "total_cells": 3, "avg_score": 0.5}
    _write_matrix_report(tmp_path, results, summary)
    report = _load_report(tmp_path)
    # 0.123456789 should be formatted as 0.1235 (4 decimals)
    assert "0.1235" in report
    # 1.0 should be formatted as 1.0000
    assert "1.0000" in report
    # Empty score should show as dash
    lines_bug03 = [ln for ln in report.splitlines() if "BUG03" in ln]
    assert len(lines_bug03) == 1
    # The score column (5th pipe-delimited field) should contain "-"
    fields = lines_bug03[0].split("|")
    score_field = fields[5].strip()  # score is the 5th column (1-indexed in split)
    assert score_field == "-"


@pytest.mark.parametrize(
    "pytest_ran,pytest_passed,expected_str",
    [
        (True, True, "ok"),
        (True, False, "fail"),
        ("", "", "-"),
        (False, False, "-"),
    ],
    ids=["passed", "failed", "not-ran-empty", "not-ran-false"],
)
def test_write_matrix_report_pytest_status(
    tmp_path, pytest_ran, pytest_passed, expected_str
):
    """Pytest column should show ok/fail/- based on pytest_ran and pytest_passed."""
    results = [_make_result(pytest_ran=pytest_ran, pytest_passed=pytest_passed)]
    summary = {"suite": "s.yaml", "total_cells": 1, "avg_score": 0.85}
    _write_matrix_report(tmp_path, results, summary)
    report = _load_report(tmp_path)
    # Find the data row (skip header rows)
    data_lines = [ln for ln in report.splitlines() if ln.startswith("| BUG")]
    assert len(data_lines) == 1
    # Pytest is the last column before the trailing pipe
    fields = data_lines[0].rstrip("|").split("|")
    pytest_field = fields[-1].strip()
    assert pytest_field == expected_str


def test_write_matrix_report_avg_score_none(tmp_path):
    """When avg_score is None, report should show 'n/a' for avg score."""
    results = [_make_result(status="error", overall_score="")]
    summary = {"suite": "s.yaml", "total_cells": 1, "avg_score": None}
    _write_matrix_report(tmp_path, results, summary)
    report = _load_report(tmp_path)
    assert "n/a" in report


def test_write_matrix_report_coverage_formatting(tmp_path):
    """Coverage should be formatted to 2 decimal places or show '-' when empty."""
    results = [
        _make_result(task_id="BUG01", required_snippet_coverage=0.8571),
        _make_result(task_id="BUG02", required_snippet_coverage=""),
        _make_result(task_id="BUG03", required_snippet_coverage=None),
    ]
    summary = {"suite": "s.yaml", "total_cells": 3, "avg_score": 0.85}
    _write_matrix_report(tmp_path, results, summary)
    report = _load_report(tmp_path)
    assert "0.86" in report  # 0.8571 rounded to 2 decimals
