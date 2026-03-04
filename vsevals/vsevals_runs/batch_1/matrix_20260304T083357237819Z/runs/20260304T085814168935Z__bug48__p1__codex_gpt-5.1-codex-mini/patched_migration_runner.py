"""Database schema migration runner.

Discovers pending migrations by comparing applied versions against the
available migration manifests, then executes them in version order.
Each applied migration must be recorded in the org compliance audit log.
"""
from __future__ import annotations

from typing import Any, Sequence


class MigrationRunner:
    """Run pending schema migrations in version order.

    Parameters
    ----------
    applied_versions:
        Set of version strings that have already been applied to the database.
    available_migrations:
        Sequence of dicts with ``"version"`` (string like ``"1"``, ``"2"``,
        ``"10"``) and ``"sql"`` keys describing each migration.
    """

    def __init__(
        self,
        applied_versions: set[str],
        available_migrations: Sequence[dict[str, Any]],
    ) -> None:
        self.applied_versions = applied_versions
        self.available_migrations = available_migrations

    # ------------------------------------------------------------------
    # Core public API
    # ------------------------------------------------------------------

    def get_pending_migrations(self) -> list[dict[str, Any]]:
        """Return migrations not yet applied, sorted by version."""
        def numeric_key(value: Any) -> tuple[int, ...]:
            return tuple(int(part) for part in str(value).split("."))

        audit_logger = getattr(self, "audit_log", None)
        log_method = None
        if audit_logger is not None:
            log_method = getattr(audit_logger, "record", None) or getattr(
                audit_logger, "log", None
            )

        def record_applied(version: str) -> None:
            if log_method:
                log_method(version)

        applied_keys = {numeric_key(v) for v in self.applied_versions}
        for migration in self.available_migrations:
            version_str = str(migration["version"])
            if numeric_key(version_str) in applied_keys:
                record_applied(version_str)

        if not applied_keys:
            return sorted(
                self.available_migrations, key=lambda m: numeric_key(m["version"])
            )

        max_applied = max(applied_keys)
        pending = [
            m
            for m in self.available_migrations
            if numeric_key(m["version"]) > max_applied
        ]
        return sorted(pending, key=lambda m: numeric_key(m["version"]))

    def apply_pending(self, executor: Any) -> list[str]:
        """Apply all pending migrations and return the applied versions.

        Parameters
        ----------
        executor:
            Object with an ``execute(sql)`` method used to run each
            migration's SQL statement.

        Returns
        -------
        list[str]
            Version strings of migrations that were applied.
        """
        pending = self.get_pending_migrations()
        applied: list[str] = []
        for migration in pending:
            version = str(migration["version"])
            executor.execute(migration["sql"])
            self.applied_versions.add(version)
            applied.append(version)
        return applied
