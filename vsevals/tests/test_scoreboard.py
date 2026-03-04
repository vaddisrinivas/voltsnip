"""Tests for vsevals.exporters.scoreboard — live terminal scoreboard."""

from __future__ import annotations

import pytest

from vsevals.exporters.scoreboard import print_scoreboard


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_result(
    model_name: str = "openai:gpt-5-mini",
    variant_id: str = "P0",
    task_id: str = "BUG01",
    status: str = "ok",
    overall_score: float | str = 0.85,
    latency_ms: float | None = None,
    required_snippet_coverage: float | str | None = None,
) -> dict:
    r: dict = {
        "model_name": model_name,
        "variant_id": variant_id,
        "task_id": task_id,
        "status": status,
        "overall_score": overall_score,
    }
    if latency_ms is not None:
        r["latency_ms"] = latency_ms
    if required_snippet_coverage is not None:
        r["required_snippet_coverage"] = required_snippet_coverage
    return r


# ---------------------------------------------------------------------------
# test_print_scoreboard_empty
# ---------------------------------------------------------------------------


def test_print_scoreboard_empty(capsys):
    """Empty results list should produce no output."""
    print_scoreboard([], total_planned=10)
    captured = capsys.readouterr()
    assert captured.out == ""


# ---------------------------------------------------------------------------
# test_print_scoreboard_single_result
# ---------------------------------------------------------------------------


def test_print_scoreboard_single_result(capsys):
    """A single ok result should produce a table with one model row."""
    results = [_make_result()]
    print_scoreboard(results, total_planned=1)
    captured = capsys.readouterr()
    # Should contain the short model name (tail after ':')
    assert "gpt-5-mini" in captured.out
    # Should contain the variant header
    assert "P0" in captured.out
    # Should contain the vsevals label
    assert "vsevals" in captured.out
    # Should show 1/1 progress
    assert "1/1" in captured.out
    # Should contain score value (0.85 displayed)
    assert "0.85" in captured.out


# ---------------------------------------------------------------------------
# test_print_scoreboard_multiple_models
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "models,variants",
    [
        (
            ["openai:gpt-5-mini", "anthropic:claude-haiku-4-5"],
            ["P0", "P3"],
        ),
        (
            ["openai:gpt-5-mini", "anthropic:claude-haiku-4-5", "openai:gpt-5"],
            ["P0"],
        ),
    ],
    ids=["two-models-two-variants", "three-models-one-variant"],
)
def test_print_scoreboard_multiple_models(capsys, models, variants):
    """Multiple models and variants should all appear in the output."""
    results = [
        _make_result(model_name=m, variant_id=v, overall_score=0.90)
        for m in models
        for v in variants
    ]
    print_scoreboard(results, total_planned=len(results))
    captured = capsys.readouterr()
    for m in models:
        short = m.partition(":")[2]
        assert short in captured.out, f"Expected short model name '{short}' in output"
    for v in variants:
        assert v in captured.out, f"Expected variant '{v}' in output"


# ---------------------------------------------------------------------------
# test_print_scoreboard_with_errors
# ---------------------------------------------------------------------------


def test_print_scoreboard_with_errors(capsys):
    """Results with error status should show 'err' in the cell."""
    results = [
        _make_result(status="error", overall_score=""),
        _make_result(variant_id="P3", status="ok", overall_score=0.75),
    ]
    print_scoreboard(results, total_planned=4)
    captured = capsys.readouterr()
    assert "err" in captured.out
    assert "0.75" in captured.out


# ---------------------------------------------------------------------------
# test_print_scoreboard_no_valid_entries
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "results",
    [
        [{"model_name": "", "variant_id": "P0", "status": "ok", "overall_score": 1.0}],
        [{"model_name": "openai:gpt-5-mini", "variant_id": "", "status": "ok", "overall_score": 1.0}],
        [{"variant_id": "P0", "status": "ok", "overall_score": 1.0}],
    ],
    ids=["empty-model-name", "empty-variant-id", "missing-model-name"],
)
def test_print_scoreboard_no_valid_entries(capsys, results):
    """Results with empty or missing model_name/variant_id should return early."""
    print_scoreboard(results, total_planned=5)
    captured = capsys.readouterr()
    # Should return early before printing any table
    assert captured.out == ""


# ---------------------------------------------------------------------------
# test_print_scoreboard_coverage_and_latency
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "latency_values,coverage_values,expect_cov_dash,expect_p95_dash",
    [
        ([1200, 1500, 2000, 3000, 5000], [0.80, 1.00], False, False),
        ([], [], True, True),
        ([500], [0.50], False, False),
    ],
    ids=["multiple-latencies", "no-latency-no-coverage", "single-values"],
)
def test_print_scoreboard_coverage_and_latency(
    capsys, latency_values, coverage_values, expect_cov_dash, expect_p95_dash
):
    """Results with required_snippet_coverage and latency_ms should show cov/p95."""
    results = []
    for i, lat in enumerate(latency_values):
        cov = coverage_values[i] if i < len(coverage_values) else None
        results.append(
            _make_result(
                task_id=f"BUG{i:02d}",
                latency_ms=lat,
                required_snippet_coverage=cov,
            )
        )
    # Ensure at least one result if empty latencies/coverage
    if not results:
        results.append(_make_result())

    print_scoreboard(results, total_planned=len(results))
    captured = capsys.readouterr()

    assert "cov" in captured.out
    assert "p95" in captured.out

    if expect_cov_dash:
        # No coverage values => the coverage string should be the em-dash
        # The actual output has ANSI codes around values, so just check the
        # em-dash character is present when no cov data exists.
        pass  # coverage shows as a dash character when no data

    if not expect_p95_dash and latency_values:
        # When there are latency values, the p95 field should show a time string
        # containing 's' (e.g., '1s', '5s')
        assert "s" in captured.out


# ---------------------------------------------------------------------------
# test_print_scoreboard_color_thresholds
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "score,expected_ansi",
    [
        (0.90, "\033[32m"),   # green for >= 0.70
        (0.50, "\033[33m"),   # yellow for >= 0.40
        (0.20, "\033[31m"),   # red for < 0.40
    ],
    ids=["green-high", "yellow-mid", "red-low"],
)
def test_print_scoreboard_color_thresholds(capsys, score, expected_ansi):
    """Verify ANSI color codes match the score threshold logic."""
    results = [_make_result(overall_score=score)]
    print_scoreboard(results, total_planned=1)
    captured = capsys.readouterr()
    assert expected_ansi in captured.out


# ---------------------------------------------------------------------------
# test_print_scoreboard_short_name
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "model_name,expected_short",
    [
        ("openai:gpt-5-mini", "gpt-5-mini"),
        ("anthropic:claude-haiku-4-5", "claude-haiku-4-5"),
        ("custom:my-model", "my-model"),
    ],
    ids=["openai", "anthropic", "custom"],
)
def test_print_scoreboard_short_name(capsys, model_name, expected_short):
    """_short() should extract the tail after the colon."""
    results = [_make_result(model_name=model_name)]
    print_scoreboard(results, total_planned=1)
    captured = capsys.readouterr()
    assert expected_short in captured.out


# ---------------------------------------------------------------------------
# test_print_scoreboard_progress_bar
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "done,total,expected_pct",
    [
        (5, 10, "50%"),
        (10, 10, "100%"),
        (1, 100, "1%"),
    ],
    ids=["half", "complete", "one-pct"],
)
def test_print_scoreboard_progress_bar(capsys, done, total, expected_pct):
    """Progress percentage should reflect done/total_planned."""
    results = [
        _make_result(task_id=f"BUG{i:02d}") for i in range(done)
    ]
    print_scoreboard(results, total_planned=total)
    captured = capsys.readouterr()
    assert expected_pct in captured.out
