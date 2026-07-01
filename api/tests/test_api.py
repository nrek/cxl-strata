from __future__ import annotations

from fastapi.testclient import TestClient

BOOTSTRAP_KEY = "strata_dev_example"


def _auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {BOOTSTRAP_KEY}"}


def test_landing_page(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    body = response.text
    assert 'href="https://github.com/nrek/cxl-strata"' in body
    assert 'src="/assets/strata_large.png"' in body
    assert 'target=' not in body


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["storage"] == "postgres"


def test_whoami_bootstrap(client: TestClient) -> None:
    response = client.get("/v1/whoami", headers=_auth_headers())
    assert response.status_code == 200
    body = response.json()
    assert body["organization"] == "bootstrap-org"
    assert body["bootstrap"] is True
    assert "memory:read" in body["scopes"]


def test_unknown_token_rejected(client: TestClient) -> None:
    response = client.get("/v1/whoami", headers={"Authorization": "Bearer strata_dev_unknown"})
    assert response.status_code == 401


def test_create_and_search_memory_event(client: TestClient) -> None:
    payload = {
        "project_slug": "cxl-strata",
        "event_type": "implementation_note",
        "title": "Postgres rollout",
        "summary": "Wired API to PostgreSQL with Alembic migrations.",
        "tags": ["postgres", "alembic"],
    }
    create = client.post("/v1/memory-events", json=payload, headers=_auth_headers())
    assert create.status_code == 200
    event_id = create.json()["id"]

    search = client.get("/v1/search", params={"q": "Alembic"}, headers=_auth_headers())
    assert search.status_code == 200
    ids = [row["id"] for row in search.json()["results"]]
    assert event_id in ids

    get_one = client.get(f"/v1/memory-events/{event_id}", headers=_auth_headers())
    assert get_one.status_code == 200
    assert get_one.json()["title"] == "Postgres rollout"


def test_secret_payload_rejected(client: TestClient) -> None:
    payload = {
        "project_slug": "cxl-strata",
        "event_type": "general_note",
        "title": "bad",
        "summary": "password=supersecret123",
    }
    response = client.post("/v1/memory-events", json=payload, headers=_auth_headers())
    assert response.status_code == 422


def test_hashed_api_key_flow(client: TestClient) -> None:
    create_key = client.post(
        "/v1/api-keys",
        json={"name": "test-key", "prefix": "strata_dev_"},
        headers=_auth_headers(),
    )
    assert create_key.status_code == 200
    body = create_key.json()
    raw_key = body["raw_key"]
    key_id = body["id"]

    whoami = client.get("/v1/whoami", headers={"Authorization": f"Bearer {raw_key}"})
    assert whoami.status_code == 200
    assert whoami.json()["bootstrap"] is False

    revoke = client.post(f"/v1/api-keys/{key_id}/revoke", headers=_auth_headers())
    assert revoke.status_code == 200
    assert revoke.json()["is_active"] is False

    rejected = client.get("/v1/whoami", headers={"Authorization": f"Bearer {raw_key}"})
    assert rejected.status_code == 401
