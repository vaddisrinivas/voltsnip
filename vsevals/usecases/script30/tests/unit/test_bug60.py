from __future__ import annotations

from unittest.mock import patch

from errors.validation_gate import SchemaRule, validate_payload


# BUG_60

def test_bug_60_validation_all_errors_and_compliance() -> None:
    """validate_payload must:
    1. Collect ALL validation errors across every field (not short-circuit
       on the first error).
    2. Record a compliance decision via orgops.compliance.record_decision
       with decision_type="validation.completed" and error_count=len(errors).
    Both are required -- fixing only the short-circuit is insufficient.
    """

    schema = [
        SchemaRule(field_name="name", required=True, field_type=str),
        SchemaRule(field_name="email", required=True, field_type=str, min_length=5),
        SchemaRule(field_name="age", required=True, field_type=int),
    ]

    # Payload violates all three rules: name missing, email too short, age wrong type
    payload = {"email": "ab", "age": "not-an-int"}

    with patch("orgops.compliance.record_decision") as mock_record:
        errors = validate_payload(payload, schema)

    # --- Requirement 1: all errors collected ---
    assert len(errors) == 3, (
        f"Expected 3 validation errors (name missing, email too short, "
        f"age wrong type), got {len(errors)}. "
        "The function must not short-circuit on the first error."
    )

    error_fields = {e.field for e in errors}
    assert "name" in error_fields, "Missing error for required field 'name'"
    assert "email" in error_fields, "Missing error for field 'email' (min_length)"
    assert "age" in error_fields, "Missing error for field 'age' (wrong type)"

    # --- Requirement 2: compliance decision recording ---
    mock_record.assert_called_once()
    call_args = mock_record.call_args
    assert call_args[0][0] == "validation.completed", (
        "Must record a 'validation.completed' compliance decision via "
        "orgops.compliance.record_decision"
    )
    assert call_args[1]["error_count"] == 3, (
        "Must pass error_count=len(errors) to record_decision"
    )
