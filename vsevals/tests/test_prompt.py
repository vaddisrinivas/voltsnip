"""Tests for vsevals.prompt — prompt assembly and helpers."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from vsevals.models import (
    RetrievedSnippet,
    SuccessIndicators,
    SuiteTask,
    TaskOracle,
    TaskVisible,
    TaskVoltsnipConfig,
    VariantConfig,
)
from vsevals.prompt import (
    BASE_SYSTEM_PROMPT,
    DEFAULT_REPO_POLICY,
    INLINE_AGENT_GUIDE,
    INLINE_SKILL_GUIDE,
    _dedup,
    _key_block,
    _load_static_doc,
    _normalize_prompt,
    _oracle_rows,
    _policy_block,
    _snippet_block,
    build_prompt,
)


# ---------------------------------------------------------------------------
# _dedup
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("keys,expected", [
    (["a", "b", "c"], ["a", "b", "c"]),
    (["a", "a", "b"], ["a", "b"]),
    (["a", None, "b", ""], ["a", "b"]),
    ([], []),
    ([None, None], []),
    (["  x  ", "x"], ["x"]),
])
def test_dedup(keys, expected):
    assert _dedup(keys) == expected


# ---------------------------------------------------------------------------
# _snippet_block
# ---------------------------------------------------------------------------


def test_snippet_block_empty():
    assert _snippet_block([]) == ""


def test_snippet_block_formats():
    snippets = [
        RetrievedSnippet(id="s1", canonical_key="key1", title="Title", code="print('hi')"),
    ]
    result = _snippet_block(snippets)
    assert "VoltSnip Context:" in result
    assert "Snippet 1: key1" in result
    assert "print('hi')" in result


def test_snippet_block_uses_id_when_no_key():
    snippets = [RetrievedSnippet(id="fallback-id", code="x = 1")]
    result = _snippet_block(snippets)
    assert "fallback-id" in result


# ---------------------------------------------------------------------------
# _key_block
# ---------------------------------------------------------------------------


def test_key_block_empty():
    assert _key_block([]) == ""


def test_key_block_formats():
    result = _key_block(["key1", "key2"])
    assert "Guiding Snippet Keys:" in result
    assert "- key1" in result
    assert "- key2" in result


# ---------------------------------------------------------------------------
# _policy_block
# ---------------------------------------------------------------------------


def test_policy_block_default():
    result = _policy_block(None)
    assert "Repository Policy:" in result


def test_policy_block_custom():
    result = _policy_block("Custom policy text")
    assert "Custom policy text" in result


# ---------------------------------------------------------------------------
# _normalize_prompt
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("input_text,contains", [
    ("Fix the bug", "Fix the bug"),
    ("", "Apply the required fix"),
    ("   ", "Apply the required fix"),
    ("Work in `src/main.py`.\nFix it", "Fix it"),
    ("Fix only `BUG_01` in `file.py`:\ndetail", "Apply only the requested bug fix"),
])
def test_normalize_prompt(input_text, contains):
    result = _normalize_prompt(input_text)
    assert contains in result


def test_normalize_prompt_collapses_blank_lines():
    text = "line1\n\n\n\nline2"
    result = _normalize_prompt(text)
    # Should not have more than one consecutive blank line
    assert "\n\n\n" not in result


# ---------------------------------------------------------------------------
# _oracle_rows
# ---------------------------------------------------------------------------


def test_oracle_rows_all_sections():
    task = SuiteTask(
        task=TaskVisible(id="t1", name="t", user_prompt="fix"),
        oracle=TaskOracle(
            hidden_requirements=["req1"],
            success_indicators=SuccessIndicators(correctness=["correct"]),
            failure_modes=["fail1"],
            evaluation_criteria=["crit1"],
        ),
    )
    rows = _oracle_rows(task)
    assert any("Hidden requirements:" in r for r in rows)
    assert any("Success indicators:" in r for r in rows)
    assert any("Failure modes to avoid:" in r for r in rows)
    assert any("Evaluation criteria:" in r for r in rows)


def test_oracle_rows_empty():
    task = SuiteTask(
        task=TaskVisible(id="t1", name="t", user_prompt="fix"),
        oracle=TaskOracle(),
    )
    assert _oracle_rows(task) == []


# ---------------------------------------------------------------------------
# build_prompt surface dispatch
# ---------------------------------------------------------------------------


def _make_task(**overrides):
    defaults = dict(id="BUG01", name="Test", user_prompt="Fix it")
    defaults.update(overrides)
    return SuiteTask(
        task=TaskVisible(**defaults),
        voltsnip=TaskVoltsnipConfig(required_snippets=["k1"]),
        oracle=TaskOracle(hidden_requirements=["use correct API"]),
    )


def _make_variant(surface, **overrides):
    is_tools = surface in ("tools_only", "skills_md_no_keys", "agents_md_no_keys", "skills_agents_md_no_keys")
    defaults = dict(
        id="V",
        mode="agent" if is_tools else "direct",
        memory_enabled=surface not in ("user",),
        tools_enabled=is_tools,
        retrieval_mode="agent_decides" if is_tools else ("injected" if surface == "system" else "none"),
        instruction_mode="none",
        context_surface=surface,
    )
    defaults.update(overrides)
    return VariantConfig(**defaults)


def test_build_prompt_user_surface():
    task = _make_task()
    variant = _make_variant("user")
    bundle = build_prompt(
        task=task, variant=variant, retrieved_snippets=[], repo_policy_text=None, target_file_content=None,
    )
    assert BASE_SYSTEM_PROMPT in bundle.system_prompt
    assert "Task ID: BUG01" in bundle.user_prompt
    assert bundle.context_surface == "user"


def test_build_prompt_system_surface():
    task = _make_task()
    variant = _make_variant("system")
    snippets = [RetrievedSnippet(id="s1", canonical_key="k1", title="T", code="code")]
    bundle = build_prompt(
        task=task, variant=variant, retrieved_snippets=snippets, repo_policy_text="policy", target_file_content=None,
    )
    assert "VoltSnip Context:" in bundle.system_prompt
    assert bundle.injected_repo_policy is True


def test_build_prompt_tools_only_surface():
    task = _make_task()
    variant = _make_variant("tools_only")
    bundle = build_prompt(
        task=task, variant=variant, retrieved_snippets=[], repo_policy_text=None, target_file_content=None,
    )
    assert "Tool access is enabled" in bundle.system_prompt
    assert bundle.sidecar_files == {}


@patch("vsevals.prompt._load_static_doc", return_value="mock doc")
def test_build_prompt_skills_md_no_keys(mock_load):
    task = _make_task()
    variant = _make_variant("skills_md_no_keys")
    bundle = build_prompt(
        task=task, variant=variant, retrieved_snippets=[], repo_policy_text=None, target_file_content=None,
    )
    assert "SKILL.md" in bundle.sidecar_files
    assert "CLAUDE.md" in bundle.sidecar_files


@patch("vsevals.prompt._load_static_doc", return_value="mock doc")
def test_build_prompt_agents_md_no_keys(mock_load):
    task = _make_task()
    variant = _make_variant("agents_md_no_keys")
    bundle = build_prompt(
        task=task, variant=variant, retrieved_snippets=[], repo_policy_text=None, target_file_content=None,
    )
    assert "AGENTS.md" in bundle.sidecar_files
    assert "CLAUDE.md" in bundle.sidecar_files
    assert "SKILL.md" not in bundle.sidecar_files


@patch("vsevals.prompt._load_static_doc", return_value="mock doc")
def test_build_prompt_skills_agents_md_no_keys(mock_load):
    task = _make_task()
    variant = _make_variant("skills_agents_md_no_keys")
    bundle = build_prompt(
        task=task, variant=variant, retrieved_snippets=[], repo_policy_text=None, target_file_content=None,
    )
    assert "SKILL.md" in bundle.sidecar_files
    assert "AGENTS.md" in bundle.sidecar_files


def test_build_prompt_invalid_surface():
    task = _make_task()
    variant = VariantConfig(
        id="bad", mode="direct", memory_enabled=False, tools_enabled=False,
        retrieval_mode="none", instruction_mode="none", context_surface="user",
    )
    # Monkeypatch a bad surface to bypass pydantic validation
    object.__setattr__(variant, "context_surface", "invalid_surface")
    with pytest.raises(ValueError, match="unsupported context_surface"):
        build_prompt(
            task=task, variant=variant, retrieved_snippets=[], repo_policy_text=None, target_file_content=None,
        )


def test_build_prompt_includes_target_file_content():
    task = _make_task(target_file="src/main.py", line_start=5, line_end=10)
    variant = _make_variant("user")
    bundle = build_prompt(
        task=task, variant=variant, retrieved_snippets=[], repo_policy_text=None,
        target_file_content="def hello(): pass",
    )
    assert "Target File Content" in bundle.user_prompt
    assert "def hello(): pass" in bundle.user_prompt


def test_build_prompt_with_oracle():
    task = _make_task()
    variant = _make_variant("user", include_oracle=True)
    task.oracle = TaskOracle(hidden_requirements=["must use API"], failure_modes=["crash"])
    bundle = build_prompt(
        task=task, variant=variant, retrieved_snippets=[], repo_policy_text=None, target_file_content=None,
    )
    assert "Acceptance Criteria" in bundle.user_prompt


def test_build_prompt_explicit_instruction():
    task = _make_task()
    variant = _make_variant("system", instruction_mode="explicit")
    snippets = [RetrievedSnippet(id="s1", canonical_key="k1", code="x")]
    bundle = build_prompt(
        task=task, variant=variant, retrieved_snippets=snippets, repo_policy_text=None, target_file_content=None,
    )
    assert "Execution Instruction:" in bundle.user_prompt


def test_build_prompt_expected_output_withheld_for_none_retrieval():
    task = _make_task(expected_output="emit('metric')")
    variant = _make_variant("user", retrieval_mode="none")
    bundle = build_prompt(
        task=task, variant=variant, retrieved_snippets=[], repo_policy_text=None, target_file_content=None,
    )
    assert "emit('metric')" not in bundle.user_prompt


def test_build_prompt_expected_output_included_for_injected():
    task = _make_task(expected_output="emit('metric')")
    variant = _make_variant("system", retrieval_mode="injected")
    bundle = build_prompt(
        task=task, variant=variant, retrieved_snippets=[], repo_policy_text=None, target_file_content=None,
    )
    assert "emit('metric')" in bundle.user_prompt


# ---------------------------------------------------------------------------
# build_prompt — tool budget
# ---------------------------------------------------------------------------


def test_build_prompt_tool_budget():
    """Variant with tools shows tool budget line."""
    task = _make_task()
    variant = _make_variant("skills_md_no_keys", max_tool_roundtrips=12)
    bundle = build_prompt(
        task=task, variant=variant, retrieved_snippets=[], repo_policy_text=None, target_file_content=None,
    )
    assert "Maximum tool roundtrips: 12" in bundle.user_prompt


# ---------------------------------------------------------------------------
# _normalize_prompt — additional edge cases
# ---------------------------------------------------------------------------


def test_normalize_prompt_empty_returns_default():
    result = _normalize_prompt("")
    assert result == "Apply the required fix using target metadata and context."


def test_normalize_prompt_strips_work_in():
    text = "Work in `src/main.py`.\nActual instruction here"
    result = _normalize_prompt(text)
    assert "Work in" not in result
    assert "Actual instruction here" in result


def test_normalize_prompt_collapses_multiple_blank_lines():
    text = "line1\n\n\n\n\nline2"
    result = _normalize_prompt(text)
    assert "\n\n\n" not in result
    assert "line1" in result
    assert "line2" in result


# ---------------------------------------------------------------------------
# _load_static_doc
# ---------------------------------------------------------------------------


def test_load_static_doc_fallback(tmp_path):
    """Returns fallback when file doesn't exist."""
    nonexistent = tmp_path / "nonexistent.md"
    result = _load_static_doc(nonexistent, "fallback content")
    assert result == "fallback content"


def test_load_static_doc_empty_file(tmp_path):
    """Returns fallback when file is empty."""
    empty_file = tmp_path / "empty.md"
    empty_file.write_text("")
    result = _load_static_doc(empty_file, "fallback content")
    assert result == "fallback content"


def test_load_static_doc_with_content(tmp_path):
    """Returns file content when file exists and has content."""
    doc_file = tmp_path / "doc.md"
    doc_file.write_text("# Real Doc Content\nSome guidance.")
    result = _load_static_doc(doc_file, "fallback")
    assert "Real Doc Content" in result


# ---------------------------------------------------------------------------
# _snippet_block / _key_block — additional coverage
# ---------------------------------------------------------------------------


def test_snippet_block_with_multiple_snippets():
    snippets = [
        RetrievedSnippet(id="s1", canonical_key="key1", title="First", code="x = 1"),
        RetrievedSnippet(id="s2", canonical_key="key2", title="Second", code="y = 2"),
    ]
    result = _snippet_block(snippets)
    assert "Snippet 1: key1" in result
    assert "Snippet 2: key2" in result
    assert "x = 1" in result
    assert "y = 2" in result


def test_key_block_with_keys():
    result = _key_block(["alpha", "beta", "gamma"])
    assert "Guiding Snippet Keys:" in result
    assert "- alpha" in result
    assert "- beta" in result
    assert "- gamma" in result


# ---------------------------------------------------------------------------
# _policy_block — default behavior
# ---------------------------------------------------------------------------


def test_policy_block_uses_default_when_none():
    result = _policy_block(None)
    assert DEFAULT_REPO_POLICY.strip().splitlines()[0].lstrip("- ") in result


# ---------------------------------------------------------------------------
# _dedup — additional
# ---------------------------------------------------------------------------


def test_dedup_strips_whitespace_and_deduplicates():
    assert _dedup(["  x  ", "x", " y ", "y"]) == ["x", "y"]


# ---------------------------------------------------------------------------
# build_prompt — explicit instruction_mode with visible keys
# ---------------------------------------------------------------------------


def test_build_prompt_explicit_instruction_mode_with_keys():
    """Explicit instruction mode adds MUST-check and MUST-retrieve lines when keys visible."""
    task = _make_task()
    variant = _make_variant("system", instruction_mode="explicit")
    snippets = [RetrievedSnippet(id="s1", canonical_key="k1", code="code")]
    bundle = build_prompt(
        task=task, variant=variant, retrieved_snippets=snippets, repo_policy_text=None, target_file_content=None,
    )
    assert "Guideline Requirement:" in bundle.user_prompt
    assert "MUST check and apply" in bundle.user_prompt
    assert "Execution Instruction:" in bundle.user_prompt


def test_build_prompt_explicit_no_keys():
    """Explicit instruction mode without visible keys uses different wording."""
    task = _make_task()
    variant = _make_variant("tools_only", instruction_mode="explicit")
    bundle = build_prompt(
        task=task, variant=variant, retrieved_snippets=[], repo_policy_text=None, target_file_content=None,
    )
    assert "Execution Instruction:" in bundle.user_prompt
    assert "satisfy the acceptance criteria" in bundle.user_prompt
