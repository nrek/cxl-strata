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
