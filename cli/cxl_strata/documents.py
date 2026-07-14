"""Stash local workspace documents to central STRATA API."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import api_client, local_store
from .content_safety import redact_secret_markers
from .path_guard import SCRATCH_REASON, is_scratch_path
from .workspace_index import db, queries
from .workspace_index.indexer import index_file
from .workspace_index.parsers import infer_published_at
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
            "published_at": doc.get("published_at") or doc.get("created_at"),
        }
    body = redact_secret_markers(body)
    return {
        "path": rel_path,
        "kind": kind or "handoff",
        "title": Path(rel_path).stem,
        "body": body,
        "body_hash": _body_hash(body),
        "published_at": infer_published_at(filename=Path(rel_path).name),
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
            if is_scratch_path(rel):
                skipped.append({"path": rel, "reason": SCRATCH_REASON})
                continue
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

    comment_errors: list[dict[str, str]] = []
    with db.connect() as conn:
        db.init_db(conn)
        for row in synced:
            db.mark_shared(
                conn,
                path=row.get("path", ""),
                remote_id=row.get("remote_id", ""),
                author_name=author_name,
                author_email=author_email,
                remote_updated_at=row.get("updated_at") or row.get("remote_updated_at"),
                remote_body_hash=row.get("body_hash"),
            )
            comment_errors.extend(
                push_unsynced_comments(
                    conn,
                    path=row.get("path", ""),
                    remote_id=row.get("remote_id", ""),
                )
            )

    result_out = {"synced": synced, "failed": failed, "skipped": skipped}
    if comment_errors:
        result_out["comment_errors"] = comment_errors
    return result_out


def push_unsynced_comments(conn, *, path: str, remote_id: str) -> list[dict[str, str]]:
    """Send local comments that never reached the central API for a shared doc."""
    errors: list[dict[str, str]] = []
    if not remote_id:
        return errors
    for comment in db.unsynced_comments(conn, path):
        try:
            remote = api_client.create_document_comment(
                str(remote_id),
                comment["body"],
                author_name=comment.get("author_name"),
                author_email=comment.get("author_email"),
                created_at=comment.get("created_at"),
            )
            db.mark_comment_synced(
                conn,
                comment_id=comment["id"],
                remote_comment_id=remote.get("id"),
            )
        except Exception as exc:  # noqa: BLE001 - comment push is best-effort
            errors.append({"path": path, "comment_id": comment["id"], "error": str(exc)})
    return errors


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


def archive_paths(
    paths: list[str],
    *,
    reason: str = "archived_local",
) -> dict[str, Any]:
    """Archive docs locally: tombstone rows so sync never re-imports them.

    Local-only — never touches the central API; teammates keep their copies.
    """
    archived: list[str] = []
    missing: list[str] = []
    with db.connect() as conn:
        db.init_db(conn)
        for path in paths:
            rel = path.replace("\\", "/")
            if db.archive_document(conn, path=rel, reason=reason):
                archived.append(rel)
            else:
                missing.append(rel)
    return {"archived": archived, "missing": missing, "count": len(archived)}


def archive_prefix(
    prefix: str,
    *,
    reason: str = "archived_local",
    execute: bool = False,
) -> dict[str, Any]:
    """Archive every non-ignored doc whose path starts with prefix.

    Dry run by default: returns the matching paths without changing anything.
    """
    rel_prefix = prefix.replace("\\", "/")
    with db.connect() as conn:
        db.init_db(conn)
        rows = conn.execute(
            """
            SELECT path FROM documents
            WHERE path LIKE ? || '%' AND sync_ignored_at IS NULL
            ORDER BY path
            """,
            (rel_prefix,),
        ).fetchall()
    paths = [r["path"] for r in rows]
    if not execute:
        return {"would_archive": paths, "count": len(paths), "executed": False}
    result = archive_paths(paths, reason=reason)
    result["executed"] = True
    return result


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
            "(remote_id IS NULL OR last_pushed_body_hash IS NULL"
            " OR body_hash != last_pushed_body_hash)",
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
