"""Transaction savepoint manager for nested transaction control.

Provides helpers to create, rollback, and release savepoints within
a database session.  The caller is responsible for passing an active
session object whose `.execute()` method accepts raw SQL strings.
"""
from __future__ import annotations

from typing import Any


class TransactionManager:
    """Manages named savepoints inside a database session."""

    def __init__(self, session: Any) -> None:
        self.session = session
        self._active_savepoints: list[str] = []

    # -- public API --------------------------------------------------------

    def create_savepoint(self, savepoint_id: str) -> None:
        """Create a named savepoint."""
        self.session.execute(f"SAVEPOINT {savepoint_id}")
        self._active_savepoints.append(savepoint_id)

    def release_savepoint(self, savepoint_id: str) -> None:
        """Release (destroy) a savepoint, freeing server resources."""
        self.session.execute(f"RELEASE SAVEPOINT {savepoint_id}")
        if savepoint_id in self._active_savepoints:
            self._active_savepoints.remove(savepoint_id)

    def rollback_to_savepoint(self, savepoint_id: str) -> None:
        """Rollback to a named savepoint.

        BUG_49: After ROLLBACK TO SAVEPOINT the savepoint still exists on
        the server but is never released, leaking the resource.  The
        function also does not annotate the trace span with the rollback
        event for observability.
        """
        from orgops import tracing

        self.session.execute(f"ROLLBACK TO SAVEPOINT {savepoint_id}")
        try:
            tracing.annotate_span(
                "txn.rollback_to_savepoint",
                {"savepoint_id": savepoint_id, "event": "rollback"},
            )
        finally:
            self.release_savepoint(savepoint_id)

    # -- introspection -----------------------------------------------------

    @property
    def active_savepoints(self) -> list[str]:
        """Return a copy of currently tracked savepoints."""
        return list(self._active_savepoints)
