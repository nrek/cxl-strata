from __future__ import annotations

from fastapi.testclient import TestClient

BOOTSTRAP_KEY = "strata_dev_example"


def _auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {BOOTSTRAP_KEY}"}


def test_create_and_search_shared_document(client: TestClient) -> None:
    payload = {
        "path": ".md/handoff/cxl-strata/2026-06-30T12-00-00Z.md",
        "kind": "handoff",
        "project_slug": "cxl-strata",
        "title": "Workspace knowledge rollout",
        "body": "# Handoff\n\nIndexed STRATA workspace knowledge hybrid flow.",
    }
    create = client.post("/v1/documents", json=payload, headers=_auth_headers())
    assert create.status_code == 200
    body = create.json()
    assert body["author_name"]
    doc_id = body["id"]

    search = client.get(
        "/v1/documents/search",
        params={"q": "workspace knowledge"},
        headers=_auth_headers(),
    )
    assert search.status_code == 200
    ids = [row["id"] for row in search.json()["results"]]
    assert doc_id in ids

    get_one = client.get(f"/v1/documents/{doc_id}", headers=_auth_headers())
    assert get_one.status_code == 200
    assert "hybrid flow" in get_one.json()["body"]


def test_delete_shared_document_removes_it_from_remote_search(client: TestClient) -> None:
    payload = {
        "path": ".md/handoff/cxl-strata/2026-07-01T12-00-00Z.md",
        "kind": "handoff",
        "project_slug": "cxl-strata",
        "title": "Remote delete target",
        "body": "# Handoff\n\nThis shared document should be deleted remotely.",
    }
    create = client.post("/v1/documents", json=payload, headers=_auth_headers())
    assert create.status_code == 200
    doc_id = create.json()["id"]

    deleted = client.delete(f"/v1/documents/{doc_id}", headers=_auth_headers())
    assert deleted.status_code == 200
    assert deleted.json() == {"id": doc_id, "deleted": True}

    get_one = client.get(f"/v1/documents/{doc_id}", headers=_auth_headers())
    assert get_one.status_code == 404

    search = client.get(
        "/v1/documents/search",
        params={"q": "deleted remotely"},
        headers=_auth_headers(),
    )
    assert search.status_code == 200
    ids = [row["id"] for row in search.json()["results"]]
    assert doc_id not in ids


def test_import_batch_shared_documents(client: TestClient) -> None:
    batch = {
        "documents": [
            {
                "path": ".md/blueprints/cxl-strata.md",
                "kind": "blueprint",
                "project_slug": "cxl-strata",
                "title": "STRATA blueprint",
                "body": "# STRATA\n\nCore function: shared memory.",
            }
        ]
    }
    response = client.post(
        "/v1/documents/import-batch", json=batch, headers=_auth_headers()
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["synced"]) == 1
    assert not data["failed"]


def test_import_batch_redacts_secret_markers(client: TestClient) -> None:
    batch = {
        "documents": [
            {
                "path": ".cursor/plans/draft/secret-plan.md",
                "kind": "plan",
                "project_slug": "commonspace-app",
                "title": "Secret placeholder plan",
                "body": "# Plan\n\nExample password=supersecret123 should be stripped.",
            }
        ]
    }
    response = client.post(
        "/v1/documents/import-batch", json=batch, headers=_auth_headers()
    )

    assert response.status_code == 200
    data = response.json()
    assert len(data["synced"]) == 1
    assert not data["failed"]

    doc_id = data["synced"][0]["remote_id"]
    get_one = client.get(f"/v1/documents/{doc_id}", headers=_auth_headers())
    assert get_one.status_code == 200
    body = get_one.json()["body"]
    assert "supersecret123" not in body
    assert "password=[REDACTED_SECRET]" in body
