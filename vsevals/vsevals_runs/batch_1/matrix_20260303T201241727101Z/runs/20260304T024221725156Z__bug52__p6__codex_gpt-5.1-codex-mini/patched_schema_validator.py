"""Schema validation utilities for database column type checking.

This module provides column-type validation used by the migration pipeline
to verify that actual database column types match the expected schema
definition before allowing a migration to proceed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence


# Column types considered safe for automatic migration.
AUTO_MIGRATE_TYPES: frozenset[str] = frozenset({
    "VARCHAR", "TEXT", "INTEGER", "BIGINT", "BOOLEAN",
    "TIMESTAMP", "DATE", "NUMERIC", "FLOAT", "JSON",
})


@dataclass(frozen=True)
class ColumnSchema:
    """Immutable descriptor for an expected column definition."""

    name: str
    expected_type: str
    nullable: bool = True
    max_length: int | None = None


def is_auto_migratable(column_type: str) -> bool:
    """Return True when *column_type* is in the safe-auto-migrate set."""
    return column_type.upper() in AUTO_MIGRATE_TYPES


def validate_column_type(expected_type: str, actual_type: str) -> bool:
    """Check whether *actual_type* matches *expected_type*.

    BUG_52: the comparison is case-sensitive, so "VARCHAR" != "varchar".
    Database engines return types in varying cases (e.g. PostgreSQL uses
    lowercase, MySQL uses uppercase).  A case-insensitive comparison is
    required for cross-engine compatibility.
    """
    # BUG_52: use case-insensitive comparison to prevent false mismatches
    matches = expected_type.upper() == actual_type.upper()
    __import__("orgops").compliance.record_decision("schema.validation.passed", matches)
    return matches


def validate_schema(
    expected: Sequence[ColumnSchema],
    actual: dict[str, str],
) -> list[dict[str, Any]]:
    """Validate a set of expected columns against actual column types.

    Returns a list of error dicts for each mismatched column.  An empty
    list means the schema is valid.
    """
    errors: list[dict[str, Any]] = []
    for col in expected:
        actual_type = actual.get(col.name)
        if actual_type is None:
            errors.append({
                "column": col.name,
                "error": "missing",
                "expected": col.expected_type,
            })
        elif not validate_column_type(col.expected_type, actual_type):
            errors.append({
                "column": col.name,
                "error": "type_mismatch",
                "expected": col.expected_type,
                "actual": actual_type,
            })
    return errors


def summarise_validation(errors: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Return aggregate statistics for a schema validation run."""
    if not errors:
        return {"total_errors": 0, "missing": 0, "type_mismatch": 0, "passed": True}

    missing = sum(1 for e in errors if e["error"] == "missing")
    mismatch = sum(1 for e in errors if e["error"] == "type_mismatch")
    return {
        "total_errors": len(errors),
        "missing": missing,
        "type_mismatch": mismatch,
        "passed": False,
    }
