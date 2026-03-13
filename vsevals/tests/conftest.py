"""Shared fixtures for vsevals test suite."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from vsevals.models import (
    GeneratedPayload,
    LLMResult,
    OracleConstraint,
    PromptBundle,
    PytestResult,
    RetrievedSnippet,
    RunArtifactPaths,
    RunConfig,
    RunError,
    RunResult,
    ScoreDimension,
    ScoreResult,
    SuiteConfig,
    SuiteMeta,
    SuiteTask,
    SummaryMetrics,
    TaskOracle,
    TaskVisible,
    TaskVoltsnipConfig,
    TimingInfo,
    TokenUsage,
    ToolTrace,
    VariantConfig,
)


@pytest.fixture
def run_config():
    return RunConfig(
        api_key="test-key",
        voltsnip_base_url="http://localhost:8000",
        scoring_judge_model="mock:default",
    )


@pytest.fixture
def variant_p0():
    return VariantConfig(
        id="P0",
        mode="direct",
        memory_enabled=False,
        tools_enabled=False,
        retrieval_mode="none",
        instruction_mode="none",
        context_surface="user",
    )


@pytest.fixture
def variant_p3():
    return VariantConfig(
        id="P2",
        mode="agent",
        memory_enabled=True,
        tools_enabled=False,
        retrieval_mode="injected",
        instruction_mode="none",
        context_surface="system",
    )


@pytest.fixture
def variant_p5():
    return VariantConfig(
        id="P5",
        mode="agent",
        memory_enabled=True,
        tools_enabled=True,
        retrieval_mode="agent_decides",
        instruction_mode="none",
        context_surface="agents_md_no_keys",
        max_tool_roundtrips=8,
    )


@pytest.fixture
def task_visible():
    return TaskVisible(
        id="BUG01",
        name="Test Bug",
        user_prompt="Fix the bug in the function",
        target_file="src/main.py",
        line_start=10,
        line_end=20,
        test_command="pytest tests/",
    )


@pytest.fixture
def suite_task(task_visible):
    return SuiteTask(
        task=task_visible,
        voltsnip=TaskVoltsnipConfig(required_snippets=["key1", "key2"]),
        oracle=TaskOracle(
            hidden_requirements=["must use correct API"],
            success_indicators=_default_success_indicators(),
            failure_modes=["uses deprecated method"],
            evaluation_criteria=["code is clean"],
            constraints=[
                OracleConstraint(
                    id="c1",
                    check="uses correct API",
                    judge_prompt="Does the code use the correct API?",
                    expected=True,
                ),
                OracleConstraint(
                    id="c2",
                    check="no deprecated methods",
                    judge_prompt="Does the code avoid deprecated methods?",
                    expected=False,
                ),
            ],
        ),
    )


@pytest.fixture
def sample_snippets():
    return [
        RetrievedSnippet(
            id="s1",
            canonical_key="key1",
            title="API Usage",
            language="python",
            tags=["api"],
            code="def emit(metric, value): pass",
        ),
        RetrievedSnippet(
            id="s2",
            canonical_key="key2",
            title="Config Pattern",
            language="python",
            tags=["config"],
            code="CONFIG = {'timeout': 30}",
        ),
    ]


@pytest.fixture
def prompt_bundle():
    return PromptBundle(
        system_prompt="You are a test assistant.",
        user_prompt="Fix the bug.",
        context_surface="user",
    )


@pytest.fixture
def token_usage():
    return TokenUsage(
        prompt_tokens=100,
        completion_tokens=50,
        total_tokens=150,
        cached_tokens=0,
        cost_usd=0.001,
    )


@pytest.fixture
def timings():
    now = datetime.now(timezone.utc)
    return TimingInfo(
        started_at=now,
        finished_at=now,
        latency_ms=500,
    )


@pytest.fixture
def run_result(prompt_bundle, token_usage, timings):
    return RunResult(
        run_id="test-run-001",
        suite_path="/tmp/suite.yaml",
        output_root="/tmp/output",
        task_id="BUG01",
        task_name="Test Bug",
        variant_id="P0",
        model_name="mock:default",
        status="ok",
        variant_mode="direct",
        variant_memory_enabled=False,
        variant_tools_enabled=False,
        variant_retrieval_mode="none",
        variant_context_surface="user",
        required_snippet_keys=["key1", "key2"],
        prompt=prompt_bundle,
        parsed_output=GeneratedPayload(code="def fix(): return 42", comments="fixed"),
        token_usage=token_usage,
        timings=timings,
        summary_metrics=SummaryMetrics(
            latency_ms=500,
            prompt_chars=100,
            output_chars=50,
            token_usage=token_usage,
        ),
        artifacts=RunArtifactPaths(
            run_dir="/tmp/output/run",
            full_dump_json="/tmp/output/run/full_dump.json",
            summary_dump_json="/tmp/output/run/summary.json",
            code_output="/tmp/output/run/code.py",
            comments_output="/tmp/output/run/comments.txt",
        ),
    )


@pytest.fixture
def tmp_repo(tmp_path):
    """Create a temporary repo structure for tool tests."""
    root = tmp_path / "repo"
    root.mkdir()
    (root / "src").mkdir()
    (root / "src" / "main.py").write_text(
        "def hello():\n    return 'world'\n\ndef add(a, b):\n    return a + b\n"
    )
    (root / "src" / "utils.py").write_text(
        "import os\n\ndef get_path():\n    return os.getcwd()\n"
    )
    (root / "README.md").write_text("# Test Repo\n")
    return root


def _default_success_indicators():
    from vsevals.models import SuccessIndicators
    return SuccessIndicators(correctness=["correct output"])
