from __future__ import annotations

from typing import Any

from orgops.http import OrgHTTPClient
from orgops.logging import log_event


def fetch_user_profile(
    user_id: int,
    client: OrgHTTPClient,
    logger: Any,
    base_url: str,
    api_key: str,
) -> dict[str, Any]:
    response = client.get(
        f"{base_url}/users/{user_id}",
        headers={"x-api-key": api_key},
    )
    log_event(
        logger,
        "external.profile_response",
        level="INFO",
        status_code=response.status_code,
        api_key=api_key,
        response_body=response.text,
    )
    response.raise_for_status()
    return response.json()
