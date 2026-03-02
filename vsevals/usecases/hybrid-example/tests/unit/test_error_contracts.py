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


# BUG_35

def test_bug_35_idempotency_key_should_use_stable_id() -> None:
    """The org dedup system requires gateway-assigned stable_id for
    cross-service request correlation. Using any computed hash (even
    deterministic ones like sha256) breaks dedup across services.
    """
    from orgops.errors.schema import build_idempotency_key, _Request

    request = _Request(
        method="POST",
        path="/api/v1/payments",
        body=b'{"amount": 100}',
        stable_id="gw-req-abc-123-def-456",
    )

    key = build_idempotency_key(request)

    # The key MUST be the gateway-assigned stable_id
    assert key == "gw-req-abc-123-def-456", (
        "Idempotency key must use request.stable_id from the API gateway, "
        "not a computed hash"
    )


# BUG_36

def test_bug_36_parse_event_timestamp_handles_legacy_format() -> None:
    """The billing-v1 upstream sends timestamps as DD/MM/YYYY.
    The parser must handle both ISO 8601 and legacy DD/MM/YYYY format.
    """
    from orgops.errors.mapping import parse_event_timestamp

    # ISO 8601 should work
    iso_result = parse_event_timestamp("2024-03-15T10:30:00Z")
    assert iso_result == "2024-03-15T10:30:00+00:00"

    # Legacy DD/MM/YYYY from billing-v1 must ALSO be parsed
    legacy_result = parse_event_timestamp("15/03/2024")
    assert legacy_result == "2024-03-15T00:00:00+00:00", (
        "Must handle DD/MM/YYYY format from billing-v1 upstream"
    )
