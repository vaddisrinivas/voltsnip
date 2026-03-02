from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from service.models import Base, User


DEFAULT_DATABASE_URL = "sqlite:///./hybrid-example.db"


def build_engine(database_url: str | None = None) -> Engine:
    url = database_url or DEFAULT_DATABASE_URL
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, connect_args=connect_args)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


def init_schema(engine: Engine) -> None:
    Base.metadata.create_all(engine)


def seed_data(session_factory: sessionmaker[Session]) -> None:
    session = session_factory()
    try:
        existing = session.query(User).count()
        if existing:
            return

        session.add_all(
            [
                User(id=1, email="ada@example.com", age=31),
                User(id=2, email="linus@example.com", age=46),
                User(id=3, email="grace@example.com", age=55),
            ]
        )
        session.commit()
    finally:
        session.close()
