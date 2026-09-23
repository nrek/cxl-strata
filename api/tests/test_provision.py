from __future__ import annotations

from fastapi.testclient import TestClient

PROVISION_TOKEN = "provision-test-token"


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {PROVISION_TOKEN}"}


def test_provision_team_requires_token(client: TestClient) -> None:
    response = client.post(
        "/v1/provision/team",
        json={"slug": "htc", "name": "HTC"},
    )
    assert response.status_code == 401


def test_provision_team_rejects_wrong_token(client: TestClient) -> None:
    response = client.post(
        "/v1/provision/team",
        json={"slug": "htc", "name": "HTC"},
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert response.status_code == 401


def test_provision_team_creates_org_and_key(client: TestClient) -> None:
    response = client.post(
        "/v1/provision/team",
        json={
            "slug": "htc",
            "name": "HTC",
            "actor_name": "david",
            "actor_email": "david@htc.example",
            "prefix": "strata_dev_",
        },
        headers=_headers(),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["organization"]["slug"] == "htc"
    assert body["organization"]["name"] == "HTC"
    assert body["organization"]["id"]
    assert body["actor"]["name"] == "david"
    assert body["api_key"].startswith("strata_dev_")

    whoami = client.get("/v1/whoami", headers={"Authorization": f"Bearer {body['api_key']}"})
    assert whoami.status_code == 200
    assert whoami.json()["organization"] == "htc"
    assert whoami.json()["organization_id"] == body["organization"]["id"]


def test_provision_team_idempotent_slug(client: TestClient) -> None:
    first = client.post(
        "/v1/provision/team",
        json={"slug": "craft-and-logic", "name": "Craft & Logic", "prefix": "strata_dev_"},
        headers=_headers(),
    )
    assert first.status_code == 200
    second = client.post(
        "/v1/provision/team",
        json={"slug": "craft-and-logic", "name": "Craft and Logic Renamed", "prefix": "strata_dev_"},
        headers=_headers(),
    )
    assert second.status_code == 200
    assert first.json()["organization"]["id"] == second.json()["organization"]["id"]
    assert first.json()["api_key"] != second.json()["api_key"]
    assert (
        client.get(
            "/v1/whoami",
            headers={"Authorization": f"Bearer {first.json()['api_key']}"},
        ).status_code
        == 401
    )
    assert (
        client.get(
            "/v1/whoami",
            headers={"Authorization": f"Bearer {second.json()['api_key']}"},
        ).status_code
        == 200
    )


def test_provision_team_isolates_orgs(client: TestClient) -> None:
    a = client.post(
        "/v1/provision/team",
        json={"slug": "craft-and-logic", "name": "Craft & Logic", "prefix": "strata_dev_"},
        headers=_headers(),
    )
    b = client.post(
        "/v1/provision/team",
        json={"slug": "htc", "name": "HTC", "prefix": "strata_dev_"},
        headers=_headers(),
    )
    assert a.status_code == 200 and b.status_code == 200
    assert a.json()["organization"]["id"] != b.json()["organization"]["id"]


def test_provision_team_rejects_bad_slug(client: TestClient) -> None:
    response = client.post(
        "/v1/provision/team",
        json={"slug": "Bad_Slug!", "name": "Nope", "prefix": "strata_dev_"},
        headers=_headers(),
    )
    assert response.status_code == 422
