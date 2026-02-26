from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy.orm import Session

from orgops.db import fetch_users_by_ids
from orgops.http import OrgHTTPClient
from service.app_dependencies import get_db, get_http_client
from service.app_logging import logger
from service.external import fetch_user_profile
from service.models import User
from service.repository import get_user


def register_enrich_routes(app: FastAPI) -> None:
    @app.get("/users/{user_id}/enrich")
    def read_user_with_profile(
        user_id: int,
        db: Session = Depends(get_db),
        client: OrgHTTPClient = Depends(get_http_client),
    ) -> dict[str, Any]:
        user = get_user(db, user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")

        profile = fetch_user_profile(
            user_id=user_id,
            client=client,
            logger=logger,
            base_url=app.state.external_base_url,
            api_key=app.state.external_api_key,
        )

        sampled_users = fetch_users_by_ids(db, User, [1, 2, 3])
        return {
            "id": user.id,
            "email": user.email,
            "profile": profile,
            "sampled_count": len(sampled_users),
        }
