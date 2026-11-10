from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    inspect,
    select,
)
from sqlalchemy.exc import IntegrityError

BOOTSTRAP_KEY = "strata_dev_example"


def _auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {BOOTSTRAP_KEY}"}


def _encrypt(payload: dict) -> tuple[str, str]:
    import base64
    import json

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    plain = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    nonce = b"\x02" * 12
    ciphertext = AESGCM(bytes(range(32))).encrypt(nonce, plain, None)
    return base64.b64encode(nonce).decode(), base64.b64encode(ciphertext).decode()


def seal_document(payload: dict) -> dict:
    import hashlib

    sealed = dict(payload)
    path = sealed["path"]
    body = sealed.get("body") or ""
    title = sealed.get("title") or ""
    nonce, ciphertext = _encrypt({"body": body, "path": path, "title": title, "v": 1})
    sealed["body"] = ""
    sealed["title"] = ""
    sealed["path_hash"] = hashlib.sha256(path.encode()).hexdigest()
    sealed["body_hash"] = hashlib.sha256(body.encode()).hexdigest()
    sealed["content_nonce"] = nonce
    sealed["content_ciphertext"] = ciphertext
    sealed["dek_version"] = 1
    sealed["content_state"] = "sealed"
    return sealed


def seal_comment(body: str) -> dict:
    nonce, ciphertext = _encrypt({"body": body, "v": 1})
    return {
        "body": "",
        "content_nonce": nonce,
        "content_ciphertext": ciphertext,
        "dek_version": 1,
    }


def test_create_and_search_shared_document(client: TestClient) -> None:
    payload = {
        "path": ".md/handoff/cxl-strata/2026-06-30T12-00-00Z.md",
        "kind": "handoff",
        "project_slug": "cxl-strata",
        "title": "Workspace knowledge rollout",
        "body": "# Handoff\n\nIndexed STRATA workspace knowledge hybrid flow.",
    }
    payload = seal_document(payload)
    create = client.post("/v1/documents", json=payload, headers=_auth_headers())
    assert create.status_code == 200
    body = create.json()
    assert body["author_name"]
    assert body["body"] == ""
    assert body["content_state"] == "sealed"
    doc_id = body["id"]

    search = client.get(
        "/v1/documents/search",
        params={"q": "workspace knowledge"},
        headers=_auth_headers(),
    )
    assert search.status_code == 200
    ids = [row["id"] for row in search.json()["results"]]
    assert doc_id not in ids

    get_one = client.get(f"/v1/documents/{doc_id}", headers=_auth_headers())
    assert get_one.status_code == 200
    assert get_one.json()["body"] == ""
    assert "hybrid flow" not in get_one.json()["body"]


def test_metadata_only_document_responses_omit_body(client: TestClient) -> None:
    payload = {
        "path": ".md/handoff/cxl-strata/metadata-only.md",
        "kind": "handoff",
        "project_slug": "cxl-strata",
        "title": "Metadata-only response",
        "body": "This body must not appear in metadata responses.",
    }
    payload = seal_document(payload)
    create = client.post("/v1/documents", json=payload, headers=_auth_headers())
    assert create.status_code == 200

    listing = client.get(
        "/v1/documents",
        params={"project": "cxl-strata"},
        headers=_auth_headers(),
    )
    assert listing.status_code == 200
    listed = next(row for row in listing.json()["results"] if row["path_hash"] == payload["path_hash"])
    assert "body" not in listed


def test_upsert_reuses_unique_organization_path(client: TestClient) -> None:
    path = ".md/blueprints/unique-upsert.md"
    first_payload = seal_document({"path": path, "kind": "blueprint", "body": "first body"})
    second_payload = seal_document({"path": path, "kind": "blueprint", "body": "second body"})
    first = client.post("/v1/documents", json=first_payload, headers=_auth_headers())
    second = client.post("/v1/documents", json=second_payload, headers=_auth_headers())

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["body"] == ""

    listing = client.get(
        "/v1/documents",
        params={"include_body": True},
        headers=_auth_headers(),
    )
    matches = [row for row in listing.json()["results"] if row["path_hash"] == first_payload["path_hash"]]
    assert len(matches) == 1


def test_delete_shared_document_removes_it_from_remote_search(client: TestClient) -> None:
    payload = {
        "path": ".md/handoff/cxl-strata/2026-07-01T12-00-00Z.md",
        "kind": "handoff",
        "project_slug": "cxl-strata",
        "title": "Remote delete target",
        "body": "# Handoff\n\nThis shared document should be deleted remotely.",
    }
    payload = seal_document(payload)
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
    batch["documents"] = [seal_document(batch["documents"][0])]
    response = client.post(
        "/v1/documents/import-batch", json=batch, headers=_auth_headers()
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["synced"]) == 1
    assert not data["failed"]
    synced = data["synced"][0]
    assert synced["path"] == ".md/blueprints/cxl-strata.md"
    assert synced["remote_id"]
    assert synced["body_hash"]
    assert synced["updated_at"]


def test_import_batch_rejects_scratch_paths(client: TestClient) -> None:
    batch = {
        "documents": [
            {
                "path": ".codex/.tmp/plugins/plugins/zoom/skills/zoom/SKILL.md",
                "kind": "rule",
                "title": "Plugin cache dump",
                "body": "# Not team knowledge\n",
            },
            {
                "path": ".md/handoff/cxl-strata/2026-07-08T12-00-00Z.md",
                "kind": "handoff",
                "project_slug": "cxl-strata",
                "title": "Legit handoff",
                "body": "# Handoff\n\nReal knowledge.",
            },
        ]
    }
    batch["documents"][1] = seal_document(batch["documents"][1])
    response = client.post(
        "/v1/documents/import-batch", json=batch, headers=_auth_headers()
    )
    assert response.status_code == 200
    data = response.json()
    assert [row["path"] for row in data["synced"]] == [
        ".md/handoff/cxl-strata/2026-07-08T12-00-00Z.md"
    ]
    assert data["failed"] == [
        {
            "path": ".codex/.tmp/plugins/plugins/zoom/skills/zoom/SKILL.md",
            "error": "scratch path not allowed",
        }
    ]


def test_published_at_round_trip_and_ordering(client: TestClient) -> None:
    older = {
        "path": ".md/handoff/cxl-strata/2026-06-01T08-00-00Z.md",
        "kind": "handoff",
        "project_slug": "cxl-strata",
        "title": "Older published handoff",
        "body": "# Handoff\n\nOlder published document.",
        "published_at": "2026-06-01T08:00:00Z",
    }
    newer = {
        "path": ".md/handoff/cxl-strata/2026-07-01T08-00-00Z.md",
        "kind": "handoff",
        "project_slug": "cxl-strata",
        "title": "Newer published handoff",
        "body": "# Handoff\n\nNewer published document.",
        "published_at": "2026-07-01T08:00:00Z",
    }
    # Create the newer one first so ordering must come from published_at,
    # not insertion/created_at order.
    newer = seal_document(newer)
    older = seal_document(older)
    created_newer = client.post("/v1/documents", json=newer, headers=_auth_headers())
    created_older = client.post("/v1/documents", json=older, headers=_auth_headers())
    assert created_newer.status_code == 200
    assert created_older.status_code == 200
    assert created_newer.json()["published_at"].startswith("2026-07-01T08:00:00")

    listing = client.get(
        "/v1/documents",
        params={"project": "cxl-strata"},
        headers=_auth_headers(),
    )
    assert listing.status_code == 200
    results = listing.json()["results"]
    hashes = [row["path_hash"] for row in results]
    assert hashes.index(newer["path_hash"]) < hashes.index(older["path_hash"])


def test_list_pagination_uses_id_to_break_published_at_ties(client: TestClient) -> None:
    published_at = "2026-07-01T08:00:00Z"
    created = []
    for suffix in ("a", "b", "c"):
        response = client.post(
            "/v1/documents",
            json=seal_document({
                "path": f".md/handoff/cxl-strata/tied-{suffix}.md",
                "kind": "handoff",
                "project_slug": "pagination-ties",
                "body": f"tied document {suffix}",
                "published_at": published_at,
            }),
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        created.append(response.json()["id"])

    paged_ids = []
    for offset in range(3):
        response = client.get(
            "/v1/documents",
            params={
                "project": "pagination-ties",
                "limit": 1,
                "offset": offset,
            },
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        paged_ids.append(response.json()["results"][0]["id"])

    assert paged_ids == sorted(created, reverse=True)
    assert len(set(paged_ids)) == 3


def test_document_comments_create_and_list(client: TestClient) -> None:
    payload = {
        "path": ".md/handoff/cxl-strata/2026-07-02T12-00-00Z.md",
        "kind": "handoff",
        "project_slug": "cxl-strata",
        "title": "Commented handoff",
        "body": "# Handoff\n\nDocument that receives comments.",
    }
    payload = seal_document(payload)
    create = client.post("/v1/documents", json=payload, headers=_auth_headers())
    assert create.status_code == 200
    doc_id = create.json()["id"]

    comment = client.post(
        f"/v1/documents/{doc_id}/comments",
        json=seal_comment("Reviewed — deploy steps confirmed."),
        headers=_auth_headers(),
    )
    assert comment.status_code == 200
    comment_body = comment.json()
    assert comment_body["body"] == ""
    assert comment_body["content_state"] == "sealed"
    assert comment_body["author_name"]

    listing = client.get(f"/v1/documents/{doc_id}/comments", headers=_auth_headers())
    assert listing.status_code == 200
    results = listing.json()["results"]
    assert len(results) == 1
    assert results[0]["id"] == comment_body["id"]

    get_one = client.get(f"/v1/documents/{doc_id}", headers=_auth_headers())
    assert get_one.status_code == 200
    assert get_one.json()["comments"][0]["body"] == ""
    assert get_one.json()["comments"][0]["content_state"] == "sealed"

    missing = client.post(
        "/v1/documents/does-not-exist/comments",
        json={"body": "nope"},
        headers=_auth_headers(),
    )
    assert missing.status_code == 404


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
    assert data["synced"] == []
    assert data["failed"]
    assert "sealed" in data["failed"][0]["error"]
    assert "supersecret123" not in response.text


def test_migration_004_deduplicates_reparents_and_enforces_uniqueness() -> None:
    engine = create_engine("sqlite://")
    metadata = MetaData()
    organizations = Table(
        "organizations",
        metadata,
        Column("id", String(36), primary_key=True),
    )
    documents = Table(
        "shared_documents",
        metadata,
        Column("id", String(36), primary_key=True),
        Column("organization_id", String(36), nullable=False),
        Column("path", Text, nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
        Column("shared_at", DateTime(timezone=True), nullable=False),
        Column("updated_at", DateTime(timezone=True), nullable=False),
    )
    comments = Table(
        "shared_document_comments",
        metadata,
        Column("id", String(36), primary_key=True),
        Column(
            "document_id",
            String(36),
            ForeignKey("shared_documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )
    sections = Table(
        "shared_document_sections",
        metadata,
        Column("id", String(36), primary_key=True),
        Column(
            "document_id",
            String(36),
            ForeignKey("shared_documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )
    metadata.create_all(engine)

    migration_path = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "004_shared_document_org_path_unique.py"
    )
    spec = importlib.util.spec_from_file_location("migration_004", migration_path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert len(migration.revision) <= 32

    old_at = datetime(2026, 7, 1, tzinfo=timezone.utc)
    new_at = datetime(2026, 7, 2, tzinfo=timezone.utc)
    with engine.begin() as connection:
        connection.execute(organizations.insert().values(id="org-1"))
        connection.execute(
            documents.insert(),
            [
                {
                    "id": "old-id",
                    "organization_id": "org-1",
                    "path": ".md/handoff/duplicate.md",
                    "created_at": old_at,
                    "shared_at": old_at,
                    "updated_at": old_at,
                },
                {
                    "id": "new-id",
                    "organization_id": "org-1",
                    "path": ".md/handoff/duplicate.md",
                    "created_at": old_at,
                    "shared_at": new_at,
                    "updated_at": new_at,
                },
            ],
        )
        connection.execute(comments.insert().values(id="comment-1", document_id="old-id"))
        connection.execute(sections.insert().values(id="section-1", document_id="old-id"))

        original_op = migration.op
        migration.op = Operations(MigrationContext.configure(connection))
        try:
            migration.upgrade()
        finally:
            migration.op = original_op

        rows = connection.execute(select(documents.c.id)).scalars().all()
        assert rows == ["new-id"]
        assert connection.scalar(select(comments.c.document_id)) == "new-id"
        assert connection.scalar(select(sections.c.document_id)) == "new-id"

        unique_constraints = inspect(connection).get_unique_constraints("shared_documents")
        assert any(
            constraint["column_names"] == ["organization_id", "path"]
            for constraint in unique_constraints
        )
        with pytest.raises(IntegrityError):
            connection.execute(
                documents.insert().values(
                    id="another-id",
                    organization_id="org-1",
                    path=".md/handoff/duplicate.md",
                    created_at=new_at,
                    shared_at=new_at,
                    updated_at=new_at,
                )
            )
