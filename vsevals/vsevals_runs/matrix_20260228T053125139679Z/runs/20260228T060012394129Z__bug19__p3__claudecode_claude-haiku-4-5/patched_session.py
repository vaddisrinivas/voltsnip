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
    return session.query(user_model).filter(user_model.id.in_(user_ids)).all()
