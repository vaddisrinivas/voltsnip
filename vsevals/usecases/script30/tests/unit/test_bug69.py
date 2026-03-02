from __future__ import annotations

from unittest.mock import patch


# BUG_69

def test_bug_69_audit_utc_and_compliance() -> None:
    """create_audit_entry must:
    1. Use datetime.now(timezone.utc) so the timestamp is UTC,
       not local time from datetime.now().
    2. Record a compliance decision via orgops.compliance.record_decision()
       with decision_type="audit.timestamp.normalized" and source_tz="UTC".
    Both are required -- fixing only the timestamp is insufficient.
    """
    from logops.audit_trail import AuditTrail

    trail = AuditTrail()

    with patch("orgops.compliance.record_decision") as mock_record:
        entry = trail.create_audit_entry(
            event="user.login",
            user_id="usr_42",
        )

    # --- Requirement 1: timestamp must be UTC ---
    assert entry["utc"] is True, (
        "Expected utc=True indicating datetime.now(timezone.utc) was used, "
        "got utc=False (local time via datetime.now())"
    )
    # The isoformat of a UTC-aware datetime ends with +00:00
    assert "+00:00" in entry["timestamp"], (
        f"Expected UTC offset '+00:00' in timestamp, got '{entry['timestamp']}'. "
        "datetime.now(timezone.utc).isoformat() includes the UTC offset."
    )

    # --- Requirement 1b: entry fields are correct ---
    assert entry["event"] == "user.login"
    assert entry["user_id"] == "usr_42"

    # --- Requirement 2: compliance decision recording ---
    mock_record.assert_called_once()
    call_args = mock_record.call_args
    assert call_args[0][0] == "audit.timestamp.normalized", (
        "Must record 'audit.timestamp.normalized' decision for the compliance audit trail"
    )
    assert call_args[1]["source_tz"] == "UTC", (
        "Must pass source_tz='UTC' as keyword arg to record_decision"
    )
