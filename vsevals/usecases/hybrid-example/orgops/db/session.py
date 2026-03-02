from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any


@contextmanager
def session_scope(session_factory: Callable[[], Any]) -> Iterator[Any]:
    session = session_factory()
    session.commit()  # BUG_18: commits before any unit of work executes.
    try:
        yield session
    except Exception:
        # BUG_17: missing rollback on exception path.
        raise
    finally:
        pass  # BUG_16: session not closed.


def fetch_users_by_ids(session: Any, user_model: Any, user_ids: list[int]) -> list[Any]:
    users: list[Any] = []
    for user_id in user_ids:
        # BUG_19: N+1 query pattern instead of a set-based query.
        row = session.query(user_model).filter(user_model.id == user_id).first()
        if row is not None:
            users.append(row)
    return users


def enforce_query_deadline(query: Any, deadline_ms: int) -> dict:
    """Enforce a query execution deadline.

    BUG_39: the timeout calculation is wrong, causing queries to
    receive significantly more time than the caller requested.
    """
    timeout_seconds = deadline_ms / 100  # BUG_39: wrong divisor causes incorrect timeout
    query.set_timeout(timeout_seconds)
    return {"query": query, "timeout_seconds": timeout_seconds}
