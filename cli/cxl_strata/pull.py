"""Pull shared documents from central API into local SQLite."""

from __future__ import annotations

from typing import Any

from . import api_client
from .workspace_index import db
from .workspace_index.parsers import doc_id_for_path

_PAGE_SIZE = 200
_MAX_REMOTE_ROWS = 2000


def _doc_path(row: dict[str, Any]) -> str:
    return row.get("path") or f"shared/{row.get('id')}"


def _remote_updated(row: dict[str, Any]) -> str | None:
    return row.get("updated_at") or row.get("remote_updated_at")


def needs_pull(row: dict[str, Any], existing: Any) -> bool:
    """True when remote row is missing locally or differs from local copy."""
    if existing is None:
        return True
    if existing["body_hash"] != row.get("body_hash"):
        return True
    return existing["remote_updated_at"] != _remote_updated(row)


def fetch_all_remote_documents(
    *,
    project: str | None = None,
    kind: str | None = None,
    since: str | None = None,
    include_body: bool = False,
    max_rows: int = _MAX_REMOTE_ROWS,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    offset = 0
    while len(rows) < max_rows:
        batch = api_client.list_documents(
            project=project,
            kind=kind,
            since=since,
            limit=_PAGE_SIZE,
            offset=offset,
            include_body=include_body,
        )
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < _PAGE_SIZE:
            break
        offset += len(batch)
    return rows[:max_rows]


def count_remote_pending(
    *,
    project: str | None = None,
    kind: str | None = None,
    since: str | None = None,
) -> dict[str, Any]:
    """Count remote documents not yet synced to local SQLite."""
    remote_rows = fetch_all_remote_documents(
        project=project, kind=kind, since=since, include_body=False
    )
    pending = 0
    with db.connect() as conn:
        db.init_db(conn)
        for row in remote_rows:
            rel = _doc_path(row)
            existing = conn.execute(
                "SELECT body_hash, remote_updated_at FROM documents WHERE path = ?",
                (rel,),
            ).fetchone()
            if needs_pull(row, existing):
                pending += 1
    return {"pending": pending, "total_remote": len(remote_rows)}


def pull_documents(
    *,
    project: str | None = None,
    kind: str | None = None,
    since: str | None = None,
    limit: int = _MAX_REMOTE_ROWS,
) -> dict[str, Any]:
    remote_rows = fetch_all_remote_documents(
        project=project,
        kind=kind,
        since=since,
        include_body=True,
        max_rows=limit,
    )
    pulled = 0
    skipped = 0

    with db.connect() as conn:
        db.init_db(conn)
        for row in remote_rows:
            rel = _doc_path(row)
            existing = conn.execute(
                "SELECT body_hash, remote_updated_at FROM documents WHERE path = ?",
                (rel,),
            ).fetchone()
            remote_updated = _remote_updated(row)
            if not needs_pull(row, existing):
                skipped += 1
                continue

            payload = {
                "id": doc_id_for_path(rel),
                "kind": row.get("kind") or "handoff",
                "project": row.get("project_slug") or row.get("project"),
                "path": rel,
                "title": row.get("title"),
                "created_at": row.get("created_at"),
                "updated_at": row.get("updated_at") or remote_updated,
                "body": row.get("body") or "",
                "body_hash": row.get("body_hash") or "",
                "plan_status": row.get("plan_status"),
                "linear_task_id": row.get("linear_task_id"),
                "files_changed": None,
                "deploy_commands": None,
                "tags": None,
                "folder_status": None,
                "status_mismatch": 0,
                "storage": row.get("storage_state") or "db_only",
                "origin": "shared",
                "remote_id": row.get("id"),
                "author_name": row.get("author_name"),
                "author_email": row.get("author_email"),
                "shared_at": row.get("shared_at") or row.get("created_at"),
                "synced_at": db.utc_now(),
                "remote_updated_at": remote_updated,
            }
            db.upsert_document(conn, payload)
            pulled += 1

    return {"pulled": pulled, "skipped": skipped, "total_remote": len(remote_rows)}
