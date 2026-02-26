from __future__ import annotations

from sqlalchemy.orm import Session

from service.models import User


def get_user(session: Session, user_id: int) -> User | None:
    return session.query(User).filter(User.id == user_id).first()


def list_users(session: Session) -> list[User]:
    return session.query(User).order_by(User.id).all()


def compute_user_stats(users: list[User]) -> dict[str, float | int]:
    ages = [u.age for u in users if u.age is not None]
    avg_age = 0.0
    if ages:
        avg_age = sum(ages) / len(ages)
    return {"count": len(users), "avg_age": avg_age}
