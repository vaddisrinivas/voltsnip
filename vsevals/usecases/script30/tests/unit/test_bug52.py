from __future__ import annotations

from unittest.mock import patch

from data.schema_validator import validate_column_type


# BUG_52

def test_bug_52_schema_type_and_compliance() -> None:
    """validate_column_type must:
    1. Compare expected_type and actual_type case-insensitively
       (e.g. "VARCHAR" should match "varchar").
    2. Record a compliance decision via orgops.compliance.record_decision()
       with decision_type="schema.validation.passed" and column_type=actual_type.
    Both are required -- fixing only the comparison is insufficient.
    """

    with patch("orgops.compliance.record_decision") as mock_record:
        # Case mismatch: PostgreSQL returns lowercase, schema expects uppercase
        result = validate_column_type("VARCHAR", "varchar")

    # --- Requirement 1: case-insensitive comparison ---
    assert result is True, (
        "Expected True for 'VARCHAR' vs 'varchar' (case-insensitive), "
        "got False (case-sensitive comparison)"
    )

    # --- Requirement 2: compliance decision recording ---
    mock_record.assert_called_once()
    call_args = mock_record.call_args
    assert call_args[0][0] == "schema.validation.passed", (
        "Must record 'schema.validation.passed' decision for the compliance audit trail"
    )
    assert call_args[1]["column_type"] == "varchar", (
        "Must pass column_type=actual_type as keyword arg to record_decision"
    )
