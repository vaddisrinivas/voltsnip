"""Comprehensive tests for vsevals.runner — the core execution engine.

Uses function-based tests, pytest.mark.parametrize, and unittest.mock.patch.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

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
    SuccessIndicators,
    TaskOracle,
    TaskVisible,
    TaskVoltsnipConfig,
    TimingInfo,
    TokenUsage,
    ToolTrace,
    VariantConfig,
)
from vsevals.runner import (
    _classify_error,
    _container_file_path,
    _dedup_snippets,
    _empty_llm_result,
    _invoke_tool,
    _load_dotenv_keys,
    _load_provider_keys,
    _make_artifact_paths,
    _make_client,
    _merge_tool_snippets,
    _parse_provider,
    _read_target_file,
    _resolve_repo_root,
    _retrieve_snippets,
    _run_agent,
    _run_patch_and_test,
    _write_artifacts,
    _write_raw_llm_artifacts,
    main,
    run_hypothesis,
    run_one,
)


# ============================================================================
# Helpers for building fixtures inline
# ============================================================================


def _make_variant(
    id: str = "P0",
    mode: str = "direct",
    memory_enabled: bool = False,
    tools_enabled: bool = False,
    retrieval_mode: str = "none",
    instruction_mode: str = "none",
    context_surface: str = "user",
    max_tool_roundtrips: int = 4,
) -> VariantConfig:
    return VariantConfig(
        id=id,
        mode=mode,
        memory_enabled=memory_enabled,
        tools_enabled=tools_enabled,
        retrieval_mode=retrieval_mode,
        instruction_mode=instruction_mode,
        context_surface=context_surface,
        max_tool_roundtrips=max_tool_roundtrips,
    )


def _make_task(
    task_id: str = "BUG01",
    name: str = "Test Bug",
    user_prompt: str = "Fix the bug",
    target_file: str | None = "src/main.py",
    required_snippets: list[str] | None = None,
) -> SuiteTask:
    return SuiteTask(
        task=TaskVisible(
            id=task_id,
            name=name,
            user_prompt=user_prompt,
            target_file=target_file,
        ),
        voltsnip=TaskVoltsnipConfig(
            required_snippets=required_snippets or [],
        ),
        oracle=TaskOracle(),
    )


def _make_snippet(id: str = "s1", canonical_key: str = "key1", code: str = "pass") -> RetrievedSnippet:
    return RetrievedSnippet(id=id, canonical_key=canonical_key, title="Snippet", code=code)


def _make_llm_result(
    raw_output: str = '{"code":"def fix(): pass","comments":"fixed"}',
    code: str = "def fix(): pass",
    comments: str = "fixed",
    subprocess_stdout: str = "",
    subprocess_stderr: str = "",
    api_response_raw: str = "",
) -> LLMResult:
    now = datetime.now(timezone.utc)
    return LLMResult(
        raw_output=raw_output,
        parsed_output=GeneratedPayload(code=code, comments=comments),
        token_usage=TokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150),
        structured_output_attempted=True,
        structured_output_succeeded=True,
        fallback_parser_used=False,
        request_started_at=now,
        request_finished_at=now,
        request_latency_ms=200,
        request_id="req-001",
        finish_reason="stop",
        subprocess_stdout=subprocess_stdout,
        subprocess_stderr=subprocess_stderr,
        api_response_raw=api_response_raw,
    )


def _make_prompt_bundle() -> PromptBundle:
    return PromptBundle(
        system_prompt="You are a test assistant.",
        user_prompt="Fix the bug.",
        context_surface="user",
    )


def _make_run_config(**overrides) -> RunConfig:
    defaults = dict(
        api_key="test-key",
        voltsnip_base_url="http://localhost:8000",
        scoring_judge_model="mock:default",
    )
    defaults.update(overrides)
    return RunConfig(**defaults)


def _make_run_result(tmp_path: Path, status: str = "ok", code: str = "def fix(): return 42") -> RunResult:
    now = datetime.now(timezone.utc)
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    return RunResult(
        run_id="test-run-001",
        suite_path="/tmp/suite.yaml",
        output_root=str(tmp_path),
        task_id="BUG01",
        task_name="Test Bug",
        variant_id="P0",
        model_name="mock:default",
        status=status,
        prompt=_make_prompt_bundle(),
        parsed_output=GeneratedPayload(code=code, comments="fixed"),
        token_usage=TokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150),
        timings=TimingInfo(started_at=now, finished_at=now, latency_ms=500),
        summary_metrics=SummaryMetrics(
            latency_ms=500,
            prompt_chars=100,
            output_chars=50,
            token_usage=TokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150),
        ),
        artifacts=RunArtifactPaths(
            run_dir=str(run_dir),
            full_dump_json=str(run_dir / "full_dump.json"),
            summary_dump_json=str(run_dir / "summary_dump.json"),
            code_output=str(run_dir / "generated_code.txt"),
            comments_output=str(run_dir / "generated_comments.txt"),
        ),
    )


# ============================================================================
# 1. _parse_provider
# ============================================================================


@pytest.mark.parametrize(
    "model_name, expected",
    [
        ("openai:gpt-5-mini", ("openai", "gpt-5-mini")),
        ("gpt-5-mini", ("openai", "gpt-5-mini")),
        ("anthropic:claude-haiku-4-5", ("anthropic", "claude-haiku-4-5")),
        ("claudecode:claude-sonnet-4-5", ("claudecode", "claude-sonnet-4-5")),
        ("codex:gpt-5.3-codex", ("codex", "gpt-5.3-codex")),
        ("OPENAI:GPT-5-MINI", ("openai", "GPT-5-MINI")),
    ],
    ids=[
        "explicit-openai",
        "default-openai",
        "anthropic",
        "claudecode",
        "codex",
        "case-insensitive-provider",
    ],
)
def test_parse_provider(model_name, expected):
    assert _parse_provider(model_name) == expected


# ============================================================================
# 2. _dedup_snippets
# ============================================================================


def test_dedup_snippets_empty():
    assert _dedup_snippets([]) == []


def test_dedup_snippets_same_canonical_key():
    s1 = _make_snippet(id="s1", canonical_key="key1", code="a")
    s2 = _make_snippet(id="s2", canonical_key="key1", code="b")
    result = _dedup_snippets([s1, s2])
    assert len(result) == 1
    assert result[0].id == "s1"


def test_dedup_snippets_different_keys():
    s1 = _make_snippet(id="s1", canonical_key="key1")
    s2 = _make_snippet(id="s2", canonical_key="key2")
    result = _dedup_snippets([s1, s2])
    assert len(result) == 2


def test_dedup_snippets_falls_back_to_id():
    s1 = RetrievedSnippet(id="s1", canonical_key=None, code="a")
    s2 = RetrievedSnippet(id="s1", canonical_key=None, code="b")
    result = _dedup_snippets([s1, s2])
    assert len(result) == 1


# ============================================================================
# 3. _empty_llm_result
# ============================================================================


def test_empty_llm_result_defaults():
    r = _empty_llm_result()
    assert isinstance(r, LLMResult)
    assert r.raw_output == ""
    assert r.parsed_output.code == ""
    assert r.parsed_output.comments == ""
    assert r.structured_output_attempted is False
    assert r.structured_output_succeeded is False
    assert r.fallback_parser_used is False
    assert r.request_started_at is None
    assert r.request_finished_at is None
    assert r.request_latency_ms is None
    assert r.request_id is None
    assert r.finish_reason is None


# ============================================================================
# 4. _container_file_path
# ============================================================================


@pytest.mark.parametrize(
    "workdir, target_file, expected",
    [
        ("/workspace", "src/main.py", "/workspace/src/main.py"),
        ("/workspace/", "src/main.py", "/workspace/src/main.py"),
        ("/workspace", "/absolute/path.py", "/absolute/path.py"),
        ("/app", "utils.py", "/app/utils.py"),
    ],
    ids=["basic-relative", "trailing-slash", "absolute-target", "different-workdir"],
)
def test_container_file_path(workdir, target_file, expected):
    assert _container_file_path(workdir=workdir, target_file=target_file) == expected


# ============================================================================
# 5. _classify_error
# ============================================================================


@pytest.mark.parametrize(
    "exc, expected_class",
    [
        (Exception("api key invalid"), "AUTH_ERROR"),
        (Exception("401 unauthorized"), "AUTH_ERROR"),
        (Exception("403 Forbidden"), "AUTH_ERROR"),
        (Exception("rate limit exceeded"), "RATE_LIMIT_ERROR"),
        (Exception("429 Too Many Requests"), "RATE_LIMIT_ERROR"),
        (Exception("quota exceeded"), "RATE_LIMIT_ERROR"),
        (TimeoutError("request timed out"), "TIMEOUT"),
        (Exception("timed out waiting for response"), "TIMEOUT"),
        (Exception("connection refused"), "NETWORK_ERROR"),
        (Exception("SSL certificate error"), "NETWORK_ERROR"),
        (Exception("failed to parse json response"), "LLM_PARSE_ERROR"),
        (Exception("non-json output from model"), "LLM_PARSE_ERROR"),
        (Exception("voltsnip retrieval error"), "RETRIEVAL_ERROR"),
        (Exception("get_by_canonical keys failed"), "RETRIEVAL_ERROR"),
        (Exception("unknown task BUG99"), "CONFIG_ERROR"),
        (ValueError("missing required field"), "CONFIG_ERROR"),
        (KeyError("not found in config"), "CONFIG_ERROR"),
        (Exception("empty output from model"), "EMPTY_OUTPUT"),
        (Exception("some random error that fits no category"), "UNKNOWN_ERROR"),
    ],
    ids=[
        "api-key-invalid",
        "401-unauthorized",
        "403-forbidden",
        "rate-limit",
        "429",
        "quota",
        "timeout-error-type",
        "timed-out-message",
        "connection-refused",
        "ssl-error",
        "parse-json",
        "non-json-output",
        "voltsnip-retrieval",
        "canonical-keys-retrieval",
        "unknown-task-config",
        "value-error-missing",
        "key-error-not-found",
        "empty-output",
        "unknown-error",
    ],
)
def test_classify_error(exc, expected_class):
    assert _classify_error(exc) == expected_class


# ============================================================================
# 6. _resolve_repo_root
# ============================================================================


def test_resolve_repo_root_none():
    assert _resolve_repo_root(None, suite_path="/tmp/suite.yaml") is None


def test_resolve_repo_root_empty_string():
    assert _resolve_repo_root("", suite_path="/tmp/suite.yaml") is None


def test_resolve_repo_root_absolute_path(tmp_path):
    abs_path = str(tmp_path / "repo")
    (tmp_path / "repo").mkdir()
    result = _resolve_repo_root(abs_path, suite_path="/tmp/suite.yaml")
    assert result is not None
    assert result == (tmp_path / "repo").resolve()


def test_resolve_repo_root_relative_in_cwd(tmp_path, monkeypatch):
    repo = tmp_path / "myrepo"
    repo.mkdir()
    monkeypatch.chdir(tmp_path)
    result = _resolve_repo_root("myrepo", suite_path="/tmp/suite.yaml")
    assert result is not None
    assert result == repo.resolve()


def test_resolve_repo_root_relative_falls_to_suite_dir(tmp_path, monkeypatch):
    # Create repo relative to suite dir, NOT cwd
    suite_dir = tmp_path / "suites"
    suite_dir.mkdir()
    repo = suite_dir / "relrepo"
    repo.mkdir()
    # cwd does not have relrepo
    monkeypatch.chdir(tmp_path)
    result = _resolve_repo_root("relrepo", suite_path=str(suite_dir / "suite.yaml"))
    assert result is not None
    assert result == repo.resolve()


# ============================================================================
# 7. _read_target_file
# ============================================================================


def test_read_target_file_no_target():
    assert _read_target_file(repo_root=Path("/tmp"), target_file=None, suite_path="/tmp/suite.yaml") is None


def test_read_target_file_no_repo_root():
    assert _read_target_file(repo_root=None, target_file="src/main.py", suite_path="/tmp/suite.yaml") is None


def test_read_target_file_exists(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    target = src / "main.py"
    target.write_text("hello world", encoding="utf-8")
    result = _read_target_file(repo_root=tmp_path, target_file="src/main.py", suite_path="/tmp/suite.yaml")
    assert result == "hello world"


def test_read_target_file_missing(tmp_path):
    result = _read_target_file(repo_root=tmp_path, target_file="does_not_exist.py", suite_path="/tmp/suite.yaml")
    assert result is None


# ============================================================================
# 8. _make_artifact_paths (filesystem)
# ============================================================================


def test_make_artifact_paths_creates_dir(tmp_path):
    output_root = str(tmp_path / "output")
    result = _make_artifact_paths(output_root=output_root, task_id="BUG01", variant_id="P0", model_name="openai:gpt-5-mini")
    assert Path(result.run_dir).exists()
    assert Path(result.run_dir).is_dir()


def test_make_artifact_paths_sanitizes_special_chars(tmp_path):
    output_root = str(tmp_path / "output")
    result = _make_artifact_paths(
        output_root=output_root,
        task_id="BUG/01@special",
        variant_id="P0!!",
        model_name="openai:gpt-5-mini",
    )
    run_dir_name = Path(result.run_dir).name
    # Should not contain special chars beyond a-zA-Z0-9._-
    assert "/" not in run_dir_name
    assert "@" not in run_dir_name
    assert "!" not in run_dir_name


def test_make_artifact_paths_has_expected_fields(tmp_path):
    output_root = str(tmp_path / "output")
    result = _make_artifact_paths(output_root=output_root, task_id="BUG01", variant_id="P0", model_name="mock:default")
    assert result.full_dump_json.endswith("full_dump.json")
    assert result.summary_dump_json.endswith("summary_dump.json")
    assert result.code_output.endswith("generated_code.txt")
    assert result.comments_output.endswith("generated_comments.txt")


# ============================================================================
# 9. _write_artifacts (filesystem)
# ============================================================================


def test_write_artifacts_without_score(tmp_path):
    rr = _make_run_result(tmp_path)
    _write_artifacts(run_result=rr, score=None)
    assert Path(rr.artifacts.full_dump_json).exists()
    assert Path(rr.artifacts.summary_dump_json).exists()
    assert Path(rr.artifacts.code_output).exists()
    assert Path(rr.artifacts.comments_output).exists()
    summary = json.loads(Path(rr.artifacts.summary_dump_json).read_text())
    assert summary["score"] is None


def test_write_artifacts_with_score(tmp_path):
    rr = _make_run_result(tmp_path)
    score = ScoreResult(
        overall_score=0.85,
        hidden_requirements=ScoreDimension(matched=1, total=1, score=1.0),
        success_indicators=ScoreDimension(matched=1, total=1, score=1.0),
        failure_modes=ScoreDimension(matched=0, total=1, score=0.0),
        passed=True,
    )
    _write_artifacts(run_result=rr, score=score)
    summary = json.loads(Path(rr.artifacts.summary_dump_json).read_text())
    assert summary["score"]["overall_score"] == 0.85
    # score_result.json should also be written
    score_file = Path(rr.artifacts.run_dir) / "score_result.json"
    assert score_file.exists()


def test_write_artifacts_with_pytest_result(tmp_path):
    rr = _make_run_result(tmp_path)
    rr.pytest_result = PytestResult(ran=True, returncode=0, passed=True, stdout="ok", stderr="")
    _write_artifacts(run_result=rr, score=None)
    assert (Path(rr.artifacts.run_dir) / "pytest.stdout.txt").exists()
    assert (Path(rr.artifacts.run_dir) / "pytest.stderr.txt").exists()


# ============================================================================
# 10. _write_raw_llm_artifacts (filesystem)
# ============================================================================


def test_write_raw_llm_artifacts_stdout_stderr(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    llm = _make_llm_result(subprocess_stdout="line1\nline2", subprocess_stderr="warning")
    _write_raw_llm_artifacts(llm_result=llm, run_dir=str(run_dir), provider="claudecode")
    stdout_file = run_dir / "subprocess.stdout.claudecode.jsonl"
    stderr_file = run_dir / "subprocess.stderr.claudecode.txt"
    assert stdout_file.exists()
    assert stdout_file.read_text() == "line1\nline2"
    assert stderr_file.exists()
    assert stderr_file.read_text() == "warning"


def test_write_raw_llm_artifacts_api_response(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    llm = _make_llm_result(api_response_raw='{"id":"resp-001"}')
    _write_raw_llm_artifacts(llm_result=llm, run_dir=str(run_dir), provider="openai")
    api_file = run_dir / "llm_response.openai.json"
    assert api_file.exists()
    assert "resp-001" in api_file.read_text()


def test_write_raw_llm_artifacts_skips_existing(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    # Pre-create the file
    existing = run_dir / "subprocess.stdout.codex.jsonl"
    existing.write_text("original content")
    llm = _make_llm_result(subprocess_stdout="new content")
    _write_raw_llm_artifacts(llm_result=llm, run_dir=str(run_dir), provider="codex")
    # Should NOT overwrite
    assert existing.read_text() == "original content"


def test_write_raw_llm_artifacts_empty_content_skipped(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    llm = _make_llm_result(subprocess_stdout="", subprocess_stderr="", api_response_raw="")
    _write_raw_llm_artifacts(llm_result=llm, run_dir=str(run_dir), provider="openai")
    # No files should be created for empty content
    assert not (run_dir / "subprocess.stdout.openai.jsonl").exists()
    assert not (run_dir / "subprocess.stderr.openai.txt").exists()
    assert not (run_dir / "llm_response.openai.json").exists()


# ============================================================================
# 11. _load_provider_keys (mocking)
# ============================================================================


def test_load_provider_keys_from_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-123")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-456")
    cfg = _make_run_config(api_key=None, provider_api_keys={})
    with patch("vsevals.runner._load_dotenv_keys", return_value={}):
        keys = _load_provider_keys(cfg)
    assert keys["openai"] == "sk-openai-123"
    assert keys["anthropic"] == "sk-ant-456"


def test_load_provider_keys_cfg_api_key_override():
    cfg = _make_run_config(api_key="master-key")
    with patch("vsevals.runner._load_dotenv_keys", return_value={}):
        with patch.dict(os.environ, {}, clear=True):
            keys = _load_provider_keys(cfg)
    assert keys["_override"] == "master-key"


def test_load_provider_keys_cfg_provider_api_keys():
    cfg = _make_run_config(api_key=None, provider_api_keys={"openai": "cfg-openai-key"})
    with patch("vsevals.runner._load_dotenv_keys", return_value={}):
        with patch.dict(os.environ, {}, clear=True):
            keys = _load_provider_keys(cfg)
    assert keys["openai"] == "cfg-openai-key"


# ============================================================================
# 12. _load_dotenv_keys (mocking)
# ============================================================================


def test_load_dotenv_keys_file_exists(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY=sk-dotenv-openai\nANTHROPIC_API_KEY=sk-dotenv-ant\n")
    monkeypatch.chdir(tmp_path)
    result = _load_dotenv_keys()
    assert result["openai"] == "sk-dotenv-openai"
    assert result["anthropic"] == "sk-dotenv-ant"


def test_load_dotenv_keys_no_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = _load_dotenv_keys()
    assert result == {}


def test_load_dotenv_keys_ignores_comments_and_blanks(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("# comment\n\nOPENAI_API_KEY=sk-val\nIRRELEVANT_KEY=ignored\n")
    monkeypatch.chdir(tmp_path)
    result = _load_dotenv_keys()
    assert result == {"openai": "sk-val"}


# ============================================================================
# 13. _make_client (mocking)
# ============================================================================


def test_make_client_no_memory_no_tools():
    variant = _make_variant(memory_enabled=False, tools_enabled=False)
    cfg = _make_run_config()
    result = _make_client(variant, cfg)
    assert result is None


@patch("vsevals.runner.VoltSnipClient")
def test_make_client_memory_enabled_success(MockClient):
    variant = _make_variant(memory_enabled=True, tools_enabled=False)
    cfg = _make_run_config()
    instance = MockClient.return_value
    instance.preflight_check.return_value = True
    result = _make_client(variant, cfg)
    assert result is instance
    MockClient.assert_called_once()


@patch("vsevals.runner.VoltSnipClient")
def test_make_client_tools_enabled_success(MockClient):
    variant = _make_variant(
        memory_enabled=False,
        tools_enabled=True,
        retrieval_mode="agent_decides",
        context_surface="tools_only",
    )
    cfg = _make_run_config()
    instance = MockClient.return_value
    instance.preflight_check.return_value = True
    result = _make_client(variant, cfg)
    assert result is instance


@patch("vsevals.runner.VoltSnipClient")
def test_make_client_preflight_fails(MockClient):
    variant = _make_variant(memory_enabled=True)
    cfg = _make_run_config()
    instance = MockClient.return_value
    instance.preflight_check.return_value = False
    with pytest.raises(RuntimeError, match="preflight check failed"):
        _make_client(variant, cfg)


# ============================================================================
# 14. _retrieve_snippets (mocking)
# ============================================================================


def test_retrieve_snippets_no_voltsnip():
    task = _make_task(required_snippets=["key1"])
    variant = _make_variant(memory_enabled=True)
    cfg = _make_run_config()
    result = _retrieve_snippets(task=task, variant=variant, voltsnip=None, cfg=cfg)
    assert result == []


def test_retrieve_snippets_no_required_keys():
    task = _make_task(required_snippets=[])
    variant = _make_variant(memory_enabled=True)
    cfg = _make_run_config()
    mock_vs = MagicMock()
    result = _retrieve_snippets(task=task, variant=variant, voltsnip=mock_vs, cfg=cfg)
    assert result == []
    mock_vs.get_by_canonical_keys.assert_not_called()


def test_retrieve_snippets_with_keys():
    task = _make_task(required_snippets=["key1", "key2"])
    variant = _make_variant(memory_enabled=True)
    cfg = _make_run_config()
    mock_vs = MagicMock()
    expected = [_make_snippet(id="s1", canonical_key="key1"), _make_snippet(id="s2", canonical_key="key2")]
    mock_vs.get_by_canonical_keys.return_value = expected
    result = _retrieve_snippets(task=task, variant=variant, voltsnip=mock_vs, cfg=cfg)
    assert result == expected
    mock_vs.get_by_canonical_keys.assert_called_once()


# ============================================================================
# 15. _invoke_tool (mocking)
# ============================================================================


def test_invoke_tool_success():
    mock_vs = MagicMock()
    snippets: list[RetrievedSnippet] = []
    tool_traces: list[ToolTrace] = []
    roundtrip_count = {"n": 0}
    new_snippet = _make_snippet(id="s1", canonical_key="k1", code="code")

    result = _invoke_tool(
        name="voltsnip.get_by_canonical_keys",
        args={"canonical_keys": ["k1"]},
        voltsnip=mock_vs,
        snippets=snippets,
        tool_traces=tool_traces,
        roundtrip_count=roundtrip_count,
        max_roundtrips=4,
        fetch=lambda: [new_snippet],
    )
    assert "snippets" in result
    assert len(result["snippets"]) == 1
    assert len(snippets) == 1
    assert len(tool_traces) == 1
    assert tool_traces[0].error is None
    assert roundtrip_count["n"] == 1


def test_invoke_tool_budget_exceeded():
    mock_vs = MagicMock()
    snippets: list[RetrievedSnippet] = []
    tool_traces: list[ToolTrace] = []
    roundtrip_count = {"n": 4}  # already at max

    result = _invoke_tool(
        name="voltsnip.get_by_canonical_keys",
        args={"canonical_keys": ["k1"]},
        voltsnip=mock_vs,
        snippets=snippets,
        tool_traces=tool_traces,
        roundtrip_count=roundtrip_count,
        max_roundtrips=4,
        fetch=lambda: [],
    )
    assert "error" in result
    assert "budget exceeded" in result["error"]
    assert len(tool_traces) == 1
    assert tool_traces[0].error is not None


def test_invoke_tool_fetch_raises():
    mock_vs = MagicMock()
    snippets: list[RetrievedSnippet] = []
    tool_traces: list[ToolTrace] = []
    roundtrip_count = {"n": 0}

    def _fail():
        raise RuntimeError("network down")

    result = _invoke_tool(
        name="voltsnip.get_by_canonical_keys",
        args={"canonical_keys": ["k1"]},
        voltsnip=mock_vs,
        snippets=snippets,
        tool_traces=tool_traces,
        roundtrip_count=roundtrip_count,
        max_roundtrips=4,
        fetch=_fail,
    )
    assert "error" in result
    assert "network down" in result["error"]
    assert len(tool_traces) == 1
    assert tool_traces[0].error is not None


# ============================================================================
# 16. _merge_tool_snippets (mocking)
# ============================================================================


def test_merge_tool_snippets_no_voltsnip():
    snippets: list[RetrievedSnippet] = []
    traces = [ToolTrace(roundtrip=1, tool_name="fetch")]
    # Should not raise
    _merge_tool_snippets(traces, snippets, voltsnip=None, cfg=_make_run_config(), task=_make_task())
    assert snippets == []


def test_merge_tool_snippets_no_traces():
    mock_vs = MagicMock()
    snippets: list[RetrievedSnippet] = []
    _merge_tool_snippets([], snippets, voltsnip=mock_vs, cfg=_make_run_config(), task=_make_task())
    mock_vs.get_by_canonical_keys.assert_not_called()


def test_merge_tool_snippets_fetch_by_key_traces():
    mock_vs = MagicMock()
    fetched = [_make_snippet(id="s1", canonical_key="k1")]
    mock_vs.get_by_canonical_keys.return_value = fetched
    snippets: list[RetrievedSnippet] = []
    traces = [
        ToolTrace(
            roundtrip=1,
            tool_name="voltsnip_fetch_by_canonical_keys",
            tool_args={"canonical_keys": ["k1"]},
        ),
    ]
    _merge_tool_snippets(traces, snippets, voltsnip=mock_vs, cfg=_make_run_config(), task=_make_task())
    assert len(snippets) == 1
    mock_vs.get_by_canonical_keys.assert_called_once()


def test_merge_tool_snippets_search_traces():
    mock_vs = MagicMock()
    found = [_make_snippet(id="s2", canonical_key="k2")]
    mock_vs.semantic_search.return_value = found
    snippets: list[RetrievedSnippet] = []
    traces = [
        ToolTrace(
            roundtrip=1,
            tool_name="search_memory",
            tool_args={"query": "retry policy"},
        ),
    ]
    _merge_tool_snippets(traces, snippets, voltsnip=mock_vs, cfg=_make_run_config(), task=_make_task())
    assert len(snippets) == 1
    mock_vs.semantic_search.assert_called_once()


# ============================================================================
# 17. run_hypothesis (mocking)
# ============================================================================


@patch("vsevals.runner.run_one")
def test_run_hypothesis_valid(mock_run_one, tmp_path):
    mock_run_one.return_value = MagicMock(spec=RunResult)
    result = run_hypothesis(
        hypothesis="P0",
        task_id="BUG01",
        model_name="mock:default",
        suite_path="suite.yaml",
        output_dir=str(tmp_path),
    )
    mock_run_one.assert_called_once_with(
        task_id="BUG01",
        variant_id="P0",
        model_name="mock:default",
        suite_path="suite.yaml",
        output_dir=str(tmp_path),
        repo_root=None,
        cfg=None,
    )


def test_run_hypothesis_invalid():
    with pytest.raises(ValueError, match="unknown hypothesis"):
        run_hypothesis(
            hypothesis="P99",
            task_id="BUG01",
            model_name="mock:default",
            suite_path="suite.yaml",
            output_dir="/tmp",
        )


# ============================================================================
# 18. run_one (heavy mocking)
# ============================================================================


@patch("vsevals.runner._write_artifacts")
@patch("vsevals.runner._write_raw_llm_artifacts")
@patch("vsevals.runner.score_one")
@patch("vsevals.runner.call_llm")
@patch("vsevals.runner.build_prompt")
@patch("vsevals.runner._read_target_file", return_value=None)
@patch("vsevals.runner._resolve_repo_root", return_value=None)
@patch("vsevals.runner._make_client", return_value=None)
@patch("vsevals.runner._load_provider_keys", return_value={})
@patch("vsevals.runner._make_artifact_paths")
@patch("vsevals.runner.load_suite")
def test_run_one_ok_path(
    mock_load_suite,
    mock_artifact_paths,
    mock_load_keys,
    mock_make_client,
    mock_resolve_root,
    mock_read_target,
    mock_build_prompt,
    mock_call_llm,
    mock_score_one,
    mock_write_raw,
    mock_write_artifacts,
    tmp_path,
):
    # Set up a mock suite
    task = _make_task()
    variant = _make_variant()
    mock_suite = MagicMock()
    mock_suite.task_map = {task.id: task}
    mock_suite.variant_map = {variant.id: variant}
    mock_suite.suite.pytest_docker_image = None
    mock_suite.suite.pytest_docker_workdir = None
    mock_suite.suite.default_repo_root = None
    mock_load_suite.return_value = mock_suite

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    mock_artifact_paths.return_value = RunArtifactPaths(
        run_dir=str(run_dir),
        full_dump_json=str(run_dir / "full_dump.json"),
        summary_dump_json=str(run_dir / "summary.json"),
        code_output=str(run_dir / "code.txt"),
        comments_output=str(run_dir / "comments.txt"),
    )

    mock_build_prompt.return_value = _make_prompt_bundle()
    mock_call_llm.return_value = _make_llm_result(code="def fix(): return 42")
    mock_score_one.return_value = ScoreResult(
        overall_score=1.0,
        hidden_requirements=ScoreDimension(matched=1, total=1, score=1.0),
        success_indicators=ScoreDimension(matched=1, total=1, score=1.0),
        failure_modes=ScoreDimension(matched=0, total=0, score=1.0),
        passed=True,
    )

    result = run_one(
        task_id="BUG01",
        variant_id="P0",
        model_name="mock:default",
        suite_path="suite.yaml",
        output_dir=str(tmp_path),
    )
    assert result.status == "ok"
    assert result.task_id == "BUG01"
    assert result.variant_id == "P0"
    mock_call_llm.assert_called_once()
    mock_score_one.assert_called_once()


@patch("vsevals.runner._write_artifacts")
@patch("vsevals.runner._write_raw_llm_artifacts")
@patch("vsevals.runner.call_llm")
@patch("vsevals.runner.build_prompt")
@patch("vsevals.runner._read_target_file", return_value=None)
@patch("vsevals.runner._resolve_repo_root", return_value=None)
@patch("vsevals.runner._make_client", return_value=None)
@patch("vsevals.runner._load_provider_keys", return_value={})
@patch("vsevals.runner._make_artifact_paths")
@patch("vsevals.runner.load_suite")
def test_run_one_error_path(
    mock_load_suite,
    mock_artifact_paths,
    mock_load_keys,
    mock_make_client,
    mock_resolve_root,
    mock_read_target,
    mock_build_prompt,
    mock_call_llm,
    mock_write_raw,
    mock_write_artifacts,
    tmp_path,
):
    task = _make_task()
    variant = _make_variant()
    mock_suite = MagicMock()
    mock_suite.task_map = {task.id: task}
    mock_suite.variant_map = {variant.id: variant}
    mock_suite.suite.pytest_docker_image = None
    mock_suite.suite.pytest_docker_workdir = None
    mock_suite.suite.default_repo_root = None
    mock_load_suite.return_value = mock_suite

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    mock_artifact_paths.return_value = RunArtifactPaths(
        run_dir=str(run_dir),
        full_dump_json=str(run_dir / "full_dump.json"),
        summary_dump_json=str(run_dir / "summary.json"),
        code_output=str(run_dir / "code.txt"),
        comments_output=str(run_dir / "comments.txt"),
    )

    mock_build_prompt.return_value = _make_prompt_bundle()
    mock_call_llm.side_effect = RuntimeError("API connection failed")

    result = run_one(
        task_id="BUG01",
        variant_id="P0",
        model_name="mock:default",
        suite_path="suite.yaml",
        output_dir=str(tmp_path),
    )
    assert result.status == "error"
    assert result.error is not None
    assert "API connection failed" in result.error.message


@patch("vsevals.runner._write_artifacts")
@patch("vsevals.runner._write_raw_llm_artifacts")
@patch("vsevals.runner.call_llm")
@patch("vsevals.runner.build_prompt")
@patch("vsevals.runner._read_target_file", return_value=None)
@patch("vsevals.runner._resolve_repo_root", return_value=None)
@patch("vsevals.runner._make_client", return_value=None)
@patch("vsevals.runner._load_provider_keys", return_value={})
@patch("vsevals.runner._make_artifact_paths")
@patch("vsevals.runner.load_suite")
def test_run_one_empty_output_demoted_to_error(
    mock_load_suite,
    mock_artifact_paths,
    mock_load_keys,
    mock_make_client,
    mock_resolve_root,
    mock_read_target,
    mock_build_prompt,
    mock_call_llm,
    mock_write_raw,
    mock_write_artifacts,
    tmp_path,
):
    task = _make_task()
    variant = _make_variant()
    mock_suite = MagicMock()
    mock_suite.task_map = {task.id: task}
    mock_suite.variant_map = {variant.id: variant}
    mock_suite.suite.pytest_docker_image = None
    mock_suite.suite.pytest_docker_workdir = None
    mock_suite.suite.default_repo_root = None
    mock_load_suite.return_value = mock_suite

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    mock_artifact_paths.return_value = RunArtifactPaths(
        run_dir=str(run_dir),
        full_dump_json=str(run_dir / "full_dump.json"),
        summary_dump_json=str(run_dir / "summary.json"),
        code_output=str(run_dir / "code.txt"),
        comments_output=str(run_dir / "comments.txt"),
    )

    mock_build_prompt.return_value = _make_prompt_bundle()
    # LLM returns empty code
    mock_call_llm.return_value = _make_llm_result(code="", comments="")

    result = run_one(
        task_id="BUG01",
        variant_id="P0",
        model_name="mock:default",
        suite_path="suite.yaml",
        output_dir=str(tmp_path),
    )
    assert result.status == "error"
    assert result.error is not None
    assert result.error.type == "EmptyOutput"


@patch("vsevals.runner.load_suite")
def test_run_one_unknown_task(mock_load_suite, tmp_path):
    mock_suite = MagicMock()
    mock_suite.task_map = {}
    mock_suite.variant_map = {"P0": _make_variant()}
    mock_suite.suite.pytest_docker_image = None
    mock_suite.suite.pytest_docker_workdir = None
    mock_load_suite.return_value = mock_suite

    with pytest.raises(ValueError, match="unknown task_id"):
        run_one(
            task_id="NONEXISTENT",
            variant_id="P0",
            model_name="mock:default",
            suite_path="suite.yaml",
            output_dir=str(tmp_path),
        )


@patch("vsevals.runner.load_suite")
def test_run_one_unknown_variant(mock_load_suite, tmp_path):
    task = _make_task()
    mock_suite = MagicMock()
    mock_suite.task_map = {task.id: task}
    mock_suite.variant_map = {}
    mock_suite.suite.pytest_docker_image = None
    mock_suite.suite.pytest_docker_workdir = None
    mock_load_suite.return_value = mock_suite

    with pytest.raises(ValueError, match="unknown variant_id"):
        run_one(
            task_id="BUG01",
            variant_id="NONEXISTENT",
            model_name="mock:default",
            suite_path="suite.yaml",
            output_dir=str(tmp_path),
        )


# ============================================================================
# 19. main() - CLI entry point
# ============================================================================


@patch("vsevals.runner.run_one")
def test_main_calls_run_one(mock_run_one):
    mock_result = MagicMock()
    mock_result.run_id = "test-run"
    mock_result.status = "ok"
    mock_result.score = None
    mock_result.error = None
    mock_run_one.return_value = mock_result

    test_args = [
        "vseval",
        "--task", "BUG01",
        "--model", "mock:default",
        "--suite", "suite.yaml",
        "--output-dir", "/tmp/output",
        "--variant", "P0",
    ]
    with patch("sys.argv", test_args):
        main()
    mock_run_one.assert_called_once()
    call_kwargs = mock_run_one.call_args[1]
    assert call_kwargs["task_id"] == "BUG01"
    assert call_kwargs["model_name"] == "mock:default"
    assert call_kwargs["variant_id"] == "P0"


# ============================================================================
# Additional edge case tests
# ============================================================================


def test_dedup_snippets_preserves_order():
    s1 = _make_snippet(id="s1", canonical_key="a")
    s2 = _make_snippet(id="s2", canonical_key="b")
    s3 = _make_snippet(id="s3", canonical_key="c")
    result = _dedup_snippets([s3, s2, s1])
    assert [s.id for s in result] == ["s3", "s2", "s1"]


def test_classify_error_timeout_error_class():
    exc = TimeoutError("operation timed out")
    assert _classify_error(exc) == "TIMEOUT"


def test_classify_error_connection_error_class():
    class ConnectionError(Exception):
        pass
    exc = ConnectionError("connection error: unreachable")
    assert _classify_error(exc) == "NETWORK_ERROR"


def test_invoke_tool_deduplicates_snippets():
    """If fetch returns a snippet already in the list, it should not be added again."""
    mock_vs = MagicMock()
    existing = _make_snippet(id="s1", canonical_key="k1")
    snippets: list[RetrievedSnippet] = [existing]
    tool_traces: list[ToolTrace] = []
    roundtrip_count = {"n": 0}
    # Fetch returns the same snippet
    dup_snippet = _make_snippet(id="s1_dup", canonical_key="k1")

    _invoke_tool(
        name="voltsnip.get_by_canonical_keys",
        args={"canonical_keys": ["k1"]},
        voltsnip=mock_vs,
        snippets=snippets,
        tool_traces=tool_traces,
        roundtrip_count=roundtrip_count,
        max_roundtrips=4,
        fetch=lambda: [dup_snippet],
    )
    # Should still be 1, not 2
    assert len(snippets) == 1


@patch("vsevals.runner._write_artifacts")
@patch("vsevals.runner._write_raw_llm_artifacts")
@patch("vsevals.runner.score_one")
@patch("vsevals.runner.call_llm")
@patch("vsevals.runner.build_prompt")
@patch("vsevals.runner._read_target_file", return_value=None)
@patch("vsevals.runner._resolve_repo_root", return_value=None)
@patch("vsevals.runner._make_client", return_value=None)
@patch("vsevals.runner._load_provider_keys", return_value={})
@patch("vsevals.runner._make_artifact_paths")
@patch("vsevals.runner.load_suite")
def test_run_one_skip_scoring(
    mock_load_suite,
    mock_artifact_paths,
    mock_load_keys,
    mock_make_client,
    mock_resolve_root,
    mock_read_target,
    mock_build_prompt,
    mock_call_llm,
    mock_score_one,
    mock_write_raw,
    mock_write_artifacts,
    tmp_path,
):
    task = _make_task()
    variant = _make_variant()
    mock_suite = MagicMock()
    mock_suite.task_map = {task.id: task}
    mock_suite.variant_map = {variant.id: variant}
    mock_suite.suite.pytest_docker_image = None
    mock_suite.suite.pytest_docker_workdir = None
    mock_suite.suite.default_repo_root = None
    mock_load_suite.return_value = mock_suite

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    mock_artifact_paths.return_value = RunArtifactPaths(
        run_dir=str(run_dir),
        full_dump_json=str(run_dir / "full_dump.json"),
        summary_dump_json=str(run_dir / "summary.json"),
        code_output=str(run_dir / "code.txt"),
        comments_output=str(run_dir / "comments.txt"),
    )

    mock_build_prompt.return_value = _make_prompt_bundle()
    mock_call_llm.return_value = _make_llm_result(code="def fix(): return 42")

    result = run_one(
        task_id="BUG01",
        variant_id="P0",
        model_name="mock:default",
        suite_path="suite.yaml",
        output_dir=str(tmp_path),
        cfg=RunConfig(skip_scoring=True),
    )
    assert result.status == "ok"
    mock_score_one.assert_not_called()
    assert result.score is None


def test_merge_tool_snippets_with_single_key_args():
    """Test _merge_tool_snippets handles single-key args (canonical_key and key)."""
    mock_vs = MagicMock()
    fetched = [_make_snippet(id="s1", canonical_key="k1")]
    mock_vs.get_by_canonical_keys.return_value = fetched
    snippets: list[RetrievedSnippet] = []
    traces = [
        ToolTrace(
            roundtrip=1,
            tool_name="get_snippet_by_canonical_key",
            tool_args={"canonical_key": "k1"},
        ),
    ]
    _merge_tool_snippets(traces, snippets, voltsnip=mock_vs, cfg=_make_run_config(), task=_make_task())
    assert len(snippets) == 1


def test_write_artifacts_prompt_json_created(tmp_path):
    rr = _make_run_result(tmp_path)
    _write_artifacts(run_result=rr, score=None)
    prompt_file = Path(rr.artifacts.run_dir) / "prompt.json"
    assert prompt_file.exists()
    prompt_data = json.loads(prompt_file.read_text())
    assert "system" in prompt_data
    assert "user" in prompt_data


def test_write_artifacts_with_prompt_after_tools(tmp_path):
    rr = _make_run_result(tmp_path)
    rr.prompt_after_tools = PromptBundle(
        system_prompt="updated system",
        user_prompt="updated user",
        context_surface="system",
    )
    _write_artifacts(run_result=rr, score=None)
    prompt_file = Path(rr.artifacts.run_dir) / "prompt.json"
    prompt_data = json.loads(prompt_file.read_text())
    assert "system_after_tools" in prompt_data
    assert prompt_data["system_after_tools"] == "updated system"


def test_container_file_path_nested_dirs():
    result = _container_file_path(workdir="/workspace", target_file="a/b/c/d.py")
    assert result == "/workspace/a/b/c/d.py"


@pytest.mark.parametrize(
    "hypothesis",
    ["P0", "P1", "P2", "P3", "P4", "P5", "P6"],
)
@patch("vsevals.runner.run_one")
def test_run_hypothesis_all_valid_hypotheses(mock_run_one, hypothesis, tmp_path):
    mock_run_one.return_value = MagicMock(spec=RunResult)
    run_hypothesis(
        hypothesis=hypothesis,
        task_id="BUG01",
        model_name="mock:default",
        suite_path="suite.yaml",
        output_dir=str(tmp_path),
    )
    mock_run_one.assert_called_once()
    assert mock_run_one.call_args[1]["variant_id"] == hypothesis


def test_empty_llm_result_token_usage():
    r = _empty_llm_result()
    assert r.token_usage.prompt_tokens is None
    assert r.token_usage.completion_tokens is None
    assert r.token_usage.total_tokens is None


def test_make_artifact_paths_idempotent_on_existing_root(tmp_path):
    """Calling _make_artifact_paths twice should not fail even if root exists."""
    output_root = str(tmp_path / "output")
    _make_artifact_paths(output_root=output_root, task_id="BUG01", variant_id="P0", model_name="mock:default")
    result2 = _make_artifact_paths(output_root=output_root, task_id="BUG01", variant_id="P0", model_name="mock:default")
    assert Path(result2.run_dir).exists()


def test_classify_error_scoring_error():
    """Verify scoring errors are not mis-classified (they currently fall to UNKNOWN_ERROR
    since _classify_error does not have a dedicated SCORING_ERROR branch -- checking
    that behavior is stable)."""
    exc = Exception("scorer internal failure")
    # This does not match any specific patterns, so UNKNOWN_ERROR
    assert _classify_error(exc) == "UNKNOWN_ERROR"


def test_load_provider_keys_dotenv_merges(monkeypatch):
    """Verify that dotenv keys are merged into the result."""
    cfg = _make_run_config(api_key=None, provider_api_keys={})
    with patch.dict(os.environ, {}, clear=True):
        with patch("vsevals.runner._load_dotenv_keys", return_value={"openai": "dotenv-key"}):
            keys = _load_provider_keys(cfg)
    assert keys["openai"] == "dotenv-key"


def test_parse_provider_whitespace_handling():
    """Provider and model_id should be stripped."""
    provider, model_id = _parse_provider("  anthropic : claude-haiku-4-5  ")
    assert provider == "anthropic"
    assert model_id == "claude-haiku-4-5"


def test_read_target_file_absolute_target(tmp_path):
    """When target_file is absolute, repo_root should be ignored."""
    target = tmp_path / "absolute_target.py"
    target.write_text("absolute content", encoding="utf-8")
    result = _read_target_file(
        repo_root=Path("/nonexistent"),
        target_file=str(target),
        suite_path="/tmp/suite.yaml",
    )
    assert result == "absolute content"


# ============================================================================
# 20. Dynamic run_p0 .. run_p6 functions
# ============================================================================


@pytest.mark.parametrize("variant_id", ["p0", "p1", "p2", "p3", "p4", "p5", "p6"])
def test_dynamic_run_pN_exists_in_globals(variant_id):
    """Verify that run_p0 through run_p6 are created in the runner module globals."""
    import vsevals.runner as runner_mod
    func_name = f"run_{variant_id}"
    assert hasattr(runner_mod, func_name), f"{func_name} not found in runner module"
    fn = getattr(runner_mod, func_name)
    assert callable(fn)
    assert fn.__name__ == func_name


@pytest.mark.parametrize("variant_id", ["p0", "p3", "p6"])
@patch("vsevals.runner.run_one")
def test_dynamic_run_pN_delegates_to_run_one(mock_run_one, variant_id):
    """run_p0..p6 should delegate to run_one with the correct variant_id."""
    import vsevals.runner as runner_mod
    mock_run_one.return_value = MagicMock()
    fn = getattr(runner_mod, f"run_{variant_id}")
    fn(task_id="BUG01", model_name="mock:default", suite_path="suite.yaml", output_dir="/tmp")
    mock_run_one.assert_called_once()
    assert mock_run_one.call_args[1]["variant_id"] == variant_id.upper()


# ============================================================================
# 21. Usecase docker config overrides in run_one
# ============================================================================


@patch("vsevals.runner._write_artifacts")
@patch("vsevals.runner._write_raw_llm_artifacts")
@patch("vsevals.runner.call_llm")
@patch("vsevals.runner.build_prompt")
@patch("vsevals.runner._read_target_file", return_value=None)
@patch("vsevals.runner._resolve_repo_root", return_value=None)
@patch("vsevals.runner._make_client", return_value=None)
@patch("vsevals.runner._load_provider_keys", return_value={})
@patch("vsevals.runner._make_artifact_paths")
@patch("vsevals.runner.load_suite")
def test_run_one_docker_image_override_from_suite(
    mock_load_suite,
    mock_artifact_paths,
    mock_load_keys,
    mock_make_client,
    mock_resolve_root,
    mock_read_target,
    mock_build_prompt,
    mock_call_llm,
    mock_write_raw,
    mock_write_artifacts,
    tmp_path,
):
    """When suite.pytest_docker_image is set and RunConfig has the default,
    the suite value should override."""
    task = _make_task()
    variant = _make_variant()
    mock_suite = MagicMock()
    mock_suite.task_map = {task.id: task}
    mock_suite.variant_map = {variant.id: variant}
    mock_suite.suite.pytest_docker_image = "custom-image:v2"
    mock_suite.suite.pytest_docker_workdir = "/custom/workdir"
    mock_suite.suite.default_repo_root = None
    mock_load_suite.return_value = mock_suite

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    mock_artifact_paths.return_value = RunArtifactPaths(
        run_dir=str(run_dir),
        full_dump_json=str(run_dir / "full_dump.json"),
        summary_dump_json=str(run_dir / "summary.json"),
        code_output=str(run_dir / "code.txt"),
        comments_output=str(run_dir / "comments.txt"),
    )
    mock_build_prompt.return_value = _make_prompt_bundle()
    mock_call_llm.return_value = _make_llm_result(code="def fix(): return 42")

    # Use default RunConfig (image="moltsnip-pytest:latest", workdir="/workspace")
    result = run_one(
        task_id="BUG01",
        variant_id="P0",
        model_name="mock:default",
        suite_path="suite.yaml",
        output_dir=str(tmp_path),
        cfg=RunConfig(skip_scoring=True),
    )
    assert result.status == "ok"


@patch("vsevals.runner._write_artifacts")
@patch("vsevals.runner._write_raw_llm_artifacts")
@patch("vsevals.runner.call_llm")
@patch("vsevals.runner.build_prompt")
@patch("vsevals.runner._read_target_file", return_value=None)
@patch("vsevals.runner._resolve_repo_root", return_value=None)
@patch("vsevals.runner._make_client", return_value=None)
@patch("vsevals.runner._load_provider_keys", return_value={})
@patch("vsevals.runner._make_artifact_paths")
@patch("vsevals.runner.load_suite")
def test_run_one_docker_image_not_overridden_when_explicit(
    mock_load_suite,
    mock_artifact_paths,
    mock_load_keys,
    mock_make_client,
    mock_resolve_root,
    mock_read_target,
    mock_build_prompt,
    mock_call_llm,
    mock_write_raw,
    mock_write_artifacts,
    tmp_path,
):
    """When RunConfig has a non-default pytest_docker_image, suite value should NOT override."""
    task = _make_task()
    variant = _make_variant()
    mock_suite = MagicMock()
    mock_suite.task_map = {task.id: task}
    mock_suite.variant_map = {variant.id: variant}
    mock_suite.suite.pytest_docker_image = "suite-image:v1"
    mock_suite.suite.pytest_docker_workdir = "/suite/workdir"
    mock_suite.suite.default_repo_root = None
    mock_load_suite.return_value = mock_suite

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    mock_artifact_paths.return_value = RunArtifactPaths(
        run_dir=str(run_dir),
        full_dump_json=str(run_dir / "full_dump.json"),
        summary_dump_json=str(run_dir / "summary.json"),
        code_output=str(run_dir / "code.txt"),
        comments_output=str(run_dir / "comments.txt"),
    )
    mock_build_prompt.return_value = _make_prompt_bundle()
    mock_call_llm.return_value = _make_llm_result(code="def fix(): return 42")

    # Use explicit non-default docker image in RunConfig
    result = run_one(
        task_id="BUG01",
        variant_id="P0",
        model_name="mock:default",
        suite_path="suite.yaml",
        output_dir=str(tmp_path),
        cfg=RunConfig(skip_scoring=True, pytest_docker_image="explicit:v3"),
    )
    assert result.status == "ok"


# ============================================================================
# 22. Memory retrieval path in run_one
# ============================================================================


@patch("vsevals.runner._write_artifacts")
@patch("vsevals.runner._write_raw_llm_artifacts")
@patch("vsevals.runner.call_llm")
@patch("vsevals.runner.build_prompt")
@patch("vsevals.runner._read_target_file", return_value=None)
@patch("vsevals.runner._resolve_repo_root", return_value=None)
@patch("vsevals.runner._retrieve_snippets")
@patch("vsevals.runner._make_client")
@patch("vsevals.runner._load_provider_keys", return_value={})
@patch("vsevals.runner._make_artifact_paths")
@patch("vsevals.runner.load_suite")
def test_run_one_memory_enabled_retrieves_snippets(
    mock_load_suite,
    mock_artifact_paths,
    mock_load_keys,
    mock_make_client,
    mock_retrieve_snippets,
    mock_resolve_root,
    mock_read_target,
    mock_build_prompt,
    mock_call_llm,
    mock_write_raw,
    mock_write_artifacts,
    tmp_path,
):
    """When variant.memory_enabled=True, _retrieve_snippets should be called."""
    task = _make_task(required_snippets=["key1"])
    # P3-like: memory_enabled=True, direct mode, no tools
    variant = _make_variant(id="P3", mode="direct", memory_enabled=True, retrieval_mode="injected")
    mock_suite = MagicMock()
    mock_suite.task_map = {task.id: task}
    mock_suite.variant_map = {variant.id: variant}
    mock_suite.suite.pytest_docker_image = None
    mock_suite.suite.pytest_docker_workdir = None
    mock_suite.suite.default_repo_root = None
    mock_load_suite.return_value = mock_suite

    mock_make_client.return_value = MagicMock()  # non-None client
    seed = [_make_snippet(id="s1", canonical_key="key1")]
    mock_retrieve_snippets.return_value = seed

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    mock_artifact_paths.return_value = RunArtifactPaths(
        run_dir=str(run_dir),
        full_dump_json=str(run_dir / "full_dump.json"),
        summary_dump_json=str(run_dir / "summary.json"),
        code_output=str(run_dir / "code.txt"),
        comments_output=str(run_dir / "comments.txt"),
    )
    mock_build_prompt.return_value = _make_prompt_bundle()
    mock_call_llm.return_value = _make_llm_result(code="def fix(): return 42")

    result = run_one(
        task_id="BUG01",
        variant_id="P3",
        model_name="mock:default",
        suite_path="suite.yaml",
        output_dir=str(tmp_path),
        cfg=RunConfig(skip_scoring=True),
    )
    assert result.status == "ok"
    mock_retrieve_snippets.assert_called_once()
    assert len(result.retrieved_snippets) == 1


@patch("vsevals.runner._write_artifacts")
@patch("vsevals.runner._write_raw_llm_artifacts")
@patch("vsevals.runner.call_llm")
@patch("vsevals.runner.build_prompt")
@patch("vsevals.runner._read_target_file", return_value=None)
@patch("vsevals.runner._resolve_repo_root", return_value=None)
@patch("vsevals.runner._retrieve_snippets")
@patch("vsevals.runner._make_client", return_value=None)
@patch("vsevals.runner._load_provider_keys", return_value={})
@patch("vsevals.runner._make_artifact_paths")
@patch("vsevals.runner.load_suite")
def test_run_one_memory_disabled_skips_retrieval(
    mock_load_suite,
    mock_artifact_paths,
    mock_load_keys,
    mock_make_client,
    mock_retrieve_snippets,
    mock_resolve_root,
    mock_read_target,
    mock_build_prompt,
    mock_call_llm,
    mock_write_raw,
    mock_write_artifacts,
    tmp_path,
):
    """When variant.memory_enabled=False, _retrieve_snippets should NOT be called."""
    task = _make_task()
    variant = _make_variant(id="P0", mode="direct", memory_enabled=False)
    mock_suite = MagicMock()
    mock_suite.task_map = {task.id: task}
    mock_suite.variant_map = {variant.id: variant}
    mock_suite.suite.pytest_docker_image = None
    mock_suite.suite.pytest_docker_workdir = None
    mock_suite.suite.default_repo_root = None
    mock_load_suite.return_value = mock_suite

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    mock_artifact_paths.return_value = RunArtifactPaths(
        run_dir=str(run_dir),
        full_dump_json=str(run_dir / "full_dump.json"),
        summary_dump_json=str(run_dir / "summary.json"),
        code_output=str(run_dir / "code.txt"),
        comments_output=str(run_dir / "comments.txt"),
    )
    mock_build_prompt.return_value = _make_prompt_bundle()
    mock_call_llm.return_value = _make_llm_result(code="def fix(): return 42")

    result = run_one(
        task_id="BUG01",
        variant_id="P0",
        model_name="mock:default",
        suite_path="suite.yaml",
        output_dir=str(tmp_path),
        cfg=RunConfig(skip_scoring=True),
    )
    assert result.status == "ok"
    mock_retrieve_snippets.assert_not_called()


# ============================================================================
# 23. _run_agent — claudecode provider path
# ============================================================================


@patch("vsevals.runner._merge_tool_snippets")
@patch("vsevals.runner.build_prompt")
@patch("vsevals.runner._parse_provider", return_value=("claudecode", "claude-sonnet-4-5"))
def test_run_agent_claudecode_path(mock_parse, mock_build_prompt, mock_merge):
    """_run_agent with claudecode provider calls call_claudecode and merges tool traces."""
    task = _make_task()
    variant = _make_variant(id="P5", mode="agent", tools_enabled=True)
    cfg = _make_run_config()
    mock_build_prompt.return_value = _make_prompt_bundle()
    trace1 = ToolTrace(roundtrip=1, tool_name="mcp__voltsnip__fetch")
    fake_result = _make_llm_result()
    fake_result.tool_traces = [trace1]

    with patch("vsevals.runner.voltsnip_tool_schemas", return_value=[{"name": "t1"}]):
        with patch("vsevals.providers.claudecode.call_claudecode", return_value=fake_result) as mock_cc:
            llm_result, prompt_sent, prompt_after, snippets, tool_traces = _run_agent(
                task=task, variant=variant, model_name="claudecode:claude-sonnet-4-5",
                cfg=cfg, provider_keys={}, voltsnip=MagicMock(),
                seed_snippets=[], target_file_content="code", repo_policy="policy",
                repo_root=Path("/fake"), run_dir="/tmp/run",
            )
    mock_cc.assert_called_once()
    assert llm_result is fake_result
    # tool_traces should include the one from the subprocess
    assert len(tool_traces) == 1
    assert tool_traces[0].tool_name == "mcp__voltsnip__fetch"
    mock_merge.assert_called_once()


# ============================================================================
# 24. _run_agent — codex provider path
# ============================================================================


@patch("vsevals.runner._merge_tool_snippets")
@patch("vsevals.runner.build_prompt")
@patch("vsevals.runner._parse_provider", return_value=("codex", "gpt-5.3-codex"))
def test_run_agent_codex_path(mock_parse, mock_build_prompt, mock_merge):
    """_run_agent with codex provider calls call_codex and merges tool traces."""
    task = _make_task()
    variant = _make_variant(id="P5", mode="agent", tools_enabled=True)
    cfg = _make_run_config()
    mock_build_prompt.return_value = _make_prompt_bundle()
    trace1 = ToolTrace(roundtrip=1, tool_name="mcp__voltsnip__search")
    fake_result = _make_llm_result()
    fake_result.tool_traces = [trace1]

    with patch("vsevals.runner.voltsnip_tool_schemas", return_value=[{"name": "t1"}]):
        with patch("vsevals.providers.codex.call_codex", return_value=fake_result) as mock_cx:
            llm_result, prompt_sent, prompt_after, snippets, tool_traces = _run_agent(
                task=task, variant=variant, model_name="codex:gpt-5.3-codex",
                cfg=cfg, provider_keys={}, voltsnip=MagicMock(),
                seed_snippets=[], target_file_content="code", repo_policy="policy",
                repo_root=Path("/fake"), run_dir="/tmp/run",
            )
    mock_cx.assert_called_once()
    assert llm_result is fake_result
    assert len(tool_traces) == 1
    mock_merge.assert_called_once()


# ============================================================================
# 25. _run_agent — openai + tools path
# ============================================================================


@patch("vsevals.runner.build_prompt")
@patch("vsevals.runner._parse_provider", return_value=("openai", "gpt-5-mini"))
@patch("vsevals.runner.call_llm")
def test_run_agent_openai_tools_path(mock_call_llm, mock_parse, mock_build_prompt):
    """_run_agent with openai + tools_enabled calls call_llm with tool_schemas (MCP path)."""
    task = _make_task()
    variant = _make_variant(id="P5", mode="agent", tools_enabled=True)
    cfg = _make_run_config()
    mock_build_prompt.return_value = _make_prompt_bundle()
    fake_result = _make_llm_result()
    mock_call_llm.return_value = fake_result

    with patch("vsevals.runner.voltsnip_tool_schemas", return_value=[{"name": "vs_tool"}]):
        llm_result, prompt_sent, prompt_after, snippets, tool_traces = _run_agent(
            task=task, variant=variant, model_name="openai:gpt-5-mini",
            cfg=cfg, provider_keys={"openai": "key"}, voltsnip=MagicMock(),
            seed_snippets=[], target_file_content="code", repo_policy="policy",
        )
    mock_call_llm.assert_called_once()
    call_kwargs = mock_call_llm.call_args[1]
    assert call_kwargs["tool_schemas"] == [{"name": "vs_tool"}]
    # tool_handlers should NOT be passed for openai path
    assert "tool_handlers" not in call_kwargs
    assert llm_result is fake_result
    # Empty tool_traces since openai handles tools server-side
    assert tool_traces == []


# ============================================================================
# 26. _run_agent — anthropic (default) path with tools
# ============================================================================


@patch("vsevals.runner.build_prompt")
@patch("vsevals.runner._parse_provider", return_value=("anthropic", "claude-haiku-4-5"))
@patch("vsevals.runner.call_llm")
def test_run_agent_anthropic_tools_path(mock_call_llm, mock_parse, mock_build_prompt):
    """_run_agent with anthropic + tools builds tool_handlers dict and passes to call_llm."""
    task = _make_task()
    variant = _make_variant(id="P5", mode="agent", tools_enabled=True)
    cfg = _make_run_config()
    mock_build_prompt.return_value = _make_prompt_bundle()
    fake_result = _make_llm_result()
    mock_call_llm.return_value = fake_result
    mock_vs = MagicMock()

    with patch("vsevals.runner.voltsnip_tool_schemas", return_value=[{"name": "vs_tool"}]):
        llm_result, prompt_sent, prompt_after, snippets, tool_traces = _run_agent(
            task=task, variant=variant, model_name="anthropic:claude-haiku-4-5",
            cfg=cfg, provider_keys={"anthropic": "key"}, voltsnip=mock_vs,
            seed_snippets=[], target_file_content="code", repo_policy="policy",
        )
    mock_call_llm.assert_called_once()
    call_kwargs = mock_call_llm.call_args[1]
    assert call_kwargs["tool_schemas"] == [{"name": "vs_tool"}]
    # tool_handlers should be a dict with the expected handler names
    handlers = call_kwargs["tool_handlers"]
    assert isinstance(handlers, dict)
    expected_handler_names = {
        "get_snippet_by_canonical_key",
        "get_snippet_by_key",
        "search_memory",
        "search_snippets",
        "voltsnip_fetch_by_canonical_keys",
        "voltsnip_semantic_search",
    }
    assert set(handlers.keys()) == expected_handler_names
    assert llm_result is fake_result


# ============================================================================
# 27. _run_agent — anthropic path without tools
# ============================================================================


@patch("vsevals.runner.build_prompt")
@patch("vsevals.runner._parse_provider", return_value=("anthropic", "claude-haiku-4-5"))
@patch("vsevals.runner.call_llm")
def test_run_agent_anthropic_no_tools_path(mock_call_llm, mock_parse, mock_build_prompt):
    """_run_agent with anthropic + tools_enabled=False passes tool_schemas=None, tool_handlers=None."""
    task = _make_task()
    variant = _make_variant(id="P0", mode="agent", tools_enabled=False)
    cfg = _make_run_config()
    mock_build_prompt.return_value = _make_prompt_bundle()
    fake_result = _make_llm_result()
    mock_call_llm.return_value = fake_result

    llm_result, prompt_sent, prompt_after, snippets, tool_traces = _run_agent(
        task=task, variant=variant, model_name="anthropic:claude-haiku-4-5",
        cfg=cfg, provider_keys={"anthropic": "key"}, voltsnip=None,
        seed_snippets=[], target_file_content="code", repo_policy="policy",
    )
    mock_call_llm.assert_called_once()
    call_kwargs = mock_call_llm.call_args[1]
    assert call_kwargs["tool_schemas"] is None
    assert call_kwargs["tool_handlers"] is None


# ============================================================================
# 28. _run_agent — claudecode with tools_enabled=False (no tool schemas)
# ============================================================================


@patch("vsevals.runner._merge_tool_snippets")
@patch("vsevals.runner.build_prompt")
@patch("vsevals.runner._parse_provider", return_value=("claudecode", "claude-sonnet-4-5"))
def test_run_agent_claudecode_no_tools(mock_parse, mock_build_prompt, mock_merge):
    """_run_agent with claudecode + tools_enabled=False passes tools=None to call_claudecode."""
    task = _make_task()
    variant = _make_variant(id="P0", mode="agent", tools_enabled=False)
    cfg = _make_run_config()
    mock_build_prompt.return_value = _make_prompt_bundle()
    fake_result = _make_llm_result()
    fake_result.tool_traces = []

    with patch("vsevals.providers.claudecode.call_claudecode", return_value=fake_result) as mock_cc:
        llm_result, _, _, _, _ = _run_agent(
            task=task, variant=variant, model_name="claudecode:claude-sonnet-4-5",
            cfg=cfg, provider_keys={}, voltsnip=MagicMock(),
            seed_snippets=[], target_file_content="code", repo_policy="policy",
        )
    call_kwargs = mock_cc.call_args[1]
    assert call_kwargs["tool_schemas"] is None


# ============================================================================
# 29. _run_agent — anthropic tools with voltsnip=None (no tool_handlers built)
# ============================================================================


@patch("vsevals.runner.build_prompt")
@patch("vsevals.runner._parse_provider", return_value=("anthropic", "claude-haiku-4-5"))
@patch("vsevals.runner.call_llm")
def test_run_agent_anthropic_tools_no_voltsnip(mock_call_llm, mock_parse, mock_build_prompt):
    """When voltsnip is None, tool_handlers should be None even with tools_enabled."""
    task = _make_task()
    variant = _make_variant(id="P5", mode="agent", tools_enabled=True)
    cfg = _make_run_config()
    mock_build_prompt.return_value = _make_prompt_bundle()
    mock_call_llm.return_value = _make_llm_result()

    with patch("vsevals.runner.voltsnip_tool_schemas", return_value=[{"name": "vs_tool"}]):
        _run_agent(
            task=task, variant=variant, model_name="anthropic:claude-haiku-4-5",
            cfg=cfg, provider_keys={}, voltsnip=None,
            seed_snippets=[], target_file_content="code", repo_policy="policy",
        )
    call_kwargs = mock_call_llm.call_args[1]
    assert call_kwargs["tool_handlers"] is None
    # tool_schemas should still be set
    assert call_kwargs["tool_schemas"] is not None


# ============================================================================
# 30. _run_agent — seed_snippets dedup
# ============================================================================


@patch("vsevals.runner.build_prompt")
@patch("vsevals.runner._parse_provider", return_value=("anthropic", "claude-haiku-4-5"))
@patch("vsevals.runner.call_llm")
def test_run_agent_deduplicates_seed_snippets(mock_call_llm, mock_parse, mock_build_prompt):
    """_run_agent calls _dedup_snippets on seed_snippets."""
    task = _make_task()
    variant = _make_variant(id="P0", mode="agent", tools_enabled=False)
    cfg = _make_run_config()
    mock_build_prompt.return_value = _make_prompt_bundle()
    mock_call_llm.return_value = _make_llm_result()

    s1a = _make_snippet(id="s1", canonical_key="k1", code="pass")
    s1b = _make_snippet(id="s1_dup", canonical_key="k1", code="pass")

    _, _, _, snippets, _ = _run_agent(
        task=task, variant=variant, model_name="anthropic:claude-haiku-4-5",
        cfg=cfg, provider_keys={}, voltsnip=None,
        seed_snippets=[s1a, s1b], target_file_content="code", repo_policy="policy",
    )
    # Should be deduped to 1
    assert len(snippets) == 1
    assert snippets[0].canonical_key == "k1"


# ============================================================================
# 31. _run_patch_and_test — no repo_root
# ============================================================================


def test_run_patch_and_test_no_repo_root(tmp_path):
    """No repo_root -> PytestResult(ran=False)."""
    rr = _make_run_result(tmp_path, code="def fix(): pass")
    task = _make_task()
    cfg = _make_run_config()
    result = _run_patch_and_test(run_result=rr, task=task, repo_root=None, cfg=cfg)
    assert result.ran is False
    assert "no repo_root" in result.error


# ============================================================================
# 32. _run_patch_and_test — no target_file
# ============================================================================


def test_run_patch_and_test_no_target_file(tmp_path):
    """No target_file -> PytestResult(ran=False)."""
    rr = _make_run_result(tmp_path, code="def fix(): pass")
    task = _make_task(target_file=None)
    cfg = _make_run_config()
    result = _run_patch_and_test(run_result=rr, task=task, repo_root=Path("/fake"), cfg=cfg)
    assert result.ran is False
    assert "no target_file" in result.error


# ============================================================================
# 33. _run_patch_and_test — no test_command
# ============================================================================


def test_run_patch_and_test_no_test_command(tmp_path):
    """No test_command -> PytestResult(ran=False)."""
    rr = _make_run_result(tmp_path, code="def fix(): pass")
    # task has target_file but no test_command (default is None)
    task = _make_task(target_file="src/main.py")
    cfg = _make_run_config()
    result = _run_patch_and_test(run_result=rr, task=task, repo_root=Path("/fake"), cfg=cfg)
    assert result.ran is False
    assert "no test_command" in result.error


# ============================================================================
# 34. _run_patch_and_test — empty code
# ============================================================================


def test_run_patch_and_test_empty_code(tmp_path):
    """Empty generated code -> PytestResult(ran=False)."""
    rr = _make_run_result(tmp_path, code="   ")
    task = SuiteTask(
        task=TaskVisible(
            id="BUG01", name="Test Bug", user_prompt="Fix the bug",
            target_file="src/main.py", test_command="pytest tests/",
        ),
        voltsnip=TaskVoltsnipConfig(),
        oracle=TaskOracle(),
    )
    cfg = _make_run_config()
    result = _run_patch_and_test(run_result=rr, task=task, repo_root=Path("/fake"), cfg=cfg)
    assert result.ran is False
    assert "empty" in result.error


# ============================================================================
# 35. _run_patch_and_test — apply_line_range_rewrite exception
# ============================================================================


@patch("vsevals.runner.apply_line_range_rewrite", side_effect=ValueError("bad line range"))
def test_run_patch_and_test_rewrite_exception(mock_rewrite, tmp_path):
    """apply_line_range_rewrite exception -> PytestResult(ran=False)."""
    rr = _make_run_result(tmp_path, code="def fix(): pass")
    task = SuiteTask(
        task=TaskVisible(
            id="BUG01", name="Test Bug", user_prompt="Fix the bug",
            target_file="src/main.py", test_command="pytest tests/",
        ),
        voltsnip=TaskVoltsnipConfig(),
        oracle=TaskOracle(),
    )
    cfg = _make_run_config()
    result = _run_patch_and_test(run_result=rr, task=task, repo_root=Path("/fake"), cfg=cfg)
    assert result.ran is False
    assert "could not produce patched file" in result.error
    assert "bad line range" in result.error


# ============================================================================
# 36. _run_patch_and_test — FileNotFoundError from start_test_container
# ============================================================================


@patch("vsevals.runner.cleanup_overlay")
@patch("vsevals.runner.stop_test_container")
@patch("vsevals.runner.start_test_container", side_effect=FileNotFoundError("docker"))
@patch("vsevals.runner.apply_rewrite")
@patch("vsevals.runner.materialize_overlay")
@patch("vsevals.runner.apply_line_range_rewrite", return_value="patched content")
def test_run_patch_and_test_docker_not_found(
    mock_rewrite, mock_materialize, mock_apply, mock_start, mock_stop, mock_cleanup, tmp_path
):
    """FileNotFoundError from start_test_container -> 'docker not found'."""
    rr = _make_run_result(tmp_path, code="def fix(): pass")
    task = SuiteTask(
        task=TaskVisible(
            id="BUG01", name="Test Bug", user_prompt="Fix the bug",
            target_file="src/main.py", test_command="pytest tests/",
        ),
        voltsnip=TaskVoltsnipConfig(),
        oracle=TaskOracle(),
    )
    cfg = _make_run_config()
    result = _run_patch_and_test(run_result=rr, task=task, repo_root=tmp_path, cfg=cfg)
    assert result.ran is False
    assert "docker not found" in result.error
    # finally block should still clean up overlay (container is None so stop_test_container not called)
    mock_cleanup.assert_called_once()


# ============================================================================
# 37. _run_patch_and_test — RuntimeError from start_test_container
# ============================================================================


@patch("vsevals.runner.cleanup_overlay")
@patch("vsevals.runner.stop_test_container")
@patch("vsevals.runner.start_test_container", side_effect=RuntimeError("container launch failed"))
@patch("vsevals.runner.apply_rewrite")
@patch("vsevals.runner.materialize_overlay")
@patch("vsevals.runner.apply_line_range_rewrite", return_value="patched content")
def test_run_patch_and_test_runtime_error_from_container(
    mock_rewrite, mock_materialize, mock_apply, mock_start, mock_stop, mock_cleanup, tmp_path
):
    """RuntimeError from start_test_container -> error string in PytestResult."""
    rr = _make_run_result(tmp_path, code="def fix(): pass")
    task = SuiteTask(
        task=TaskVisible(
            id="BUG01", name="Test Bug", user_prompt="Fix the bug",
            target_file="src/main.py", test_command="pytest tests/",
        ),
        voltsnip=TaskVoltsnipConfig(),
        oracle=TaskOracle(),
    )
    cfg = _make_run_config()
    result = _run_patch_and_test(run_result=rr, task=task, repo_root=tmp_path, cfg=cfg)
    assert result.ran is False
    assert "container launch failed" in result.error


# ============================================================================
# 38. _run_patch_and_test — success path
# ============================================================================


@patch("vsevals.runner.cleanup_overlay")
@patch("vsevals.runner.stop_test_container")
@patch("vsevals.runner.run_pytest_in_docker")
@patch("vsevals.runner.start_test_container", return_value="container-123")
@patch("vsevals.runner.apply_rewrite")
@patch("vsevals.runner.materialize_overlay")
@patch("vsevals.runner.apply_line_range_rewrite", return_value="patched content")
def test_run_patch_and_test_success_path(
    mock_rewrite, mock_materialize, mock_apply_rewrite,
    mock_start, mock_pytest, mock_stop, mock_cleanup, tmp_path
):
    """Success path: materialize, apply rewrite, start container, run pytest, teardown."""
    rr = _make_run_result(tmp_path, code="def fix(): pass")
    task = SuiteTask(
        task=TaskVisible(
            id="BUG01", name="Test Bug", user_prompt="Fix the bug",
            target_file="src/main.py", test_command="pytest tests/",
        ),
        voltsnip=TaskVoltsnipConfig(),
        oracle=TaskOracle(),
    )
    cfg = _make_run_config()
    expected_pytest_result = PytestResult(ran=True, passed=True, exit_code=0, stdout="1 passed")
    mock_pytest.return_value = expected_pytest_result

    result = _run_patch_and_test(run_result=rr, task=task, repo_root=tmp_path, cfg=cfg)
    assert result.ran is True
    assert result.passed is True
    mock_materialize.assert_called_once()
    mock_apply_rewrite.assert_called_once()
    mock_start.assert_called_once()
    mock_pytest.assert_called_once()
    # finally block: stop container + cleanup
    mock_stop.assert_called_once_with("container-123")
    mock_cleanup.assert_called_once()


# ============================================================================
# 39. _run_patch_and_test — generic exception in try block
# ============================================================================


@patch("vsevals.runner.cleanup_overlay")
@patch("vsevals.runner.stop_test_container")
@patch("vsevals.runner.start_test_container", return_value="container-456")
@patch("vsevals.runner.apply_rewrite", side_effect=OSError("disk full"))
@patch("vsevals.runner.materialize_overlay")
@patch("vsevals.runner.apply_line_range_rewrite", return_value="patched content")
def test_run_patch_and_test_generic_exception(
    mock_rewrite, mock_materialize, mock_apply_rewrite,
    mock_start, mock_stop, mock_cleanup, tmp_path
):
    """Generic exception during overlay/apply -> PytestResult(ran=False) + cleanup."""
    rr = _make_run_result(tmp_path, code="def fix(): pass")
    task = SuiteTask(
        task=TaskVisible(
            id="BUG01", name="Test Bug", user_prompt="Fix the bug",
            target_file="src/main.py", test_command="pytest tests/",
        ),
        voltsnip=TaskVoltsnipConfig(),
        oracle=TaskOracle(),
    )
    cfg = _make_run_config()
    result = _run_patch_and_test(run_result=rr, task=task, repo_root=tmp_path, cfg=cfg)
    assert result.ran is False
    assert "disk full" in result.error
    # Container was never started (apply_rewrite raised before start_test_container),
    # but cleanup_overlay should still be called
    mock_cleanup.assert_called_once()


# ============================================================================
# 40. _run_patch_and_test — finally block: stop_test_container called when container set
# ============================================================================


@patch("vsevals.runner.cleanup_overlay")
@patch("vsevals.runner.stop_test_container")
@patch("vsevals.runner.run_pytest_in_docker", side_effect=RuntimeError("pytest exploded"))
@patch("vsevals.runner.start_test_container", return_value="container-789")
@patch("vsevals.runner.apply_rewrite")
@patch("vsevals.runner.materialize_overlay")
@patch("vsevals.runner.apply_line_range_rewrite", return_value="patched content")
def test_run_patch_and_test_cleanup_on_pytest_failure(
    mock_rewrite, mock_materialize, mock_apply_rewrite,
    mock_start, mock_pytest, mock_stop, mock_cleanup, tmp_path
):
    """When run_pytest_in_docker raises, finally block cleans up container + overlay."""
    rr = _make_run_result(tmp_path, code="def fix(): pass")
    task = SuiteTask(
        task=TaskVisible(
            id="BUG01", name="Test Bug", user_prompt="Fix the bug",
            target_file="src/main.py", test_command="pytest tests/",
        ),
        voltsnip=TaskVoltsnipConfig(),
        oracle=TaskOracle(),
    )
    cfg = _make_run_config()
    result = _run_patch_and_test(run_result=rr, task=task, repo_root=tmp_path, cfg=cfg)
    assert result.ran is False
    assert "pytest exploded" in result.error
    # finally block should stop the container AND clean up overlay
    mock_stop.assert_called_once_with("container-789")
    mock_cleanup.assert_called_once()


# ============================================================================
# 41. _run_agent — anthropic fetch_handler callable test
# ============================================================================


@patch("vsevals.runner.build_prompt")
@patch("vsevals.runner._parse_provider", return_value=("anthropic", "claude-haiku-4-5"))
@patch("vsevals.runner.call_llm")
def test_run_agent_anthropic_fetch_handler_callable(mock_call_llm, mock_parse, mock_build_prompt):
    """Verify the fetch handler is callable and handles canonical_keys + single key args."""
    task = _make_task()
    variant = _make_variant(id="P5", mode="agent", tools_enabled=True)
    cfg = _make_run_config()
    mock_build_prompt.return_value = _make_prompt_bundle()
    mock_call_llm.return_value = _make_llm_result()
    mock_vs = MagicMock()
    mock_vs.get_by_canonical_keys.return_value = [_make_snippet(id="s1", canonical_key="k1")]

    with patch("vsevals.runner.voltsnip_tool_schemas", return_value=[{"name": "vs_tool"}]):
        _run_agent(
            task=task, variant=variant, model_name="anthropic:claude-haiku-4-5",
            cfg=cfg, provider_keys={}, voltsnip=mock_vs,
            seed_snippets=[], target_file_content="code", repo_policy="policy",
        )
    handlers = mock_call_llm.call_args[1]["tool_handlers"]
    # Call the fetch handler
    result = handlers["get_snippet_by_canonical_key"]({"canonical_keys": ["k1"]})
    assert "snippets" in result or "error" in result


# ============================================================================
# 42. _run_agent — anthropic search_handler callable test
# ============================================================================


@patch("vsevals.runner.build_prompt")
@patch("vsevals.runner._parse_provider", return_value=("anthropic", "claude-haiku-4-5"))
@patch("vsevals.runner.call_llm")
def test_run_agent_anthropic_search_handler_callable(mock_call_llm, mock_parse, mock_build_prompt):
    """Verify the search handler is callable."""
    task = _make_task()
    variant = _make_variant(id="P5", mode="agent", tools_enabled=True)
    cfg = _make_run_config()
    mock_build_prompt.return_value = _make_prompt_bundle()
    mock_call_llm.return_value = _make_llm_result()
    mock_vs = MagicMock()
    mock_vs.semantic_search.return_value = [_make_snippet(id="s2", canonical_key="k2")]

    with patch("vsevals.runner.voltsnip_tool_schemas", return_value=[{"name": "vs_tool"}]):
        _run_agent(
            task=task, variant=variant, model_name="anthropic:claude-haiku-4-5",
            cfg=cfg, provider_keys={}, voltsnip=mock_vs,
            seed_snippets=[], target_file_content="code", repo_policy="policy",
        )
    handlers = mock_call_llm.call_args[1]["tool_handlers"]
    # Call the search handler
    result = handlers["search_memory"]({"query": "metrics API"})
    assert "snippets" in result or "error" in result


# ============================================================================
# 43. _run_agent — fetch handler with single key (not list)
# ============================================================================


@patch("vsevals.runner.build_prompt")
@patch("vsevals.runner._parse_provider", return_value=("anthropic", "claude-haiku-4-5"))
@patch("vsevals.runner.call_llm")
def test_run_agent_fetch_handler_single_key_arg(mock_call_llm, mock_parse, mock_build_prompt):
    """Fetch handler should handle 'key' single-string arg appended to keys list."""
    task = _make_task()
    variant = _make_variant(id="P5", mode="agent", tools_enabled=True)
    cfg = _make_run_config()
    mock_build_prompt.return_value = _make_prompt_bundle()
    mock_call_llm.return_value = _make_llm_result()
    mock_vs = MagicMock()
    mock_vs.get_by_canonical_keys.return_value = [_make_snippet(id="s1", canonical_key="single_key")]

    with patch("vsevals.runner.voltsnip_tool_schemas", return_value=[{"name": "vs_tool"}]):
        _run_agent(
            task=task, variant=variant, model_name="anthropic:claude-haiku-4-5",
            cfg=cfg, provider_keys={}, voltsnip=mock_vs,
            seed_snippets=[], target_file_content="code", repo_policy="policy",
        )
    handlers = mock_call_llm.call_args[1]["tool_handlers"]
    # Use the "key" single-string arg form
    result = handlers["get_snippet_by_key"]({"key": "my_key"})
    assert "snippets" in result or "error" in result


# ============================================================================
# 44. _run_patch_and_test — patched file written to artifacts
# ============================================================================


@patch("vsevals.runner.cleanup_overlay")
@patch("vsevals.runner.stop_test_container")
@patch("vsevals.runner.run_pytest_in_docker", return_value=PytestResult(ran=True, passed=True, exit_code=0))
@patch("vsevals.runner.start_test_container", return_value="ctr-abc")
@patch("vsevals.runner.apply_rewrite")
@patch("vsevals.runner.materialize_overlay")
@patch("vsevals.runner.apply_line_range_rewrite", return_value="# patched\ndef fix(): pass\n")
def test_run_patch_and_test_writes_patched_file(
    mock_rewrite, mock_materialize, mock_apply_rewrite,
    mock_start, mock_pytest, mock_stop, mock_cleanup, tmp_path
):
    """The patched file should be written to run_dir for inspection."""
    rr = _make_run_result(tmp_path, code="def fix(): pass")
    task = SuiteTask(
        task=TaskVisible(
            id="BUG01", name="Test Bug", user_prompt="Fix the bug",
            target_file="src/main.py", test_command="pytest tests/",
        ),
        voltsnip=TaskVoltsnipConfig(),
        oracle=TaskOracle(),
    )
    cfg = _make_run_config()
    _run_patch_and_test(run_result=rr, task=task, repo_root=tmp_path, cfg=cfg)
    patched_path = Path(rr.artifacts.run_dir) / "patched_main.py"
    assert patched_path.exists()
    assert "# patched" in patched_path.read_text()


# ============================================================================
# 45. _run_patch_and_test — .venv copied into overlay when present
# ============================================================================


@patch("vsevals.runner.cleanup_overlay")
@patch("vsevals.runner.stop_test_container")
@patch("vsevals.runner.run_pytest_in_docker", return_value=PytestResult(ran=True, passed=True, exit_code=0))
@patch("vsevals.runner.start_test_container", return_value="ctr-venv")
@patch("vsevals.runner.apply_rewrite")
@patch("vsevals.runner.materialize_overlay")
@patch("vsevals.runner.apply_line_range_rewrite", return_value="patched content")
def test_run_patch_and_test_copies_venv(
    mock_rewrite, mock_materialize, mock_apply_rewrite,
    mock_start, mock_pytest, mock_stop, mock_cleanup, tmp_path
):
    """When repo_root/.venv exists, shutil.copytree should be called."""
    # Create a fake .venv dir in the repo root
    venv_dir = tmp_path / ".venv"
    venv_dir.mkdir()
    (venv_dir / "bin").mkdir()
    (venv_dir / "bin" / "python").write_text("#!/usr/bin/env python3")

    rr = _make_run_result(tmp_path, code="def fix(): pass")
    task = SuiteTask(
        task=TaskVisible(
            id="BUG01", name="Test Bug", user_prompt="Fix the bug",
            target_file="src/main.py", test_command="pytest tests/",
        ),
        voltsnip=TaskVoltsnipConfig(),
        oracle=TaskOracle(),
    )
    cfg = _make_run_config()

    with patch("vsevals.runner.shutil.copytree") as mock_copytree:
        _run_patch_and_test(run_result=rr, task=task, repo_root=tmp_path, cfg=cfg)
        mock_copytree.assert_called_once()
        # Verify source is the .venv dir
        src_arg = mock_copytree.call_args[0][0]
        assert ".venv" in src_arg
