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


def _seal_event(title: str, summary: str) -> dict:
    import base64
    import json

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    plain = json.dumps(
        {
            "details": "",
            "related_files": [],
            "source_ref": "",
            "summary": summary,
            "tags": [],
            "title": title,
            "v": 1,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    nonce = b"\x03" * 12
    ciphertext = AESGCM(bytes(range(32))).encrypt(nonce, plain, None)
    return {
        "project_slug": "cxl-strata",
        "event_type": "implementation_note",
        "title": "",
        "summary": "",
        "content_nonce": base64.b64encode(nonce).decode(),
        "content_ciphertext": base64.b64encode(ciphertext).decode(),
        "dek_version": 1,
    }


def test_plaintext_memory_event_rejected(client: TestClient) -> None:
    payload = {
        "project_slug": "cxl-strata",
        "event_type": "implementation_note",
        "title": "Postgres rollout",
        "summary": "Wired API to PostgreSQL with Alembic migrations.",
        "tags": ["postgres", "alembic"],
    }
    create = client.post("/v1/memory-events", json=payload, headers=_auth_headers())
    assert create.status_code == 422


def test_sealed_memory_event_is_not_searchable(client: TestClient) -> None:
    create = client.post("/v1/memory-events", json=_seal_event("Postgres rollout", "Alembic migrations"), headers=_auth_headers())
    assert create.status_code == 200
    event_id = create.json()["id"]
    assert create.json()["title"] == ""
    assert create.json()["content_state"] == "sealed"

    search = client.get("/v1/search", params={"q": "Alembic"}, headers=_auth_headers())
    assert search.status_code == 200
    ids = [row["id"] for row in search.json()["results"]]
    assert event_id not in ids

    get_one = client.get(f"/v1/memory-events/{event_id}", headers=_auth_headers())
    assert get_one.status_code == 200
    assert get_one.json()["summary"] == ""
    assert "Alembic" not in get_one.json()["summary"]


def test_secret_payload_rejected(client: TestClient) -> None:
    payload = {
        "project_slug": "cxl-strata",
        "event_type": "general_note",
        "title": "bad",
        "summary": "password=supersecret123",
    }
    response = client.post("/v1/memory-events", json=payload, headers=_auth_headers())
    assert response.status_code == 422


def test_org_seal_upgrades_existing_rows(client: TestClient) -> None:
    import base64
    import hashlib
    import json

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from sqlalchemy import select

    from app.models import (
        MemoryEvent,
        Organization,
        Project,
        SharedDocument,
        SharedDocumentComment,
        SharedDocumentSection,
    )

    whoami = client.get("/v1/whoami", headers=_auth_headers())
    assert whoami.status_code == 200
    db = client.db_factory()
    org = db.scalars(select(Organization)).first()
    assert org is not None
    project = Project(organization_id=org.id, slug="legacy", name="legacy")
    db.add(project)
    db.flush()
    event = MemoryEvent(
        organization_id=org.id,
        project_id=project.id,
        project_slug="legacy",
        event_type="implementation_note",
        title="Legacy title",
        summary="Legacy summary stays on the server until sealed.",
        source="local_capture",
        content_state="plaintext",
    )
    document = SharedDocument(
        organization_id=org.id,
        project_id=project.id,
        project_slug="legacy",
        kind="handoff",
        title="Legacy doc",
        path=".md/handoff/legacy.md",
        body="Legacy document body",
        body_hash="abc",
        source="workspace_index",
        author_name="Tester",
        content_state="plaintext",
    )
    db.add(event)
    db.add(document)
    db.flush()
    section = SharedDocumentSection(
        document_id=document.id,
        heading="Legacy heading",
        body="Legacy section body",
        ordinal=0,
        content_state="plaintext",
    )
    comment = SharedDocumentComment(
        document_id=document.id,
        author_name="Tester",
        body="Legacy comment body",
        content_state="plaintext",
    )
    db.add(section)
    db.add(comment)
    db.commit()
    ids = {
        "memory_events": event.id,
        "shared_documents": document.id,
        "shared_document_sections": section.id,
        "shared_document_comments": comment.id,
    }
    db.close()

    backlog = client.get("/v1/org/plaintext-backlog", params={"limit": 25}, headers=_auth_headers())
    assert backlog.status_code == 200
    tables = {row["table"] for row in backlog.json()["results"]}
    assert tables == set(ids)

    dek = bytes(range(32))
    for row in backlog.json()["results"]:
        content = dict(row["content"])
        content["v"] = 1
        plain = json.dumps(content, separators=(",", ":"), sort_keys=True).encode()
        nonce = b"\x04" * 12
        ciphertext = AESGCM(dek).encrypt(nonce, plain, None)
        payload = {
            "table": row["table"],
            "id": row["id"],
            "content_nonce": base64.b64encode(nonce).decode(),
            "content_ciphertext": base64.b64encode(ciphertext).decode(),
            "dek_version": 1,
        }
        if row["table"] == "shared_documents":
            payload["path_hash"] = hashlib.sha256(content["path"].encode()).hexdigest()
        sealed = client.post("/v1/org/seal", json=payload, headers=_auth_headers())
        assert sealed.status_code == 200, sealed.text
        assert sealed.json()["sealed"] is True

    status = client.get("/v1/org/seal-status", headers=_auth_headers())
    assert status.status_code == 200
    assert status.json()["remaining"] == 0
    again = client.post(
        "/v1/org/seal",
        json={
            "table": "memory_events",
            "id": ids["memory_events"],
            "content_nonce": "AAAA",
            "content_ciphertext": "AAAA",
            "dek_version": 1,
        },
        headers=_auth_headers(),
    )
    assert again.status_code == 200
    assert again.json()["sealed"] is False

    stored = client.get(f"/v1/memory-events/{ids['memory_events']}", headers=_auth_headers())
    assert stored.status_code == 200
    assert stored.json()["title"] == ""
    assert stored.json()["summary"] == ""
    assert "Legacy summary" not in stored.text
    rejected = client.post(
        "/v1/memory-events",
        json={
            "project_slug": "legacy",
            "event_type": "general_note",
            "title": "still open",
            "summary": "this must not land",
        },
        headers=_auth_headers(),
    )
    assert rejected.status_code == 422


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
