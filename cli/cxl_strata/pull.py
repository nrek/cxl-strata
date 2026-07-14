"""Pull shared documents from central API into local SQLite."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from . import api_client
from .path_guard import is_scratch_path
from .workspace_index import db, storage
from .workspace_index.parsers import doc_id_for_path

_PAGE_SIZE = 200


def _doc_path(row: dict[str, Any]) -> str:
    return row.get("path") or f"shared/{row.get('id')}"


def _remote_updated(row: dict[str, Any]) -> str | None:
    return row.get("updated_at") or row.get("remote_updated_at")


def _normalize_iso(value: Any) -> str | None:
    if not value:
        return None
    raw = str(value).strip()
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return raw
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _is_ignored(existing: Any) -> bool:
    """True when the local row is a sync-ignore tombstone (archived locally)."""
    if existing is None:
        return False
    try:
        return bool(existing["sync_ignored_at"])
    except (KeyError, IndexError, TypeError):
        return False


def _field(existing: Any, key: str, default: Any = None) -> Any:
    if existing is None:
        return default
    try:
        return existing[key]
    except (KeyError, IndexError, TypeError):
        return default


def _should_materialize_rule(rel: str, kind: str | None) -> bool:
    """Shared rules must land on disk for Cursor alwaysApply to pick them up."""
    return (kind or "") == "rule" and rel.startswith(".cursor/rules/") and rel.endswith(".mdc")


def remote_transfer_state(row: dict[str, Any], existing: Any) -> str:
    """Classify a remote row as pull, conflict, unchanged, or ignored."""
    if existing is None:
        return "pull"
    if _is_ignored(existing):
        return "ignored"

    remote_hash = row.get("body_hash")
    seen_hash = _field(existing, "remote_body_hash")
    remote_id = _field(existing, "remote_id")
    local_hash = _field(existing, "body_hash")
    if seen_hash is None and remote_id:
        seen_hash = local_hash
    if seen_hash is None and not remote_id:
        # Compatibility for callers/tests supplying a pre-checkpoint row.
        seen_hash = local_hash

    if remote_hash and seen_hash == remote_hash:
        return "unchanged"

    if not remote_hash:
        current_remote_ts = _normalize_iso(_remote_updated(row))
        seen_remote_ts = _normalize_iso(_field(existing, "remote_updated_at"))
        if current_remote_ts == seen_remote_ts:
            return "unchanged"

    existing_keys = existing.keys() if hasattr(existing, "keys") else ()
    legacy = (
        "last_pushed_body_hash" not in existing_keys
        and "remote_body_hash" not in existing_keys
    )
    last_pushed = _field(existing, "last_pushed_body_hash")
    if last_pushed is None and legacy:
        # Legacy rows had only one hash and were assumed clean.
        last_pushed = local_hash
    local_dirty = (
        (not remote_id and not legacy)
        or last_pushed is None
        or local_hash != last_pushed
    )
    return "conflict" if local_dirty else "pull"


def needs_pull(row: dict[str, Any], existing: Any) -> bool:
    """True only for a safe unseen remote revision."""
    return remote_transfer_state(row, existing) == "pull"


def fetch_all_remote_documents(
    *,
    project: str | None = None,
    repo: str | None = None,
    kind: str | None = None,
    since: str | None = None,
    include_body: bool = False,
    include_comments: bool = False,
    max_rows: int | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    offset = 0
    while max_rows is None or len(rows) < max_rows:
        batch = api_client.list_documents(
            project=project,
            repo=repo,
            kind=kind,
            since=since,
            limit=_PAGE_SIZE,
            offset=offset,
            include_body=include_body,
            include_comments=include_comments,
        )
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < _PAGE_SIZE:
            break
        offset += len(batch)
    return rows if max_rows is None else rows[:max_rows]


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
    conflicts = 0
    pending_paths: list[str] = []
    conflict_paths: list[str] = []
    with db.connect() as conn:
        db.init_db(conn)
        for row in remote_rows:
            rel = _doc_path(row)
            if is_scratch_path(rel):
                continue
            existing = conn.execute(
                "SELECT body_hash, remote_id, remote_updated_at, remote_body_hash,"
                " last_pushed_body_hash, sync_ignored_at"
                " FROM documents WHERE path = ?",
                (rel,),
            ).fetchone()
            state = remote_transfer_state(row, existing)
            if state == "pull":
                pending += 1
                pending_paths.append(rel)
            elif state == "conflict":
                conflicts += 1
                conflict_paths.append(rel)
    return {
        "pending": pending,
        "conflicts": conflicts,
        "pending_paths": pending_paths,
        "conflict_paths": conflict_paths,
        "total_remote": len(remote_rows),
    }


def pull_documents(
    *,
    project: str | None = None,
    repo: str | None = None,
    kind: str | None = None,
    since: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    remote_rows = fetch_all_remote_documents(
        project=project,
        repo=repo,
        kind=kind,
        since=since,
        include_body=True,
        include_comments=True,
        max_rows=limit,
    )
    pulled = 0
    skipped = 0
    ignored = 0
    blocked = 0
    comments_pulled = 0
    materialized = 0
    conflicts = 0

    with db.connect() as conn:
        db.init_db(conn)
        for row in remote_rows:
            rel = _doc_path(row)
            if is_scratch_path(rel):
                blocked += 1
                continue
            existing = conn.execute(
                "SELECT body_hash, remote_id, remote_updated_at, remote_body_hash,"
                " last_pushed_body_hash, sync_ignored_at"
                " FROM documents WHERE path = ?",
                (rel,),
            ).fetchone()
            if _is_ignored(existing):
                ignored += 1
                continue
            remote_updated = _normalize_iso(_remote_updated(row))
            comments_pulled += _pull_comments(conn, rel, row.get("comments"))
            state = remote_transfer_state(row, existing)
            if state == "conflict":
                conflicts += 1
                continue
            if state != "pull":
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
                "published_at": row.get("published_at") or row.get("created_at"),
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
                "last_pushed_body_hash": row.get("body_hash") or "",
                "remote_body_hash": row.get("body_hash") or "",
            }
            if _should_materialize_rule(rel, row.get("kind")):
                storage.write_markdown_file(rel, row.get("body") or "")
                payload["storage"] = "file"
                payload["indexed_file_body_hash"] = row.get("body_hash") or ""
                materialized += 1
            db.upsert_document(conn, payload)
            pulled += 1

    return {
        "pulled": pulled,
        "skipped": skipped,
        "ignored": ignored,
        "blocked": blocked,
        "comments_pulled": comments_pulled,
        "materialized": materialized,
        "conflicts": conflicts,
        "total_remote": len(remote_rows),
    }


def _pull_comments(conn: Any, rel: str, comments: Any) -> int:
    """Mirror remote document comments into the local SQLite cache."""
    if not isinstance(comments, list):
        return 0
    count = 0
    for comment in comments:
        remote_comment_id = comment.get("id")
        if not remote_comment_id:
            continue
        db.upsert_remote_comment(
            conn,
            document_path=rel,
            remote_comment_id=str(remote_comment_id),
            body=comment.get("body") or "",
            author_name=comment.get("author_name"),
            author_email=comment.get("author_email"),
            created_at=comment.get("created_at"),
        )
        count += 1
    return count
