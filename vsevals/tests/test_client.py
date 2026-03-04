"""Tests for vsevals.client — VoltSnip HTTP client, retry, error classification."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from vsevals.client import (
    VoltSnipClient,
    _is_rate_limit_error,
    _is_timeout_error,
    _to_snippet,
)


# ---------------------------------------------------------------------------
# _is_rate_limit_error
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("exc,expected", [
    (RuntimeError("rate limit exceeded"), True),
    (RuntimeError("429 too many requests"), True),
    (RuntimeError("quota exceeded"), True),
    (RuntimeError("normal error"), False),
    (httpx.TimeoutException("timeout"), False),
])
def test_is_rate_limit_error(exc, expected):
    assert _is_rate_limit_error(exc) == expected


def test_is_rate_limit_error_http_429():
    response = MagicMock()
    response.status_code = 429
    exc = httpx.HTTPStatusError("rate limit", request=MagicMock(), response=response)
    assert _is_rate_limit_error(exc) is True


# ---------------------------------------------------------------------------
# _is_timeout_error
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("exc,expected", [
    (httpx.TimeoutException("conn timeout"), True),
    (TimeoutError("timed out"), True),
    (RuntimeError("request timeout hit"), True),
    (RuntimeError("timed out waiting"), True),
    (RuntimeError("normal error"), False),
])
def test_is_timeout_error(exc, expected):
    assert _is_timeout_error(exc) == expected


# ---------------------------------------------------------------------------
# _to_snippet
# ---------------------------------------------------------------------------


def test_to_snippet_basic():
    detail = {
        "id": "abc",
        "canonical_key": "key1",
        "title": "Title",
        "language": "python",
        "tags": ["api", "config"],
        "description": "desc",
        "code": "x = 1",
    }
    snip = _to_snippet(detail, max_chars=100)
    assert snip.id == "abc"
    assert snip.canonical_key == "key1"
    assert snip.language == "python"
    assert snip.code == "x = 1"


def test_to_snippet_truncates_code():
    detail = {"id": "abc", "code": "x" * 200}
    snip = _to_snippet(detail, max_chars=50)
    assert len(snip.code) == 50


def test_to_snippet_missing_fields():
    detail = {"id": None, "code": None}
    snip = _to_snippet(detail, max_chars=100)
    assert snip.id == "unknown"
    assert snip.code == ""


# ---------------------------------------------------------------------------
# VoltSnipClient init
# ---------------------------------------------------------------------------


def test_client_init():
    c = VoltSnipClient(base_url="http://localhost:8000/", timeout_seconds=10, retry_attempts=2)
    assert c.base_url == "http://localhost:8000"
    assert c.retry_attempts == 2
    assert c.retry_count_total == 0


def test_client_init_min_retry():
    c = VoltSnipClient(base_url="http://x", retry_attempts=0)
    assert c.retry_attempts == 1


# ---------------------------------------------------------------------------
# VoltSnipClient.preflight_check
# ---------------------------------------------------------------------------


@patch("vsevals.client.httpx.Client")
def test_preflight_check_localhost_ok(mock_client_cls):
    mock_ctx = MagicMock()
    mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_ctx)
    mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
    mock_ctx.get.return_value.raise_for_status = MagicMock()
    c = VoltSnipClient(base_url="http://localhost:8000")
    assert c.preflight_check() is True


def test_preflight_check_non_localhost():
    c = VoltSnipClient(base_url="https://api.example.com")
    assert c.preflight_check() is True


@patch("vsevals.client.httpx.Client")
def test_preflight_check_fails(mock_client_cls):
    mock_client_cls.return_value.__enter__ = MagicMock(side_effect=Exception("no connection"))
    mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
    c = VoltSnipClient(base_url="http://localhost:8000")
    assert c.preflight_check() is False


# ---------------------------------------------------------------------------
# VoltSnipClient.get_by_canonical_keys
# ---------------------------------------------------------------------------


def test_get_by_canonical_keys_empty():
    c = VoltSnipClient(base_url="http://localhost:8000")
    assert c.get_by_canonical_keys([], limit=5, max_chars=100) == []


def test_get_by_canonical_keys_filters_empty_strings():
    c = VoltSnipClient(base_url="http://localhost:8000")
    assert c.get_by_canonical_keys(["", ""], limit=5, max_chars=100) == []


@patch.object(VoltSnipClient, "_call")
def test_get_by_canonical_keys_success(mock_call):
    mock_call.return_value = {"id": "123", "canonical_key": "k1", "code": "x = 1"}
    c = VoltSnipClient(base_url="http://localhost:8000")
    result = c.get_by_canonical_keys(["k1"], limit=5, max_chars=100)
    assert len(result) == 1
    assert result[0].canonical_key == "k1"


@patch.object(VoltSnipClient, "_call", side_effect=httpx.HTTPError("404"))
def test_get_by_canonical_keys_handles_not_found(mock_call):
    c = VoltSnipClient(base_url="http://localhost:8000")
    result = c.get_by_canonical_keys(["missing"], limit=5, max_chars=100)
    assert result == []


# ---------------------------------------------------------------------------
# VoltSnipClient.semantic_search
# ---------------------------------------------------------------------------


def test_semantic_search_empty_query():
    c = VoltSnipClient(base_url="http://localhost:8000")
    assert c.semantic_search(q="  ", k=5, max_chars=100) == []


@patch.object(VoltSnipClient, "_call")
def test_semantic_search_success(mock_call):
    mock_call.side_effect = [
        [{"id": "123"}],  # search results
        {"id": "123", "canonical_key": "k1", "code": "x = 1"},  # detail
    ]
    c = VoltSnipClient(base_url="http://localhost:8000")
    result = c.semantic_search(q="test query", k=5, max_chars=100)
    assert len(result) == 1


# ---------------------------------------------------------------------------
# VoltSnipClient retry logic
# ---------------------------------------------------------------------------


@patch.object(VoltSnipClient, "_http")
def test_retry_on_failure(mock_http):
    mock_http.side_effect = [RuntimeError("fail"), {"data": "ok"}]
    c = VoltSnipClient(base_url="http://localhost:8000", retry_attempts=2, retry_backoff_seconds=0)
    result = c._call("GET", "/test")
    assert result == {"data": "ok"}
    assert c.retry_count_total == 1
    assert c.error_count_total == 1


@patch.object(VoltSnipClient, "_http")
def test_retry_exhausted(mock_http):
    mock_http.side_effect = RuntimeError("persistent failure")
    c = VoltSnipClient(base_url="http://localhost:8000", retry_attempts=2, retry_backoff_seconds=0)
    with pytest.raises(RuntimeError, match="persistent failure"):
        c._call("GET", "/test")
    assert c.error_count_total == 2


@patch.object(VoltSnipClient, "_http")
def test_retry_tracks_rate_limit(mock_http):
    mock_http.side_effect = RuntimeError("429 rate limit hit")
    c = VoltSnipClient(base_url="http://localhost:8000", retry_attempts=2, retry_backoff_seconds=0)
    with pytest.raises(RuntimeError):
        c._call("GET", "/test")
    assert c.rate_limit_error_count == 2


@patch.object(VoltSnipClient, "_http")
def test_retry_tracks_timeout(mock_http):
    mock_http.side_effect = httpx.TimeoutException("timeout")
    c = VoltSnipClient(base_url="http://localhost:8000", retry_attempts=2, retry_backoff_seconds=0)
    with pytest.raises(httpx.TimeoutException):
        c._call("GET", "/test")
    assert c.timeout_error_count == 2
