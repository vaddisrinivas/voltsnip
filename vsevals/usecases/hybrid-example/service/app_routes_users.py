from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy.orm import Session

from service.app_dependencies import get_cache, get_db
from service.cache import TTLCache
from service.repository import compute_user_stats, get_user, list_users


def register_user_routes(app: FastAPI) -> None:
    @app.get("/users")
    def read_users(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
        users = list_users(db)
        return [{"id": u.id, "email": u.email, "age": u.age} for u in users]

    @app.get("/users/stats")
    def read_user_stats(
        db: Session = Depends(get_db),
        cache: TTLCache = Depends(get_cache),
    ) -> dict[str, Any]:
        return cache.get_or_set("users.stats", lambda: compute_user_stats(list_users(db)))

    @app.get("/users/{user_id}")
    def read_user(user_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
        user = get_user(db, user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        return {"id": user.id, "email": user.email, "age": user.age}
