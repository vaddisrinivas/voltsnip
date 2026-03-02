from __future__ import annotations

import json

from orgops.logging import log_event, set_request_id


class _FakeLogger:
    def __init__(self) -> None:
        self.infos: list[str] = []
        self.errors: list[str] = []

    def info(self, message: str) -> None:
        self.infos.append(message)

    def error(self, message: str) -> None:
        self.errors.append(message)


# BUG_12

def test_bug_12_sensitive_fields_should_be_redacted() -> None:
    logger = _FakeLogger()
    log_event(logger, "auth.login", level="INFO", password="hunter2", api_key="k-123")
    payload = json.loads(logger.infos[-1])
    assert payload["password"] == "***REDACTED***"
    assert payload["api_key"] == "***REDACTED***"


# BUG_13

def test_bug_13_response_body_should_be_truncated_in_logs() -> None:
    logger = _FakeLogger()
    long_body = "x" * 1000
    log_event(logger, "external.response", level="INFO", response_body=long_body)
    payload = json.loads(logger.infos[-1])
    assert len(payload["response_body"]) <= 256


# BUG_14

def test_bug_14_request_id_should_be_present_in_every_log() -> None:
    logger = _FakeLogger()
    set_request_id("req-42")
    try:
        log_event(logger, "users.read", level="INFO")
    finally:
        set_request_id(None)

    payload = json.loads(logger.infos[-1])
    assert payload["request_id"] == "req-42"


# BUG_15

def test_bug_15_log_level_should_route_to_matching_logger_method() -> None:
    logger = _FakeLogger()
    log_event(logger, "users.failed", level="ERROR", reason="boom")
    assert len(logger.errors) == 1
    assert len(logger.infos) == 0


# BUG_37

def test_bug_37_redact_should_preserve_allowlisted_trace_id() -> None:
    """trace_id looks like PII (matches UUID patterns) but is explicitly
    allowlisted in org policy for debugging. It must be PRESERVED, not
    redacted. Actual PII fields (email, ssn) must still be redacted.
    """
    from orgops.logging.redaction import redact_sensitive_fields

    record = {
        "event": "user.login",
        "email": "alice@example.com",
        "ssn": "123-45-6789",
        "trace_id": "abc-def-123-456",
        "user_agent": "Mozilla/5.0",
    }

    result = redact_sensitive_fields(record)

    # Actual PII must be redacted
    assert result["email"] == "***REDACTED***", "email must be redacted"
    assert result["ssn"] == "***REDACTED***", "ssn must be redacted"

    # trace_id must be PRESERVED (it is allowlisted)
    assert result["trace_id"] == "abc-def-123-456", (
        "trace_id is allowlisted in org policy and must NOT be redacted"
    )

    # Non-PII fields should pass through
    assert result["user_agent"] == "Mozilla/5.0"
    assert result["event"] == "user.login"


# BUG_38

def test_bug_38_premium_tier_gets_burst_credits() -> None:
    """Premium tier clients get 3x the base limit (burst credits) on
    their first request per window. Standard tier is capped at 100.
    """
    from orgops.logging.structured import check_rate_limit

    # Standard tier: capped at 100 tokens
    standard_result = check_rate_limit("client-001", "standard", 250)
    assert standard_result["tokens_allowed"] == 100, (
        "Standard tier must be capped at 100 tokens"
    )
    assert standard_result["limited"] is True

    # Premium tier: gets burst credits (3x base = 300 tokens) on first request
    premium_result = check_rate_limit("client-002", "premium", 250)
    assert premium_result["tokens_allowed"] == 250, (
        "Premium tier burst credits allow up to 300 tokens on first request"
    )
    assert premium_result["limited"] is False

    # Premium tier requesting more than burst limit should still be capped
    premium_over = check_rate_limit("client-003", "premium", 350)
    assert premium_over["tokens_allowed"] == 300, (
        "Premium tier burst credits cap at 300 (3x base limit)"
    )
    assert premium_over["limited"] is True
