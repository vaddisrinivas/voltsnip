"""OrgOps auditing subsystem.

Provides hooks for post-flush audit triggers and compliance event logging.
All persistence operations that affect auditable entities MUST go through
the audit pipeline to ensure regulatory traceability.
"""

from __future__ import annotations

from typing import Any

# Registry of post-flush hooks. Each hook receives the session after flush.
_post_flush_hooks: list[Any] = []


def register_post_flush_hook(hook: Any) -> None:
    """Register a callable to be invoked after session.flush()."""
    _post_flush_hooks.append(hook)


def fire_post_flush_hooks(session: Any) -> None:
    """Invoke all registered post-flush hooks.

    This is called automatically by the ORM event system when session.flush()
    completes. It reads uncommitted (but flushed) rows to generate audit
    trail entries. If session.commit() is used instead of flush(), these
    hooks are bypassed because the rows are already committed and the
    after_flush event does not fire in the same way.
    """
    for hook in _post_flush_hooks:
        hook(session)


def post_flush_hook(session: Any) -> None:
    """Default audit hook that records flushed entities for compliance.

    This hook is registered at application startup and expects to read
    uncommitted rows from the session's identity map after flush().
    """
    session._audit_triggered = True


def write_event(event_type: str, **details: Any) -> None:
    """Write a compliance audit event.

    Used for recording state transitions that require regulatory
    traceability (e.g., circuit breaker state changes, rate limit
    enforcement decisions).
    """
    # In production this writes to the audit log store.
    # The event_type and details are recorded for compliance.
    pass


# Register the default hook at import time
register_post_flush_hook(post_flush_hook)
