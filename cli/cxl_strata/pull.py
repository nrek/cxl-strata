"""Pull shared documents from central API into local SQLite."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from . import api_client
from .path_guard import is_scratch_path
from .workspace_index import db, storage
from .workspace_index.parsers import doc_id_for_path

_PAGE_SIZE = 200
_CATALOG_N_RE = re.compile(r"_(\d+)$")


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


def _split_path_name(rel: str) -> tuple[str, str, str]:
    """Return (parent_with_slash_or_empty, stem, ext_with_dot_or_empty)."""
    normalized = rel.replace("\\", "/")
    parent, _, name = normalized.rpartition("/")
    if "." in name and not name.startswith("."):
        stem, _, ext = name.rpartition(".")
        return (f"{parent}/" if parent else ""), stem, f".{ext}"
    # Dotfiles / no extension: treat whole name as stem.
    return (f"{parent}/" if parent else ""), name, ""


def catalog_sibling_path(rel: str, *, taken: set[str] | None = None) -> str:
    """Next free sibling path: ``stem_1.ext``, ``stem_2.ext``, …"""
    parent, stem, ext = _split_path_name(rel)
    occupied = taken or set()
    n = 1
    while True:
        candidate = f"{parent}{stem}_{n}{ext}"
        if candidate not in occupied:
            return candidate
        n += 1


def _occupied_paths(conn: Any, rel: str) -> set[str]:
    """Paths that already exist for this document family (canonical + ``_N``)."""
    parent, stem, ext = _split_path_name(rel)
    prefix = f"{parent}{stem}"
    rows = conn.execute(
        "SELECT path FROM documents WHERE path = ? OR path GLOB ?",
        (rel.replace("\\", "/"), f"{prefix}_[0-9]*{ext}"),
    ).fetchall()
    occupied = {str(r["path"]) for r in rows}
    occupied.add(rel.replace("\\", "/"))
    return occupied


def _existing_catalog_for_hash(conn: Any, rel: str, body_hash: str | None) -> str | None:
    """Return an existing ``_N`` sibling that already holds this remote body."""
    if not body_hash:
        return None
    parent, stem, ext = _split_path_name(rel)
    prefix = f"{parent}{stem}"
    rows = conn.execute(
        "SELECT path, body_hash FROM documents WHERE path GLOB ?",
        (f"{prefix}_[0-9]*{ext}",),
    ).fetchall()
    for row in rows:
        path = str(row["path"])
        # Only numeric suffixes: stem_1, stem_12 — not stem_backup.
        name = path.rsplit("/", 1)[-1]
        name_stem = name[: -len(ext)] if ext and name.endswith(ext) else name
        if not _CATALOG_N_RE.search(name_stem):
            continue
        if row["body_hash"] == body_hash:
            return path
    return None


def _catalog_title(row: dict[str, Any], catalog_path: str) -> str:
    base = (row.get("title") or catalog_path.rsplit("/", 1)[-1]).strip()
    author = (row.get("author_name") or row.get("author_email") or "").strip()
    suffix = catalog_path.rsplit("/", 1)[-1]
    marker = _CATALOG_N_RE.search(suffix.rsplit(".", 1)[0])
    n = marker.group(1) if marker else "?"
    if author:
        return f"{base} · {author} _{n}"
    return f"{base} · remote _{n}"


def _ack_remote_revision(
    conn: Any,
    rel: str,
    *,
    remote_hash: str | None,
    remote_updated: str | None,
) -> None:
    """Record that the remote tip was seen without overwriting the local body."""
    conn.execute(
        """
        UPDATE documents
        SET remote_body_hash = COALESCE(?, remote_body_hash),
            remote_updated_at = COALESCE(?, remote_updated_at)
        WHERE path = ?
        """,
        (remote_hash or None, remote_updated, rel),
    )


def remote_transfer_state(row: dict[str, Any], existing: Any) -> str:
    """Classify a remote row as pull, catalog, unchanged, or ignored.

    Simultaneous local + remote divergence used to be a blocking conflict.
    Strata now auto-catalogs the remote revision under ``stem_N.ext`` and
    keeps the dirty local revision at the canonical path.
    """
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
    return "catalog" if local_dirty else "pull"


def needs_pull(row: dict[str, Any], existing: Any) -> bool:
    """True when a remote revision should be transferred (pull or catalog)."""
    return remote_transfer_state(row, existing) in {"pull", "catalog"}


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
    pending_paths: list[str] = []
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
            if state in {"pull", "catalog"}:
                pending += 1
                pending_paths.append(rel)
    return {
        "pending": pending,
        # Retained for older UI clients; divergence is auto-catalogued now.
        "conflicts": 0,
        "pending_paths": pending_paths,
        "conflict_paths": [],
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
    catalogued = 0
    skipped = 0
    ignored = 0
    blocked = 0
    comments_pulled = 0
    materialized = 0

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
            if state == "catalog":
                if _catalog_remote_revision(
                    conn,
                    row,
                    rel=rel,
                    remote_updated=remote_updated,
                ):
                    catalogued += 1
                    pulled += 1
                else:
                    skipped += 1
                continue
            if state != "pull":
                skipped += 1
                continue

            payload = _shared_payload(
                row,
                rel=rel,
                remote_updated=remote_updated,
                remote_id=row.get("id"),
                last_pushed_body_hash=row.get("body_hash") or "",
            )
            if _should_materialize_rule(rel, row.get("kind")):
                storage.write_markdown_file(rel, row.get("body") or "")
                payload["storage"] = "file"
                payload["indexed_file_body_hash"] = row.get("body_hash") or ""
                materialized += 1
            db.upsert_document(conn, payload)
            pulled += 1

    return {
        "pulled": pulled,
        "catalogued": catalogued,
        "skipped": skipped,
        "ignored": ignored,
        "blocked": blocked,
        "comments_pulled": comments_pulled,
        "materialized": materialized,
        "conflicts": 0,
        "total_remote": len(remote_rows),
    }


def _shared_payload(
    row: dict[str, Any],
    *,
    rel: str,
    remote_updated: str | None,
    remote_id: Any,
    last_pushed_body_hash: str,
    title: str | None = None,
) -> dict[str, Any]:
    return {
        "id": doc_id_for_path(rel),
        "kind": row.get("kind") or "handoff",
        "project": row.get("project_slug") or row.get("project"),
        "path": rel,
        "title": title if title is not None else row.get("title"),
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
        "remote_id": remote_id,
        "author_name": row.get("author_name"),
        "author_email": row.get("author_email"),
        "shared_at": row.get("shared_at") or row.get("created_at"),
        "synced_at": db.utc_now(),
        "remote_updated_at": remote_updated,
        "last_pushed_body_hash": last_pushed_body_hash,
        "remote_body_hash": row.get("body_hash") or "",
    }


def _catalog_remote_revision(
    conn: Any,
    row: dict[str, Any],
    *,
    rel: str,
    remote_updated: str | None,
) -> bool:
    """Keep local dirty path; store remote tip as ``stem_N`` sibling (db_only).

    Returns True when a new catalog row was written (or an existing twin was
    refreshed). Always acknowledges the remote tip on the canonical path so
    the same revision is not catalogued again.
    """
    remote_hash = row.get("body_hash") or ""
    existing_catalog = _existing_catalog_for_hash(conn, rel, remote_hash or None)
    if existing_catalog:
        _ack_remote_revision(
            conn, rel, remote_hash=remote_hash or None, remote_updated=remote_updated
        )
        return False

    catalog_rel = catalog_sibling_path(rel, taken=_occupied_paths(conn, rel))
    payload = _shared_payload(
        row,
        rel=catalog_rel,
        remote_updated=remote_updated,
        # No remote_id: deleting a catalog twin must not delete the canonical
        # remote document. Twin can sync later as its own shared path.
        remote_id=None,
        last_pushed_body_hash="",
        title=_catalog_title(row, catalog_rel),
    )
    payload["storage"] = "db_only"
    db.upsert_document(conn, payload)
    _ack_remote_revision(
        conn, rel, remote_hash=remote_hash or None, remote_updated=remote_updated
    )
    return True


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
