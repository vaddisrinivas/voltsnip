"""Tests for vsevals.providers — _parse_payload, _safe_response_json, _int_or_none."""

from __future__ import annotations

import json

import pytest

from vsevals.providers import _int_or_none, _parse_payload, _safe_response_json


# ---------------------------------------------------------------------------
# _parse_payload — structured mode
# ---------------------------------------------------------------------------


def test_parse_payload_valid_json():
    text = '{"code": "def f(): pass", "comments": "ok"}'
    result, fallback = _parse_payload(text, structured=True)
    assert result["code"] == "def f(): pass"
    assert fallback is False


def test_parse_payload_with_markdown_fence():
    text = '```json\n{"code": "x = 1", "comments": ""}\n```'
    result, fallback = _parse_payload(text, structured=True)
    assert result["code"] == "x = 1"
    assert fallback is False


def test_parse_payload_embedded_json():
    text = 'Here is the answer: {"code": "return 42", "comments": "fixed"} done.'
    result, fallback = _parse_payload(text, structured=True)
    assert result["code"] == "return 42"
    assert fallback is False


def test_parse_payload_empty_structured():
    result, fallback = _parse_payload("", structured=True)
    assert result["code"] == ""
    assert fallback is True


def test_parse_payload_no_code_key():
    text = '{"result": "no code key here"}'
    result, fallback = _parse_payload(text, structured=True)
    # Should scan past this block and return empty
    assert result["code"] == ""
    assert fallback is True


def test_parse_payload_unstructured():
    text = "just raw text output"
    result, fallback = _parse_payload(text, structured=False)
    assert result["code"] == text
    assert fallback is False


def test_parse_payload_multiple_json_blocks():
    text = '{"status": "ok"} and then {"code": "x = 1", "comments": ""}'
    result, fallback = _parse_payload(text, structured=True)
    assert result["code"] == "x = 1"
    assert fallback is False


def test_parse_payload_nested_braces():
    inner = '{"code": "d = {\\"a\\": 1}", "comments": ""}'
    result, fallback = _parse_payload(inner, structured=True)
    assert "code" in result
    assert fallback is False


# ---------------------------------------------------------------------------
# _safe_response_json
# ---------------------------------------------------------------------------


def test_safe_response_json_pydantic_like():
    class FakeResp:
        def model_dump_json(self):
            return '{"key": "value"}'

    result = _safe_response_json(FakeResp())
    assert '"key"' in result


def test_safe_response_json_dict_like():
    class FakeResp:
        def __init__(self):
            self.status = 200
            self.data = "test"

    result = _safe_response_json(FakeResp())
    parsed = json.loads(result)
    assert parsed["status"] == 200


def test_safe_response_json_fallback_str():
    class FakeResp:
        def __init__(self):
            # vars() will raise
            pass
        def __repr__(self):
            return "FakeResp()"

    result = _safe_response_json(FakeResp())
    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# _int_or_none
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("val,expected", [
    (None, None),
    ("", None),
    (False, None),
    (0, None),
    (1, 1),
    (42, 42),
    ("10", 10),
    (-1, None),  # negative returns None
    ("bad", None),
])
def test_int_or_none(val, expected):
    assert _int_or_none(val) == expected


# ---------------------------------------------------------------------------
# _parse_payload — scanning logic edge cases
# ---------------------------------------------------------------------------


def test_parse_payload_unbalanced_braces():
    """Unbalanced braces returns empty fallback."""
    text = '{"code": "x = 1", "comments": ""'  # missing closing brace
    result, fallback = _parse_payload(text, structured=True)
    assert result["code"] == ""
    assert fallback is True


def test_parse_payload_json_without_code_key_skips():
    """Valid JSON without 'code' key is skipped, continues scanning."""
    text = '{"status": "ok", "data": 42}'
    result, fallback = _parse_payload(text, structured=True)
    assert result["code"] == ""
    assert fallback is True


def test_parse_payload_multiple_blocks_second_has_code():
    """First block has no code key, second has code key — should find second."""
    text = '{"status": "ok"} then {"code": "found_it", "comments": "yes"}'
    result, fallback = _parse_payload(text, structured=True)
    assert result["code"] == "found_it"
    assert fallback is False


def test_parse_payload_invalid_json_block_then_valid():
    """First block is invalid JSON (Python dict literal), second is valid with code key."""
    text = "{'python': True} and then {\"code\": \"final\", \"comments\": \"ok\"}"
    result, fallback = _parse_payload(text, structured=True)
    assert result["code"] == "final"
    assert fallback is False


# ---------------------------------------------------------------------------
# _safe_response_json — edge cases
# ---------------------------------------------------------------------------


def test_safe_response_json_model_dump_non_string():
    """model_dump_json returns non-string — should fall through to vars."""
    class FakeResp:
        def __init__(self):
            self.data = "test"
        def model_dump_json(self):
            return 12345  # not a string

    result = _safe_response_json(FakeResp())
    parsed = json.loads(result)
    assert parsed["data"] == "test"


def test_safe_response_json_vars_fails_str_works():
    """vars() raises but str() works."""
    class FakeResp:
        __slots__ = ()  # vars() will fail with TypeError
        def __str__(self):
            return "stringified response"

    result = _safe_response_json(FakeResp())
    assert result == "stringified response"


def test_safe_response_json_everything_fails():
    """All methods fail, returns empty string."""
    class FakeResp:
        __slots__ = ()
        def model_dump_json(self):
            raise RuntimeError("dump fail")
        def __str__(self):
            raise RuntimeError("str fail")

    result = _safe_response_json(FakeResp())
    assert result == ""
