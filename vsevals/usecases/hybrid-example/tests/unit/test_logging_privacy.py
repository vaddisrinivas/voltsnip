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
