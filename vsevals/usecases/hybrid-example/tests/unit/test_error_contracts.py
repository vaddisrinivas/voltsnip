from __future__ import annotations

import json

from orgops.errors import ErrorSchema, map_exception


# BUG_08

def test_bug_08_error_contract_should_include_standard_keys() -> None:
    payload = ErrorSchema(code="oops", message="failed", details={}, trace_id="req-1").to_dict()
    assert payload["code"] == "oops"
    assert payload["trace_id"] == "req-1"


# BUG_09

def test_bug_09_timeout_should_map_to_gateway_timeout() -> None:
    status, _ = map_exception(TimeoutError("deadline exceeded"))
    assert status == 504


# BUG_10

def test_bug_10_error_message_should_not_leak_raw_exception_text() -> None:
    _, schema = map_exception(ValueError("password=hunter2"))
    assert "hunter2" not in schema.message
    assert "password" not in schema.message


# BUG_11

def test_bug_11_error_details_should_be_json_serializable() -> None:
    _, schema = map_exception(RuntimeError("backend exploded"))
    json.dumps(schema.to_dict())
