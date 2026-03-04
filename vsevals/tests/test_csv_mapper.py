"""Tests for vsevals.exporters.csv_mapper — row extraction, pytest parsing, helpers."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from vsevals.models import (
    GeneratedPayload,
    MessageTrace,
    RetrievedSnippet,
    RunError,
    PytestResult,
    ScoreDimension,
    ScoreResult,
    ToolTrace,
)
from vsevals.exporters.csv_mapper import (
    CANONICAL_COLUMNS,
    _build_artifacts,
    _build_identity,
    _build_output_signals,
    _build_pytest,
    _build_reliability,
    _build_score,
    _build_snippets,
    _build_timing,
    _build_tokens,
    _build_tools,
    _code_size_metrics,
    _compute_memory_signal,
    _compute_process_passed,
    _load_completed_from_csv,
    _load_completed_from_jsonl,
    _parse_pytest_counts,
    _reliability_counts,
    _snippet_code_utilization,
    _voltsnip_constraint_split,
    append_completed_entry,
    append_csv_row,
    classify_exc,
    error_row,
    load_completed,
    load_run_result,
    result_to_row,
    row_from_dump,
    safe_float,
    truthy,
)


# ---------------------------------------------------------------------------
# truthy
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("val,expected", [
    (True, True),
    (False, False),
    ("true", True),
    ("True", True),
    ("1", True),
    ("yes", True),
    ("false", False),
    ("0", False),
    ("", False),
    (1, True),
    (0, False),
    (None, False),
])
def test_truthy(val, expected):
    assert truthy(val) == expected


# ---------------------------------------------------------------------------
# safe_float
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("val,default,expected", [
    (1.5, 0.0, 1.5),
    ("3.14", 0.0, 3.14),
    (None, 0.0, 0.0),
    ("bad", 0.0, 0.0),
    (None, -1.0, -1.0),
    (0, 0.0, 0.0),
])
def test_safe_float(val, default, expected):
    assert safe_float(val, default) == expected


# ---------------------------------------------------------------------------
# classify_exc
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("msg,expected_class", [
    ("api key invalid", "AUTH_ERROR"),
    ("401 unauthorized", "AUTH_ERROR"),
    ("rate limit exceeded", "RATE_LIMIT_ERROR"),
    ("429 too many requests", "RATE_LIMIT_ERROR"),
    ("request timeout hit", "TIMEOUT"),
    ("connection refused", "NETWORK_ERROR"),
    ("unknown task BUG99", "CONFIG_ERROR"),
    ("unknown variant P9", "CONFIG_ERROR"),
    ("some random error", "UNKNOWN_ERROR"),
])
def test_classify_exc(msg, expected_class):
    assert classify_exc(RuntimeError(msg)) == expected_class


# ---------------------------------------------------------------------------
# error_row
# ---------------------------------------------------------------------------


def test_error_row():
    row = error_row("BUG01", "P0", "mock:default", RuntimeError("rate limit hit"))
    assert row["task_id"] == "BUG01"
    assert row["status"] == "error"
    assert row["error_class"] == "RATE_LIMIT_ERROR"
    assert row["rate_limit_count"] == 1


# ---------------------------------------------------------------------------
# _parse_pytest_counts
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("stdout,expected_passed,expected_failed", [
    ("===== 3 passed in 1.5s =====", 3, None),
    ("===== 2 passed, 1 failed in 2.0s =====", 2, 1),
    ("===== 5 passed, 2 failed, 1 skipped =====", 5, 2),
    ("", None, None),
    ("no summary here", None, None),
])
def test_parse_pytest_counts(stdout, expected_passed, expected_failed):
    counts = _parse_pytest_counts(stdout, "")
    assert counts["passed"] == expected_passed
    assert counts["failed"] == expected_failed


def test_parse_pytest_counts_collected_fallback():
    counts = _parse_pytest_counts("collected 10 items\n\nsome output", "")
    assert counts["total"] == 10


def test_parse_pytest_counts_with_xfailed():
    counts = _parse_pytest_counts("===== 3 passed, 1 xfailed in 1s =====", "")
    assert counts["passed"] == 3
    assert counts["xfailed"] == 1


# ---------------------------------------------------------------------------
# _code_size_metrics
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("code,expected_lines,expected_nonempty,expected_comment", [
    ("def f():\n    return 1\n", 2, 2, 0),
    ("# comment\ndef f():\n    pass\n", 3, 3, 1),
    ("", 0, 0, 0),
    ("   \n  \n", 0, 0, 0),
])
def test_code_size_metrics(code, expected_lines, expected_nonempty, expected_comment):
    result = _code_size_metrics(code)
    assert result["generated_code_lines"] == expected_lines
    assert result["generated_code_nonempty_lines"] == expected_nonempty
    assert result["generated_code_comment_lines"] == expected_comment


# ---------------------------------------------------------------------------
# _compute_memory_signal
# ---------------------------------------------------------------------------


def test_compute_memory_signal_no_memory(run_result):
    run_result.variant_memory_enabled = False
    run_result.variant_tools_enabled = False
    assert _compute_memory_signal(run_result) == "NO_MEMORY_EXPECTED"


def test_compute_memory_signal_no_required_keys(run_result):
    run_result.variant_memory_enabled = True
    run_result.required_snippet_keys = []
    assert _compute_memory_signal(run_result) == "NO_MEMORY_EXPECTED"


def test_compute_memory_signal_retrieval_ok(run_result):
    run_result.variant_memory_enabled = True
    run_result.required_snippet_keys = ["key1"]
    run_result.retrieved_snippets = [
        RetrievedSnippet(id="s1", canonical_key="key1", code="x"),
    ]
    assert _compute_memory_signal(run_result) == "RETRIEVAL_OK"


def test_compute_memory_signal_partial(run_result):
    run_result.variant_memory_enabled = True
    run_result.required_snippet_keys = ["key1", "key2"]
    run_result.retrieved_snippets = [
        RetrievedSnippet(id="s1", canonical_key="key1", code="x"),
    ]
    assert _compute_memory_signal(run_result) == "RETRIEVAL_PARTIAL"


def test_compute_memory_signal_missed(run_result):
    run_result.variant_memory_enabled = True
    run_result.required_snippet_keys = ["key1"]
    run_result.retrieved_snippets = []
    run_result.summary_metrics.tool_call_count = 0
    run_result.summary_metrics.snippet_count = 0
    assert _compute_memory_signal(run_result) == "RETRIEVAL_MISSED"


# ---------------------------------------------------------------------------
# _snippet_code_utilization
# ---------------------------------------------------------------------------


def test_snippet_code_utilization_match():
    snippets = [
        RetrievedSnippet(id="s1", canonical_key="k1", code="def record_metric(name, value): pass"),
    ]
    code = "record_metric('query.deadline', 100)"
    result = _snippet_code_utilization(snippets, code)
    assert result["snippet_utilized_count"] == 1


def test_snippet_code_utilization_no_match():
    snippets = [
        RetrievedSnippet(id="s1", canonical_key="k1", code="def unique_function_name(): pass"),
    ]
    code = "print('hello')"
    result = _snippet_code_utilization(snippets, code)
    assert result["snippet_utilized_count"] == 0


def test_snippet_code_utilization_empty():
    assert _snippet_code_utilization([], "code")["snippet_utilized_count"] == 0
    assert _snippet_code_utilization([RetrievedSnippet(id="s1", code="x")], "")["snippet_utilized_count"] == 0


# ---------------------------------------------------------------------------
# _voltsnip_constraint_split
# ---------------------------------------------------------------------------


def test_voltsnip_constraint_split():
    results = [
        {"id": "c1", "passed": True, "voltsnip_key": "k1"},
        {"id": "c2", "passed": False, "voltsnip_key": "k2"},
        {"id": "c3", "passed": True, "voltsnip_key": None},
    ]
    split = _voltsnip_constraint_split(results)
    assert split["voltsnip_constraints_total"] == 2
    assert split["voltsnip_constraints_passed"] == 1
    assert split["generic_constraints_total"] == 1
    assert split["generic_constraints_passed"] == 1


# ---------------------------------------------------------------------------
# _compute_process_passed
# ---------------------------------------------------------------------------


def test_compute_process_passed_no_score(run_result):
    run_result.score = None
    passed, reason = _compute_process_passed(run_result)
    assert passed is False
    assert reason == "outcome_failed"


def test_compute_process_passed_ok(run_result):
    run_result.score = ScoreResult(
        overall_score=1.0,
        passed=True,
        hidden_requirements=ScoreDimension(matched=1, total=1, score=1.0),
        success_indicators=ScoreDimension(matched=0, total=0, score=1.0),
        failure_modes=ScoreDimension(matched=0, total=0, score=1.0),
    )
    run_result.variant_memory_enabled = False
    run_result.variant_tools_enabled = False
    passed, reason = _compute_process_passed(run_result)
    assert passed is True


def test_compute_process_passed_tools_no_calls(run_result):
    run_result.score = ScoreResult(
        overall_score=1.0,
        passed=True,
        hidden_requirements=ScoreDimension(matched=1, total=1, score=1.0),
        success_indicators=ScoreDimension(matched=0, total=0, score=1.0),
        failure_modes=ScoreDimension(matched=0, total=0, score=1.0),
    )
    run_result.variant_tools_enabled = True
    run_result.summary_metrics.tool_call_count = 0
    passed, reason = _compute_process_passed(run_result)
    assert passed is False
    assert "no_tool_calls" in reason


# ---------------------------------------------------------------------------
# result_to_row
# ---------------------------------------------------------------------------


def test_result_to_row_basic(run_result):
    row = result_to_row(run_result)
    assert row["run_id"] == "test-run-001"
    assert row["task_id"] == "BUG01"
    assert row["model_name"] == "mock:default"
    assert row["status"] == "ok"
    assert "latency_ms" in row


def test_result_to_row_with_score(run_result):
    run_result.score = ScoreResult(
        overall_score=0.85,
        passed=True,
        hidden_requirements=ScoreDimension(matched=1, total=1, score=1.0),
        success_indicators=ScoreDimension(matched=0, total=0, score=1.0),
        failure_modes=ScoreDimension(matched=0, total=0, score=1.0),
        constraint_scoring_used=True,
        constraint_checks_passed=2,
        constraint_checks_total=3,
        constraint_results=[
            {"id": "c1", "passed": True, "llm_verdict": True, "expected": True, "voltsnip_key": "k1"},
        ],
    )
    row = result_to_row(run_result)
    assert row["overall_score"] == 0.85
    assert row["constraint_scoring_used"] is True


def test_result_to_row_with_error(run_result):
    run_result.error = RunError(type="RuntimeError", message="something broke", error_class="UNKNOWN_ERROR")
    row = result_to_row(run_result)
    assert row["error_type"] == "RuntimeError"
    assert row["error_class"] == "UNKNOWN_ERROR"


def test_result_to_row_with_pytest(run_result):
    run_result.pytest_result = PytestResult(
        ran=True,
        passed=True,
        returncode=0,
        stdout="===== 5 passed in 1.2s =====",
    )
    row = result_to_row(run_result)
    assert row["pytest_ran"] is True
    assert row["pytest_passed"] is True
    assert row["pytest_passed_count"] == 5


def test_result_to_row_all_canonical_columns_present(run_result):
    """Verify that result_to_row produces keys matching CANONICAL_COLUMNS."""
    row = result_to_row(run_result)
    # Not all columns are always present (score, pytest, error are conditional)
    # But identity/timing/token/tool columns should always be present
    for col in ["run_id", "task_id", "variant_id", "model_name", "status", "latency_ms"]:
        assert col in row


# ---------------------------------------------------------------------------
# append_csv_row
# ---------------------------------------------------------------------------


def test_append_csv_row_creates_header_on_empty_file(tmp_path):
    csv_path = tmp_path / "matrix.csv"
    csv_path.touch()  # empty file
    row = {"run_id": "r1", "task_id": "BUG01", "variant_id": "P0", "model_name": "mock:m"}
    append_csv_row(csv_path, row)
    content = csv_path.read_text()
    lines = content.strip().splitlines()
    assert len(lines) == 2  # header + 1 data row
    assert lines[0].startswith("run_id,")
    assert "r1" in lines[1]


def test_append_csv_row_no_header_on_nonempty_file(tmp_path):
    csv_path = tmp_path / "matrix.csv"
    # Write first row (creates header)
    csv_path.touch()
    row1 = {"run_id": "r1", "task_id": "BUG01"}
    append_csv_row(csv_path, row1)
    # Write second row (should NOT write header again)
    row2 = {"run_id": "r2", "task_id": "BUG02"}
    append_csv_row(csv_path, row2)
    lines = csv_path.read_text().strip().splitlines()
    assert len(lines) == 3  # 1 header + 2 data rows
    # Only one header line
    header_count = sum(1 for ln in lines if ln.startswith("run_id,"))
    assert header_count == 1


def test_append_csv_row_uses_canonical_columns(tmp_path):
    csv_path = tmp_path / "matrix.csv"
    csv_path.touch()
    row = {"run_id": "r1", "extra_col": "ignored"}
    append_csv_row(csv_path, row)
    header = csv_path.read_text().strip().splitlines()[0]
    assert "extra_col" not in header
    assert header == ",".join(CANONICAL_COLUMNS)


def test_append_csv_row_without_fcntl(tmp_path):
    csv_path = tmp_path / "matrix.csv"
    csv_path.touch()
    row = {"run_id": "r1"}
    with patch("vsevals.exporters.csv_mapper._HAS_FCNTL", False):
        append_csv_row(csv_path, row)
    lines = csv_path.read_text().strip().splitlines()
    assert len(lines) == 2


# ---------------------------------------------------------------------------
# append_completed_entry
# ---------------------------------------------------------------------------


def test_append_completed_entry_writes_jsonl(tmp_path):
    jsonl_path = tmp_path / "completed.jsonl"
    entry = {"task_id": "BUG01", "variant_id": "P0", "model_name": "mock:m", "status": "ok"}
    append_completed_entry(jsonl_path, entry)
    lines = jsonl_path.read_text().strip().splitlines()
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["task_id"] == "BUG01"


def test_append_completed_entry_appends_multiple(tmp_path):
    jsonl_path = tmp_path / "completed.jsonl"
    for i in range(3):
        append_completed_entry(jsonl_path, {"task_id": f"BUG{i:02d}", "variant_id": "P0", "model_name": "m", "status": "ok"})
    lines = jsonl_path.read_text().strip().splitlines()
    assert len(lines) == 3


def test_append_completed_entry_without_fcntl(tmp_path):
    jsonl_path = tmp_path / "completed.jsonl"
    entry = {"task_id": "BUG01", "status": "ok"}
    with patch("vsevals.exporters.csv_mapper._HAS_FCNTL", False):
        append_completed_entry(jsonl_path, entry)
    assert json.loads(jsonl_path.read_text().strip())["task_id"] == "BUG01"


# ---------------------------------------------------------------------------
# load_completed
# ---------------------------------------------------------------------------


def test_load_completed_prefers_jsonl(tmp_path):
    jsonl_path = tmp_path / "completed.jsonl"
    csv_path = tmp_path / "matrix_results.csv"
    # Write JSONL
    jsonl_path.write_text(json.dumps({"task_id": "BUG01", "variant_id": "P0", "model_name": "m", "status": "ok"}) + "\n")
    # Write CSV with different data
    csv_path.write_text("task_id,variant_id,model_name,status\nBUG02,P0,m,ok\n")
    result = load_completed(tmp_path)
    assert "BUG01/P0/m" in result
    assert "BUG02/P0/m" not in result


def test_load_completed_falls_back_to_csv(tmp_path):
    csv_path = tmp_path / "matrix_results.csv"
    csv_path.write_text("task_id,variant_id,model_name,status\nBUG02,P0,m,ok\n")
    result = load_completed(tmp_path)
    assert "BUG02/P0/m" in result


def test_load_completed_returns_empty_when_no_files(tmp_path):
    result = load_completed(tmp_path)
    assert result == {}


# ---------------------------------------------------------------------------
# _load_completed_from_jsonl
# ---------------------------------------------------------------------------


def test_load_completed_from_jsonl_basic(tmp_path):
    path = tmp_path / "completed.jsonl"
    entries = [
        {"task_id": "BUG01", "variant_id": "P0", "model_name": "m", "status": "ok"},
        {"task_id": "BUG02", "variant_id": "P1", "model_name": "m", "status": "ok"},
    ]
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
    result = _load_completed_from_jsonl(path)
    assert len(result) == 2
    assert "BUG01/P0/m" in result
    assert "BUG02/P1/m" in result


def test_load_completed_from_jsonl_skips_non_ok(tmp_path):
    path = tmp_path / "completed.jsonl"
    entries = [
        {"task_id": "BUG01", "variant_id": "P0", "model_name": "m", "status": "ok"},
        {"task_id": "BUG02", "variant_id": "P0", "model_name": "m", "status": "error"},
    ]
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
    result = _load_completed_from_jsonl(path)
    assert len(result) == 1
    assert "BUG01/P0/m" in result


def test_load_completed_from_jsonl_skips_bad_lines(tmp_path):
    path = tmp_path / "completed.jsonl"
    content = (
        json.dumps({"task_id": "BUG01", "variant_id": "P0", "model_name": "m", "status": "ok"}) + "\n"
        + "not valid json\n"
        + "\n"  # blank line
        + json.dumps({"task_id": "BUG02", "variant_id": "P1", "model_name": "m", "status": "ok"}) + "\n"
    )
    path.write_text(content)
    result = _load_completed_from_jsonl(path)
    assert len(result) == 2


def test_load_completed_from_jsonl_skips_incomplete_entries(tmp_path):
    path = tmp_path / "completed.jsonl"
    entries = [
        {"task_id": "BUG01", "variant_id": "P0", "model_name": "m", "status": "ok"},
        {"task_id": "", "variant_id": "P0", "model_name": "m", "status": "ok"},  # empty task_id
        {"task_id": "BUG03", "variant_id": "", "model_name": "m", "status": "ok"},  # empty variant_id
    ]
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
    result = _load_completed_from_jsonl(path)
    assert len(result) == 1


def test_load_completed_from_jsonl_handles_read_error(tmp_path):
    path = tmp_path / "completed.jsonl"
    # File doesn't exist yet but we create a directory with that name to cause an error
    path.mkdir()
    result = _load_completed_from_jsonl(path)
    assert result == {}


# ---------------------------------------------------------------------------
# _load_completed_from_csv
# ---------------------------------------------------------------------------


def test_load_completed_from_csv_basic(tmp_path):
    path = tmp_path / "matrix_results.csv"
    path.write_text("task_id,variant_id,model_name,status\nBUG01,P0,m,ok\nBUG02,P1,m,ok\n")
    result = _load_completed_from_csv(path)
    assert len(result) == 2
    assert "BUG01/P0/m" in result


def test_load_completed_from_csv_skips_non_ok(tmp_path):
    path = tmp_path / "matrix_results.csv"
    path.write_text("task_id,variant_id,model_name,status\nBUG01,P0,m,ok\nBUG02,P0,m,error\n")
    result = _load_completed_from_csv(path)
    assert len(result) == 1


def test_load_completed_from_csv_handles_error(tmp_path):
    path = tmp_path / "matrix_results.csv"
    path.mkdir()  # directory instead of file to cause error
    result = _load_completed_from_csv(path)
    assert result == {}


# ---------------------------------------------------------------------------
# load_run_result
# ---------------------------------------------------------------------------


def test_load_run_result(tmp_path, run_result):
    dump_path = tmp_path / "full_dump.json"
    dump_path.write_text(run_result.model_dump_json())
    loaded = load_run_result(dump_path)
    assert loaded.run_id == "test-run-001"
    assert loaded.task_id == "BUG01"
    assert loaded.model_name == "mock:default"


# ---------------------------------------------------------------------------
# row_from_dump
# ---------------------------------------------------------------------------


def test_row_from_dump(tmp_path, run_result):
    dump_path = tmp_path / "full_dump.json"
    dump_path.write_text(run_result.model_dump_json())
    row = row_from_dump(dump_path)
    assert row["run_id"] == "test-run-001"
    assert row["task_id"] == "BUG01"
    assert "latency_ms" in row


# ---------------------------------------------------------------------------
# _build_identity — line_range None paths
# ---------------------------------------------------------------------------


def test_build_identity_line_range_with_values(run_result):
    run_result.task_line_start = 10
    run_result.task_line_end = 20
    row = _build_identity(run_result, "mock", "default")
    assert row["task_line_range_size"] == 11


def test_build_identity_line_range_none_when_start_missing(run_result):
    run_result.task_line_start = None
    run_result.task_line_end = 20
    row = _build_identity(run_result, "mock", "default")
    assert row["task_line_range_size"] is None


def test_build_identity_line_range_none_when_end_missing(run_result):
    run_result.task_line_start = 10
    run_result.task_line_end = None
    row = _build_identity(run_result, "mock", "default")
    assert row["task_line_range_size"] is None


def test_build_identity_line_range_none_when_both_missing(run_result):
    run_result.task_line_start = None
    run_result.task_line_end = None
    row = _build_identity(run_result, "mock", "default")
    assert row["task_line_range_size"] is None


# ---------------------------------------------------------------------------
# _build_timing — model_request timestamps None paths
# ---------------------------------------------------------------------------


def test_build_timing_model_request_timestamps_present(run_result):
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    run_result.summary_metrics.model_request_started_at = now
    run_result.summary_metrics.model_request_finished_at = now
    row = _build_timing(run_result)
    assert row["model_request_started_at"] == now.isoformat()
    assert row["model_request_finished_at"] == now.isoformat()


def test_build_timing_model_request_timestamps_none(run_result):
    run_result.summary_metrics.model_request_started_at = None
    run_result.summary_metrics.model_request_finished_at = None
    row = _build_timing(run_result)
    assert row["model_request_started_at"] is None
    assert row["model_request_finished_at"] is None


# ---------------------------------------------------------------------------
# _build_tokens — fallback calc, tok_per_sec/chars_per_sec None paths
# ---------------------------------------------------------------------------


def test_build_tokens_total_fallback_when_none(run_result):
    run_result.token_usage.total_tokens = None
    run_result.token_usage.prompt_tokens = 100
    run_result.token_usage.completion_tokens = 50
    row = _build_tokens(run_result)
    assert row["total_tokens"] == 150


def test_build_tokens_total_fallback_all_none(run_result):
    run_result.token_usage.total_tokens = None
    run_result.token_usage.prompt_tokens = None
    run_result.token_usage.completion_tokens = None
    row = _build_tokens(run_result)
    assert row["total_tokens"] is None


def test_build_tokens_tok_per_sec_none_when_no_latency(run_result):
    run_result.summary_metrics.model_request_latency_ms = None
    run_result.token_usage.completion_tokens = 50
    row = _build_tokens(run_result)
    assert row["completion_tokens_per_second"] is None


def test_build_tokens_tok_per_sec_calculated(run_result):
    run_result.summary_metrics.model_request_latency_ms = 2000
    run_result.token_usage.completion_tokens = 100
    row = _build_tokens(run_result)
    assert row["completion_tokens_per_second"] == 50.0


def test_build_tokens_chars_per_sec_none_when_no_latency(run_result):
    run_result.summary_metrics.latency_ms = 0
    run_result.summary_metrics.output_chars = 100
    row = _build_tokens(run_result)
    assert row["output_chars_per_second"] is None


def test_build_tokens_chars_per_sec_none_when_no_output(run_result):
    run_result.summary_metrics.latency_ms = 500
    run_result.summary_metrics.output_chars = 0
    row = _build_tokens(run_result)
    assert row["output_chars_per_second"] is None


def test_build_tokens_chars_per_sec_calculated(run_result):
    run_result.summary_metrics.latency_ms = 2000
    run_result.summary_metrics.output_chars = 200
    row = _build_tokens(run_result)
    assert row["output_chars_per_second"] == 100.0


# ---------------------------------------------------------------------------
# _build_tools — durations, names, budget, roundtrips, errors
# ---------------------------------------------------------------------------


def test_build_tools_with_traces(run_result):
    run_result.tool_traces = [
        ToolTrace(roundtrip=1, tool_name="voltsnip_search", duration_ms=100),
        ToolTrace(roundtrip=2, tool_name="voltsnip_get", duration_ms=200, error="not found"),
        ToolTrace(roundtrip=2, tool_name="voltsnip_search", duration_ms=150),
    ]
    run_result.summary_metrics.tool_call_count = 3
    run_result.summary_metrics.tool_error_count = 1
    run_result.variant_max_tool_roundtrips = 8
    row = _build_tools(run_result)
    assert row["tool_names"] == "voltsnip_get;voltsnip_search"
    assert row["tool_duration_total_ms"] == 450
    assert row["tool_duration_max_ms"] == 200
    assert row["tool_duration_avg_ms"] == 150
    assert row["tool_roundtrips_used"] == 2
    assert row["tool_first_error"] == "not found"
    assert row["tool_success_count"] == 2
    assert row["tool_success_rate"] == round(2 / 3, 4)
    assert row["tool_budget_utilization"] == round(3 / 8, 4)


def test_build_tools_no_traces(run_result):
    run_result.tool_traces = []
    run_result.summary_metrics.tool_call_count = 0
    run_result.summary_metrics.tool_error_count = 0
    run_result.variant_max_tool_roundtrips = 0
    row = _build_tools(run_result)
    assert row["tool_names"] == ""
    assert row["tool_duration_total_ms"] is None
    assert row["tool_duration_max_ms"] is None
    assert row["tool_duration_avg_ms"] is None
    assert row["tool_roundtrips_used"] == 0
    assert row["tool_first_error"] is None
    assert row["tool_success_rate"] is None
    assert row["tool_budget_utilization"] is None


# ---------------------------------------------------------------------------
# _build_reliability / _reliability_counts
# ---------------------------------------------------------------------------


def test_reliability_counts_from_error_rate_limit(run_result):
    run_result.error = RunError(type="APIError", message="rate limit exceeded", error_class="RATE_LIMIT_ERROR")
    run_result.summary_metrics.voltsnip_rate_limit_count = 0
    run_result.summary_metrics.voltsnip_timeout_count = 0
    counts = _reliability_counts(run_result)
    assert counts["rate_limit_count"] == 1


def test_reliability_counts_from_error_timeout(run_result):
    run_result.error = RunError(type="TimeoutError", message="request timed out", error_class="TIMEOUT")
    run_result.summary_metrics.voltsnip_rate_limit_count = 0
    run_result.summary_metrics.voltsnip_timeout_count = 0
    counts = _reliability_counts(run_result)
    assert counts["timeout_count"] == 1


def test_reliability_counts_mcp_from_error_message(run_result):
    run_result.error = RunError(type="Error", message="MCP connection failed", error_class="NETWORK_ERROR")
    counts = _reliability_counts(run_result)
    assert counts["mcp_error_count"] >= 1


def test_reliability_counts_mcp_from_tool_traces(run_result):
    run_result.error = None
    run_result.tool_traces = [
        ToolTrace(roundtrip=1, tool_name="mcp__voltsnip__search", error="connection refused"),
        ToolTrace(roundtrip=2, tool_name="fetch_url", error="timeout"),
    ]
    counts = _reliability_counts(run_result)
    assert counts["mcp_error_count"] == 2  # voltsnip + fetch


def test_reliability_counts_pytest_timeout(run_result):
    run_result.error = None
    run_result.pytest_result = PytestResult(ran=True, error="timed out after 30s")
    run_result.summary_metrics.voltsnip_timeout_count = 0
    counts = _reliability_counts(run_result)
    assert counts["timeout_count"] == 1


def test_build_reliability_includes_summary_metrics(run_result):
    run_result.summary_metrics.voltsnip_retry_count = 3
    run_result.summary_metrics.voltsnip_rate_limit_count = 1
    run_result.summary_metrics.voltsnip_timeout_count = 2
    run_result.summary_metrics.voltsnip_error_count = 1
    row = _build_reliability(run_result)
    assert row["voltsnip_retry_count"] == 3
    assert row["voltsnip_rate_limit_count"] == 1
    assert row["voltsnip_timeout_count"] == 2
    assert row["voltsnip_error_count"] == 1


# ---------------------------------------------------------------------------
# _build_snippets
# ---------------------------------------------------------------------------


def test_build_snippets_with_retrieved(run_result):
    run_result.required_snippet_keys = ["key1", "key2"]
    run_result.retrieved_snippets = [
        RetrievedSnippet(id="s1", canonical_key="key1", title="API", language="python", tags=["api", "core"], code="def emit(): pass"),
    ]
    run_result.prompt.injected_snippet_keys = ["key1"]
    row = _build_snippets(run_result)
    assert row["required_snippet_count"] == 2
    assert row["required_snippet_keys"] == "key1;key2"
    assert row["required_snippet_hit_keys"] == "key1"
    assert row["required_snippet_missing_keys"] == "key2"
    assert row["required_snippet_retrieved_count"] == 1
    assert row["required_snippet_missing_count"] == 1
    assert row["required_snippet_coverage"] == 0.5
    assert "API" in row["snippet_retrieved_titles"]
    assert "python" in row["snippet_retrieved_languages"]
    assert "api" in row["snippet_retrieved_tags"]
    assert row["snippet_injected_count"] == 1


def test_build_snippets_no_required(run_result):
    run_result.required_snippet_keys = []
    run_result.retrieved_snippets = []
    run_result.prompt.injected_snippet_keys = []
    row = _build_snippets(run_result)
    assert row["required_snippet_count"] == 0
    assert row["required_snippet_coverage"] is None


# ---------------------------------------------------------------------------
# _build_output_signals
# ---------------------------------------------------------------------------


def test_build_output_signals_basic(run_result):
    run_result.raw_model_output = "some model output"
    run_result.parsed_output = GeneratedPayload(code="def fix(): return 42", comments="fixed it")
    run_result.messages = [
        MessageTrace(role="user", content="fix this"),
        MessageTrace(role="assistant", content="done fixing the code"),
    ]
    row = _build_output_signals(run_result)
    assert row["messages_count"] == 2
    assert row["assistant_messages_chars"] == len("done fixing the code")
    assert row["parsed_code_chars"] == len("def fix(): return 42")
    assert row["parsed_comments_chars"] == len("fixed it")
    assert row["raw_output_preview"] == "some model output"


def test_build_output_signals_empty_raw_output(run_result):
    run_result.raw_model_output = ""
    row = _build_output_signals(run_result)
    assert row["raw_output_preview"] == ""


def test_build_output_signals_truncates_raw_output(run_result):
    run_result.raw_model_output = "x" * 500
    row = _build_output_signals(run_result)
    assert len(row["raw_output_preview"]) == 400


# ---------------------------------------------------------------------------
# _build_artifacts — subprocess vs API paths
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("provider,is_subprocess", [
    ("claudecode", True),
    ("codex", True),
    ("anthropic", False),
    ("openai", False),
])
def test_build_artifacts_provider_paths(run_result, provider, is_subprocess):
    row = _build_artifacts(run_result, provider)
    rd = run_result.artifacts.run_dir
    if is_subprocess:
        assert row["subprocess_stdout_jsonl"] == str(Path(rd) / f"subprocess.stdout.{provider}.jsonl")
        assert row["subprocess_stderr_txt"] == str(Path(rd) / f"subprocess.stderr.{provider}.txt")
        assert row["llm_response_json"] is None
    else:
        assert row["subprocess_stdout_jsonl"] is None
        assert row["subprocess_stderr_txt"] is None
        assert row["llm_response_json"] == str(Path(rd) / f"llm_response.{provider}.json")
    assert row["prompt_json"] == str(Path(rd) / "prompt.json")
    assert row["run_dir"] == rd


# ---------------------------------------------------------------------------
# _build_score — all score fields, constraint JSON, voltsnip split
# ---------------------------------------------------------------------------


def test_build_score_full():
    s = ScoreResult(
        overall_score=0.75,
        passed=True,
        hidden_requirements=ScoreDimension(matched=2, total=3, score=0.67),
        success_indicators=ScoreDimension(matched=1, total=2, score=0.5),
        failure_modes=ScoreDimension(matched=0, total=1, score=1.0),
        evaluation_criteria=ScoreDimension(matched=3, total=3, score=1.0),
        evaluation_criteria_notes=["good", "clean"],
        constraint_scoring_used=True,
        constraint_checks_passed=3,
        constraint_checks_total=4,
        constraint_pass_threshold=0.7,
        constraint_results=[
            {"id": "c1", "passed": True, "llm_verdict": True, "expected": True, "voltsnip_key": "k1"},
            {"id": "c2", "passed": True, "llm_verdict": None, "expected": True, "voltsnip_key": None},
            {"id": "c3", "passed": True, "llm_verdict": True, "expected": False, "voltsnip_key": "k2"},
            {"id": "c4", "passed": False, "llm_verdict": False, "expected": True, "voltsnip_key": None},
        ],
    )
    row = _build_score(s)
    assert row["overall_score"] == 0.75
    assert row["constraint_scoring_used"] is True
    assert row["constraint_checks_passed"] == 3
    assert row["constraint_checks_total"] == 4
    assert row["constraint_failed_count"] == 1
    assert row["constraint_pass_rate"] == 0.75
    assert row["constraint_pass_threshold"] == 0.7
    assert "c1" in row["constraint_passed_ids"]
    assert "c4" in row["constraint_failed_ids"]
    assert row["constraint_llm_verdict_count"] == 3  # c1, c3 (True), c4 (False) have non-None llm_verdict
    assert row["evaluation_criteria_notes"] == "good;clean"
    # voltsnip split
    assert row["voltsnip_constraints_total"] == 2
    assert row["voltsnip_constraints_passed"] == 2
    assert row["generic_constraints_total"] == 2
    assert row["generic_constraints_passed"] == 1
    # constraint_results_json is valid JSON
    parsed = json.loads(row["constraint_results_json"])
    assert len(parsed) == 4
    # Hidden/success/failure/eval dims
    assert row["hidden_requirements_score"] == 0.67
    assert row["success_indicators_matched"] == 1
    assert row["failure_modes_total"] == 1
    assert row["evaluation_criteria_score"] == 1.0


def test_build_score_no_constraints():
    s = ScoreResult(
        overall_score=1.0,
        passed=True,
        hidden_requirements=ScoreDimension(matched=1, total=1, score=1.0),
        success_indicators=ScoreDimension(matched=0, total=0, score=1.0),
        failure_modes=ScoreDimension(matched=0, total=0, score=1.0),
        constraint_checks_passed=None,
        constraint_checks_total=None,
    )
    row = _build_score(s)
    assert row["constraint_failed_count"] is None
    assert row["constraint_pass_rate"] is None


# ---------------------------------------------------------------------------
# _build_pytest — full pytest result with counts and file paths
# ---------------------------------------------------------------------------


def test_build_pytest_full(run_result):
    run_result.pytest_result = PytestResult(
        ran=True,
        passed=True,
        returncode=0,
        duration_ms=1500,
        docker_image="python:3.11",
        stdout="===== 5 passed, 1 failed, 2 skipped in 3.0s =====",
        stderr="",
        error=None,
    )
    row = _build_pytest(run_result)
    assert row["pytest_ran"] is True
    assert row["pytest_passed"] is True
    assert row["pytest_returncode"] == 0
    assert row["pytest_duration_ms"] == 1500
    assert row["pytest_docker_image"] == "python:3.11"
    assert row["pytest_error"] == ""
    assert row["pytest_passed_count"] == 5
    assert row["pytest_failed_count"] == 1
    assert row["pytest_skipped_count"] == 2
    assert row["pytest_stdout_file"] == run_result.artifacts.run_dir + "/pytest.stdout.txt"
    assert row["pytest_stderr_file"] == run_result.artifacts.run_dir + "/pytest.stderr.txt"


def test_build_pytest_not_ran(run_result):
    run_result.pytest_result = PytestResult(ran=False)
    row = _build_pytest(run_result)
    assert row["pytest_ran"] is False
    assert row["pytest_stdout_file"] is None
    assert row["pytest_stderr_file"] is None


def test_build_pytest_with_error(run_result):
    long_error = "x" * 500
    run_result.pytest_result = PytestResult(ran=True, error=long_error)
    row = _build_pytest(run_result)
    assert len(row["pytest_error"]) == 300  # truncated


def test_build_pytest_returns_empty_when_no_result(run_result):
    run_result.pytest_result = None
    row = _build_pytest(run_result)
    assert row == {}


# ---------------------------------------------------------------------------
# _compute_process_passed — memory incomplete, all_tool_calls_failed
# ---------------------------------------------------------------------------


def test_compute_process_passed_retrieval_incomplete(run_result):
    run_result.score = ScoreResult(
        overall_score=1.0,
        passed=True,
        hidden_requirements=ScoreDimension(matched=1, total=1, score=1.0),
        success_indicators=ScoreDimension(matched=0, total=0, score=1.0),
        failure_modes=ScoreDimension(matched=0, total=0, score=1.0),
    )
    run_result.variant_memory_enabled = True
    run_result.variant_tools_enabled = False
    run_result.required_snippet_keys = ["key1", "key2"]
    run_result.retrieved_snippets = [
        RetrievedSnippet(id="s1", canonical_key="key1", code="x"),
    ]
    passed, reason = _compute_process_passed(run_result)
    assert passed is False
    assert "retrieval_incomplete" in reason


def test_compute_process_passed_all_tool_calls_failed(run_result):
    run_result.score = ScoreResult(
        overall_score=1.0,
        passed=True,
        hidden_requirements=ScoreDimension(matched=1, total=1, score=1.0),
        success_indicators=ScoreDimension(matched=0, total=0, score=1.0),
        failure_modes=ScoreDimension(matched=0, total=0, score=1.0),
    )
    run_result.variant_tools_enabled = True
    run_result.variant_memory_enabled = False
    run_result.summary_metrics.tool_call_count = 3
    run_result.summary_metrics.tool_error_count = 3
    passed, reason = _compute_process_passed(run_result)
    assert passed is False
    assert "all_tool_calls_failed" in reason


# ---------------------------------------------------------------------------
# _compute_memory_signal — RETRIEVAL_ATTEMPTED_NO_HITS path
# ---------------------------------------------------------------------------


def test_compute_memory_signal_attempted_no_hits(run_result):
    run_result.variant_memory_enabled = True
    run_result.required_snippet_keys = ["key1"]
    run_result.retrieved_snippets = []
    run_result.summary_metrics.tool_call_count = 3
    run_result.summary_metrics.snippet_count = 0
    assert _compute_memory_signal(run_result) == "RETRIEVAL_ATTEMPTED_NO_HITS"


def test_compute_memory_signal_attempted_no_hits_via_snippet_count(run_result):
    run_result.variant_memory_enabled = True
    run_result.required_snippet_keys = ["key1"]
    run_result.retrieved_snippets = []
    run_result.summary_metrics.tool_call_count = 0
    run_result.summary_metrics.snippet_count = 2
    assert _compute_memory_signal(run_result) == "RETRIEVAL_ATTEMPTED_NO_HITS"
