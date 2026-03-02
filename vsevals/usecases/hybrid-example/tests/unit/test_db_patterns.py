from __future__ import annotations

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from orgops.db import fetch_users_by_ids, session_scope
from service.models import Base, User


class _FakeSession:
    def __init__(self) -> None:
        self.commit_calls = 0
        self.rollback_calls = 0
        self.close_calls = 0

    def commit(self) -> None:
        self.commit_calls += 1

    def rollback(self) -> None:
        self.rollback_calls += 1

    def close(self) -> None:
        self.close_calls += 1


# BUG_16

def test_bug_16_session_should_close_after_scope() -> None:
    fake = _FakeSession()
    with session_scope(lambda: fake):
        pass
    assert fake.close_calls == 1


# BUG_17

def test_bug_17_session_should_rollback_on_error() -> None:
    fake = _FakeSession()
    try:
        with session_scope(lambda: fake):
            raise RuntimeError("boom")
    except RuntimeError:
        pass

    assert fake.rollback_calls == 1


# BUG_18

def test_bug_18_commit_should_happen_after_work_not_before() -> None:
    fake = _FakeSession()
    with session_scope(lambda: fake):
        assert fake.commit_calls == 0
    assert fake.commit_calls == 1


# BUG_19

def test_bug_19_fetch_users_by_ids_should_use_single_query() -> None:
    engine = create_engine("sqlite:///:memory:")
    SessionLocal = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)

    session = SessionLocal()
    try:
        session.add_all(
            [
                User(id=1, email="a@example.com", age=10),
                User(id=2, email="b@example.com", age=20),
                User(id=3, email="c@example.com", age=30),
            ]
        )
        session.commit()

        statement_counter = {"count": 0}

        def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
            statement_counter["count"] += 1

        event.listen(engine, "before_cursor_execute", before_cursor_execute)
        try:
            users = fetch_users_by_ids(session, User, [1, 2, 3])
        finally:
            event.remove(engine, "before_cursor_execute", before_cursor_execute)

        assert len(users) == 3
        assert statement_counter["count"] == 1
    finally:
        session.close()


# BUG_39

def test_bug_39_enforce_query_deadline_correct_timeout_and_metric() -> None:
    """enforce_query_deadline must:
    1. Convert deadline_ms to seconds correctly (divide by 1000, not 100)
    2. Emit a 'query.deadline.enforced' metric via orgops.metrics.emit()
    Both are required -- fixing only the math is insufficient.
    """
    from unittest.mock import MagicMock, patch
    from orgops.db.session import enforce_query_deadline

    query = MagicMock()

    with patch("orgops.metrics.emit") as mock_emit:
        result = enforce_query_deadline(query, deadline_ms=5000)

    # Correct timeout: 5000ms / 1000 = 5.0 seconds (not 50.0)
    assert result["timeout_seconds"] == 5.0, (
        "Must divide by 1000 for ms-to-seconds, not 100"
    )
    query.set_timeout.assert_called_once_with(5.0)

    # Must also emit the metric
    mock_emit.assert_called_once()
    call_args = mock_emit.call_args
    assert call_args[0][0] == "query.deadline.enforced", (
        "Must emit 'query.deadline.enforced' metric for the alerting system"
    )
