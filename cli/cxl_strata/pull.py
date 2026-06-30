"""Pull shared documents from central API into local SQLite."""

from __future__ import annotations

from typing import Any

from . import api_client
from .workspace_index import db
from .workspace_index.parsers import doc_id_for_path


def pull_documents(
    *,
    project: str | None = None,
    kind: str | None = None,
    since: str | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    remote_rows = api_client.list_documents(
        project=project, kind=kind, since=since, limit=limit
    )
    pulled = 0
    skipped = 0

    with db.connect() as conn:
        db.init_db(conn)
        for row in remote_rows:
            rel = row.get("path") or f"shared/{row.get('id')}"
            existing = conn.execute(
                "SELECT body_hash, remote_updated_at FROM documents WHERE path = ?",
                (rel,),
            ).fetchone()
            remote_updated = row.get("updated_at") or row.get("remote_updated_at")
            if existing and existing["body_hash"] == row.get("body_hash"):
                if existing["remote_updated_at"] == remote_updated:
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
