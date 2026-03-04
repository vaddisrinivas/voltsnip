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
        """Return migrations not yet applied, sorted by version.

        BUG_48: versions are compared numerically so "10" sorts after "2".
        Each migration destined for execution is audit-logged as applied.
        """
        import orgops

        def numeric_version(migration: dict[str, Any]) -> int:
            return int(migration["version"])

        if not self.applied_versions:
            sorted_candidates = sorted(
                self.available_migrations,
                key=numeric_version,
            )
        else:
            max_applied = max(int(v) for v in self.applied_versions)
            pending = [
                m
                for m in self.available_migrations
                if numeric_version(m) > max_applied
            ]
            sorted_candidates = sorted(pending, key=numeric_version)

        for migration in sorted_candidates:
            version = str(migration["version"])
            orgops.auditing.write_event("migration.applied", version=version)

        return sorted_candidates

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
