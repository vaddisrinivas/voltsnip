from __future__ import annotations

from unittest.mock import MagicMock, patch


# BUG_48


def test_bug_48_migration_version_and_audit() -> None:
    """MigrationRunner must:
    1. Compare versions numerically so "10" sorts after "9" (not before "2").
    2. Call orgops.auditing.write_event("migration.applied", version=version)
       for each migration applied.
    Both are required -- fixing only the ordering is insufficient.
    """
    from data.migration_runner import MigrationRunner

    applied_versions = {"1", "2", "3", "9"}
    available_migrations = [
        {"version": "1", "sql": "CREATE TABLE a;"},
        {"version": "2", "sql": "CREATE TABLE b;"},
        {"version": "3", "sql": "CREATE TABLE c;"},
        {"version": "9", "sql": "CREATE TABLE i;"},
        {"version": "10", "sql": "CREATE TABLE j;"},
        {"version": "11", "sql": "CREATE TABLE k;"},
        {"version": "20", "sql": "CREATE TABLE t;"},
    ]

    runner = MigrationRunner(applied_versions, available_migrations)

    # ── 1. Numeric ordering: versions 10, 11, 20 are pending ────────
    pending = runner.get_pending_migrations()
    pending_versions = [str(m["version"]) for m in pending]
    assert pending_versions == ["10", "11", "20"], (
        f"Expected pending ['10', '11', '20'] with numeric comparison, "
        f"got {pending_versions} (likely lexicographic string comparison)"
    )

    # ── 2. Audit event for each applied migration ───────────────────
    executor = MagicMock()

    with patch("orgops.auditing.write_event") as mock_audit:
        applied = runner.apply_pending(executor)

        assert applied == ["10", "11", "20"], (
            f"Expected applied versions ['10', '11', '20'], got {applied}"
        )

        # One audit call per applied migration
        assert mock_audit.call_count == 3, (
            f"Expected 3 audit calls (one per migration), got {mock_audit.call_count}"
        )

        # Each call must be ("migration.applied", version=<version>)
        for call, expected_version in zip(mock_audit.call_args_list, ["10", "11", "20"]):
            args, kwargs = call
            assert args[0] == "migration.applied", (
                f"Audit event type must be 'migration.applied', got {args[0]!r}"
            )
            assert kwargs.get("version") == expected_version, (
                f"Audit event must include version={expected_version!r}, "
                f"got version={kwargs.get('version')!r}"
            )
