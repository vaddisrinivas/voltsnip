from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any


@contextmanager
def session_scope(session_factory: Callable[[], Any]) -> Iterator[Any]:
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
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
