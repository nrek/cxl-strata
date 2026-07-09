"""Compare filesystem artifacts against local SQLite for Sync Local review."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import db
from ..content_safety import find_secret_markers, redact_secret_markers
from .indexer import discover_files, index_file
from . import paths
from .parsers import infer_published_at
from .queries import _kinds_filter, _with_sync_status, effective_author_name, filter_by_author


def _published_iso(rel: str, db_row: dict[str, Any] | None, fallback: str) -> str:
    """Published date from index, filename stamp, or activity fallback."""
    if db_row and db_row.get("published_at"):
        return str(db_row["published_at"])
    inferred = infer_published_at(
        filename=rel.rsplit("/", 1)[-1],
        title=db_row.get("title") if db_row else None,
    )
    return inferred or fallback


def _mtime_iso(path: Path) -> str:
    ts = path.stat().st_mtime
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _file_hash(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    return hashlib.sha256(text.encode()).hexdigest()


def _preview(text: str, limit: int = 180) -> str:
    flat = " ".join(text.split())
    return flat[:limit] + ("…" if len(flat) > limit else "")


def _project_from_path(rel: str) -> str | None:
    parts = rel.replace("\\", "/").split("/")
    if len(parts) >= 3 and parts[0] == ".md" and parts[1] == "handoff":
        return parts[2]
    if len(parts) >= 3 and parts[0] == ".md" and parts[1] == "blueprints":
        return parts[2].replace(".md", "")
    return None


def _local_edit_after_sync(db_row: dict[str, Any], mtime: str | None) -> bool:
    """True when the on-disk file was edited after the last pull/share.

    After Pull from Remote the SQLite row is authoritative; a lagging disk
    copy must not look like an outbound Sync to Remote candidate.
    """
    if not mtime:
        return False
    synced_at = db_row.get("synced_at") or db_row.get("shared_at")
    if not synced_at:
        return True
    return str(mtime) > str(synced_at)


def _local_share_status(
    db_row: dict[str, Any] | None,
    *,
    body_hash: str | None = None,
    mtime: str | None = None,
) -> tuple[str, str]:
    local_status = "indexed"
    share_status = "not shared"
    if db_row and db_row.get("sync_ignored_at"):
        return "ignored", "ignored"
    if db_row is None:
        local_status = "new"
    elif body_hash is not None and db_row.get("body_hash") != body_hash:
        local_status = "changed"
    elif db_row.get("storage") == "db_only":
        local_status = "db_only"

    if db_row and db_row.get("remote_id"):
        share_status = "shared"
        if local_status == "changed":
            if _local_edit_after_sync(db_row, mtime):
                share_status = "remote changed"
            else:
                # Pulled/shared DB is newer than disk — not an outbound sync.
                local_status = "indexed"
                share_status = "shared"

    return local_status, share_status


def _activity_iso(mtime: str, db_row: dict[str, Any] | None) -> str:
    """Latest local edit or share/index activity for recency sorting."""
    candidates = [mtime]
    if db_row:
        for key in ("synced_at", "shared_at", "updated_at"):
            val = db_row.get(key)
            if val:
                candidates.append(str(val))
    return max(candidates)


def scan_pending(
    *,
    project: str | None = None,
    kind: str | None = None,
    kinds: list[str] | None = None,
    author: str | None = None,
    show_all: bool = False,
) -> list[dict[str, Any]]:
    """Return local artifacts that are new/changed/unshared vs SQLite."""
    rows: list[dict[str, Any]] = []
    kind_list = _kinds_filter(kind, kinds)

    with db.connect() as conn:
        db.init_db(conn)
        indexed = {
            r["path"]: dict(r)
            for r in conn.execute(
                """
                SELECT path, title, body_hash, storage, origin, remote_id, shared_at,
                       synced_at, author_name, updated_at, published_at, sync_ignored_at,
                       sync_ignore_reason, sync_locked
                FROM documents
                """
            ).fetchall()
        }

    for file_kind, path in discover_files():
        if kind_list and file_kind not in kind_list:
            continue
        rel = path.relative_to(paths.WORKSPACE_ROOT).as_posix()
        db_row = indexed.get(rel)
        if db_row and db_row.get("sync_ignored_at"):
            continue
        if project:
            doc_project = db_row.get("project") if db_row else _project_from_path(rel)
            if doc_project != project:
                continue

        try:
            body_hash = _file_hash(path)
            mtime = _mtime_iso(path)
        except OSError:
            continue

        local_status, share_status = _local_share_status(
            db_row, body_hash=body_hash, mtime=mtime
        )

        if not show_all and local_status == "indexed" and share_status == "shared":
            continue

        excerpt = ""
        try:
            excerpt = _preview(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            pass

        row_dict = {
            "path": rel,
            "kind": file_kind,
            "project": (db_row.get("project") if db_row else None) or _project_from_path(rel),
            "updated_at": mtime,
            "published_at": _published_iso(rel, db_row, mtime),
            "local_status": local_status,
            "share_status": share_status,
            "author_name": effective_author_name(db_row),
            "excerpt": excerpt,
            "remote_id": db_row.get("remote_id") if db_row else None,
            "synced_at": db_row.get("synced_at") if db_row else None,
            "sync_ignored_at": db_row.get("sync_ignored_at") if db_row else None,
            "sync_locked": bool(db_row.get("sync_locked")) if db_row else False,
        }
        enriched = _with_sync_status(row_dict)
        enriched["local_status"] = local_status
        enriched["share_status"] = share_status
        rows.append(enriched)

    rows.sort(
        key=lambda r: r.get("published_at") or r.get("updated_at") or "", reverse=True
    )
    _append_db_only_pending(rows, project=project, kinds=kind_list)
    return filter_by_author(rows, author)


def _append_db_only_pending(
    rows: list[dict[str, Any]],
    *,
    project: str | None,
    kinds: list[str] | None = None,
) -> None:
    """Include archived SQLite-only docs that batch sync can still upload."""
    seen = {r["path"] for r in rows}
    clauses = [
        "COALESCE(storage, 'file') = 'db_only'",
        "remote_id IS NULL",
        "sync_ignored_at IS NULL",
        "COALESCE(sync_locked, 0) = 0",
    ]
    params: list[Any] = []
    if project:
        clauses.append("project = ?")
        params.append(project)
    if kinds:
        placeholders = ",".join("?" * len(kinds))
        clauses.append(f"kind IN ({placeholders})")
        params.extend(kinds)

    with db.connect() as conn:
        db.init_db(conn)
        db_rows = conn.execute(
            f"""
            SELECT path, kind, project, title, updated_at, created_at, published_at,
                   origin, remote_id, shared_at, synced_at, sync_ignored_at,
                   sync_ignore_reason, sync_locked, author_name, storage,
                   substr(body, 1, 180) AS excerpt
            FROM documents
            WHERE {" AND ".join(clauses)}
            ORDER BY COALESCE(published_at, created_at, updated_at) DESC
            """,
            params,
        ).fetchall()

    for db_row in db_rows:
        rel = db_row["path"]
        if rel in seen:
            continue
        row_dict = {
            "path": rel,
            "kind": db_row["kind"],
            "project": db_row["project"],
            "updated_at": db_row["updated_at"] or db_row["created_at"],
            "published_at": db_row["published_at"] or db_row["created_at"],
            "local_status": "archived",
            "share_status": "not shared",
            "author_name": effective_author_name(dict(db_row)),
            "excerpt": db_row["excerpt"] or "",
            "remote_id": None,
            "synced_at": db_row["synced_at"],
            "sync_ignored_at": None,
            "sync_locked": bool(db_row["sync_locked"]),
            "storage": "db_only",
            "origin": db_row["origin"] or "local",
        }
        enriched = _with_sync_status(row_dict)
        enriched["local_status"] = "archived"
        enriched["share_status"] = "not shared"
        rows.append(enriched)


def scan_recent_locally_changed(
    *,
    hours: int = 168,
    limit: int = 200,
    kind: str | None = None,
    kinds: list[str] | None = None,
    author: str | None = None,
) -> list[dict[str, Any]]:
    """On-disk files with recent local edit or share activity, newest first."""
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat().replace(
        "+00:00", "Z"
    )
    rows: list[dict[str, Any]] = []
    kind_list = _kinds_filter(kind, kinds)

    with db.connect() as conn:
        db.init_db(conn)
        indexed = {
            r["path"]: dict(r)
            for r in conn.execute(
                """
                SELECT path, kind, project, title, created_at, published_at, origin,
                       remote_id, shared_at, synced_at, updated_at, body_hash,
                       storage, author_name, sync_ignored_at, sync_ignore_reason,
                       sync_locked, substr(body, 1, 180) AS excerpt
                FROM documents
                """
            ).fetchall()
        }

    for file_kind, path in discover_files():
        if kind_list and file_kind not in kind_list:
            continue
        rel = path.relative_to(paths.WORKSPACE_ROOT).as_posix()
        try:
            mtime = _mtime_iso(path)
            body_hash = _file_hash(path)
        except OSError:
            continue

        db_row = indexed.get(rel)
        if db_row and db_row.get("sync_ignored_at"):
            continue
        activity_at = _activity_iso(mtime, db_row)
        if activity_at < since:
            continue

        local_status, share_status = _local_share_status(
            db_row, body_hash=body_hash, mtime=mtime
        )
        excerpt = db_row.get("excerpt") if db_row else ""
        if not excerpt:
            try:
                excerpt = _preview(path.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                excerpt = ""

        item = {
            "path": rel,
            "kind": file_kind,
            "project": (db_row.get("project") if db_row else None) or _project_from_path(rel),
            "title": db_row.get("title") if db_row else None,
            "updated_at": activity_at,
            "mtime": mtime,
            "created_at": (db_row.get("created_at") if db_row else None) or mtime,
            "published_at": _published_iso(rel, db_row, mtime),
            "origin": (db_row.get("origin") if db_row else None) or "local",
            "remote_id": db_row.get("remote_id") if db_row else None,
            "shared_at": db_row.get("shared_at") if db_row else None,
            "synced_at": db_row.get("synced_at") if db_row else None,
            "sync_ignored_at": db_row.get("sync_ignored_at") if db_row else None,
            "sync_ignore_reason": db_row.get("sync_ignore_reason") if db_row else None,
            "sync_locked": bool(db_row.get("sync_locked")) if db_row else False,
            "local_status": local_status,
            "share_status": share_status,
            "author_name": effective_author_name(db_row),
            "excerpt": excerpt,
        }
        rows.append(_with_sync_status(item))

    rows.sort(
        key=lambda r: r.get("published_at") or r.get("updated_at") or "", reverse=True
    )
    filtered = filter_by_author(rows, author)
    return filtered[:limit]


def scan_potential_secret_files(
    *,
    kind: str | None = None,
    kinds: list[str] | None = None,
    author: str | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Local docs containing secret-like values that STRATA will redact before sync."""
    rows: list[dict[str, Any]] = []
    kind_list = _kinds_filter(kind, kinds)

    with db.connect() as conn:
        db.init_db(conn)
        indexed = {
            r["path"]: dict(r)
            for r in conn.execute(
                """
                SELECT path, kind, project, title, created_at, published_at, origin,
                       remote_id, shared_at, synced_at, updated_at, body_hash,
                       storage, author_name, sync_ignored_at, sync_ignore_reason,
                       sync_locked
                FROM documents
                """
            ).fetchall()
        }

    for file_kind, path in discover_files():
        if kind_list and file_kind not in kind_list:
            continue
        rel = path.relative_to(paths.WORKSPACE_ROOT).as_posix()
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            body_hash = hashlib.sha256(text.encode()).hexdigest()
            mtime = _mtime_iso(path)
        except OSError:
            continue

        markers = find_secret_markers(text)
        if not markers:
            continue

        db_row = indexed.get(rel)
        if db_row and db_row.get("sync_ignored_at"):
            continue
        local_status, share_status = _local_share_status(
            db_row, body_hash=body_hash, mtime=mtime
        )
        item = {
            "path": rel,
            "kind": file_kind,
            "project": (db_row.get("project") if db_row else None) or _project_from_path(rel),
            "title": db_row.get("title") if db_row else None,
            "updated_at": _activity_iso(mtime, db_row),
            "mtime": mtime,
            "created_at": (db_row.get("created_at") if db_row else None) or mtime,
            "published_at": _published_iso(rel, db_row, mtime),
            "origin": (db_row.get("origin") if db_row else None) or "local",
            "remote_id": db_row.get("remote_id") if db_row else None,
            "shared_at": db_row.get("shared_at") if db_row else None,
            "synced_at": db_row.get("synced_at") if db_row else None,
            "sync_ignored_at": db_row.get("sync_ignored_at") if db_row else None,
            "sync_ignore_reason": db_row.get("sync_ignore_reason") if db_row else None,
            "sync_locked": bool(db_row.get("sync_locked")) if db_row else False,
            "local_status": local_status,
            "share_status": share_status,
            "author_name": effective_author_name(db_row),
            "excerpt": _preview(redact_secret_markers(text)),
            "redaction_count": len(markers),
        }
        rows.append(_with_sync_status(item))

    rows.sort(
        key=lambda r: r.get("published_at") or r.get("updated_at") or "", reverse=True
    )
    filtered = filter_by_author(rows, author)
    return filtered[:limit]


def index_path_only(path: str) -> bool:
    fp = paths.WORKSPACE_ROOT / path.replace("\\", "/")
    if not fp.is_file():
        return False
    with db.connect() as conn:
        db.init_db(conn)
        return index_file(conn, fp.resolve())


def index_paths(file_paths: list[str]) -> dict[str, int]:
    from .indexer import index_paths as _index_paths

    resolved = [paths.WORKSPACE_ROOT / p.replace("\\", "/") for p in file_paths]
    return _index_paths(resolved)
