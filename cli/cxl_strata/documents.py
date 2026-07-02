"""Stash local workspace documents to central STRATA API."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import api_client, local_store
from .content_safety import redact_secret_markers
from .workspace_index import db, queries
from .workspace_index.indexer import index_file
from .workspace_index.paths import WORKSPACE_ROOT


def _author_from_config() -> tuple[str | None, str | None]:
    cfg = local_store.load_config()
    return cfg.get("actor_name"), cfg.get("actor_email")


def _document_payload(rel_path: str, body: str, kind: str | None = None) -> dict[str, Any]:
    with db.connect() as conn:
        db.init_db(conn)
        doc = queries.knowledge_get(conn, rel_path)
    if doc:
        body = redact_secret_markers(doc.get("body") or body)
        return {
            "path": rel_path,
            "kind": doc.get("kind") or kind or "handoff",
            "project_slug": doc.get("project"),
            "title": doc.get("title"),
            "body": body,
            "body_hash": _body_hash(body),
            "plan_status": doc.get("plan_status"),
            "linear_task_id": doc.get("linear_task_id"),
            "storage_state": doc.get("storage") or "file",
        }
    body = redact_secret_markers(body)
    return {
        "path": rel_path,
        "kind": kind or "handoff",
        "title": Path(rel_path).stem,
        "body": body,
        "body_hash": _body_hash(body),
    }


def _body_hash(body: str) -> str:
    import hashlib

    return hashlib.sha256(body.encode()).hexdigest()


def stash_paths(
    paths: list[str],
    *,
    author_name: str | None = None,
    author_email: str | None = None,
    allow_locked: bool = False,
) -> dict[str, Any]:
    cfg_author = _author_from_config()
    author_name = author_name or cfg_author[0]
    author_email = author_email or cfg_author[1]

    documents: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []

    with db.connect() as conn:
        db.init_db(conn)
        for rel in paths:
            rel = rel.replace("\\", "/")
            fp = WORKSPACE_ROOT / rel
            if fp.is_file():
                index_file(conn, fp.resolve())
            doc = queries.knowledge_get(conn, rel)
            if not doc:
                errors.append({"path": rel, "error": "not indexed"})
                continue
            if not allow_locked and doc.get("sync_locked"):
                skipped.append({"path": rel, "reason": "sync_locked"})
                continue
            body = doc.get("body") or ""
            documents.append(_document_payload(rel, body, doc.get("kind")))

    if not documents:
        return {"synced": [], "failed": errors, "skipped": skipped}

    result = api_client.documents_import_batch(documents)
    synced = result.get("synced", [])
    failed = list(result.get("failed", [])) + errors

    with db.connect() as conn:
        db.init_db(conn)
        for row in synced:
            db.mark_shared(
                conn,
                path=row.get("path", ""),
                remote_id=row.get("remote_id", ""),
                author_name=author_name,
                author_email=author_email,
            )

    return {"synced": synced, "failed": failed, "skipped": skipped}


def delete_remote_path(path: str, *, actor_name: str | None = None) -> dict[str, Any]:
    rel = path.replace("\\", "/")
    with db.connect() as conn:
        db.init_db(conn)
        doc = queries.knowledge_get(conn, rel)
    if not doc:
        return {"path": rel, "deleted": False, "error": "not indexed"}

    author = queries.effective_author_name(doc)
    if actor_name:
        if not author or author.strip().lower() != actor_name.strip().lower():
            return {"path": rel, "deleted": False, "error": "not author"}

    remote_id = doc.get("remote_id")
    if not remote_id:
        with db.connect() as conn:
            db.init_db(conn)
            db.mark_remote_deleted(conn, path=rel)
        return {"path": rel, "deleted": True, "remote_id": None}

    api_client.delete_document(str(remote_id))
    with db.connect() as conn:
        db.init_db(conn)
        db.mark_remote_deleted(conn, path=rel)
    return {"path": rel, "remote_id": remote_id, "deleted": True}


def stash_filtered(
    *,
    kind: str | None = None,
    project: str | None = None,
    since: str | None = None,
    path: str | None = None,
    all_docs: bool = False,
) -> dict[str, Any]:
    if path:
        return stash_paths([path])

    with db.connect() as conn:
        db.init_db(conn)
        clauses = [
            "(COALESCE(origin, 'local') != 'shared' OR remote_id IS NULL)",
            "sync_ignored_at IS NULL",
            "COALESCE(sync_locked, 0) = 0",
        ]
        params: list[Any] = []
        if kind:
            clauses.append("kind = ?")
            params.append(kind)
        if project:
            clauses.append("project = ?")
            params.append(project)
        if since:
            clauses.append("updated_at >= ?")
            params.append(since)
        if not all_docs:
            clauses.append("COALESCE(storage, 'file') = 'file'")

        rows = conn.execute(
            f"SELECT path FROM documents WHERE {' AND '.join(clauses)} ORDER BY updated_at DESC",
            params,
        ).fetchall()

    return stash_paths([r["path"] for r in rows])
