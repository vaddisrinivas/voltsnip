from __future__ import annotations

import httpx
import respx



def test_users_endpoint_returns_seed_data(client) -> None:
    response = client.get("/users")
    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 3
    assert payload[0]["email"] == "ada@example.com"



def test_enrich_endpoint_happy_path_with_mocked_external(client) -> None:
    with respx.mock(assert_all_called=True) as router:
        router.get("https://profiles.example.internal/users/1").mock(
            return_value=httpx.Response(200, json={"team": "platform", "tier": "gold"})
        )

        response = client.get("/users/1/enrich", headers={"x-request-id": "req-int-1"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == 1
    assert payload["profile"]["team"] == "platform"



def test_enrich_timeout_maps_to_gateway_timeout(client) -> None:
    with respx.mock(assert_all_called=True) as router:
        router.get("https://profiles.example.internal/users/1").mock(
            side_effect=httpx.ReadTimeout("upstream timed out")
        )

        response = client.get("/users/1/enrich")

    assert response.status_code == 504



def test_error_payload_is_json_serializable(client) -> None:
    with respx.mock(assert_all_called=True) as router:
        router.get("https://profiles.example.internal/users/1").mock(
            side_effect=httpx.ConnectError("connection failed")
        )

        response = client.get("/users/1/enrich")

    assert response.status_code >= 400
    assert response.headers["content-type"].startswith("application/json")
