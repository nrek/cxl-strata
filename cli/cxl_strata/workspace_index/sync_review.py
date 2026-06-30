"""Compare filesystem artifacts against local SQLite for Sync Local review."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import db
from .indexer import discover_files, index_file
from .paths import WORKSPACE_ROOT


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


def scan_pending(
    *,
    project: str | None = None,
    kind: str | None = None,
    show_all: bool = False,
) -> list[dict[str, Any]]:
    """Return local artifacts that are new/changed/unshared vs SQLite."""
    rows: list[dict[str, Any]] = []

    with db.connect() as conn:
        db.init_db(conn)
        indexed = {
            r["path"]: dict(r)
            for r in conn.execute(
                """
                SELECT path, body_hash, storage, origin, remote_id, shared_at,
                       author_name, updated_at
                FROM documents
                """
            ).fetchall()
        }

    for file_kind, path in discover_files():
        if kind and file_kind != kind:
            continue
        rel = path.relative_to(WORKSPACE_ROOT).as_posix()
        if project:
            doc_project = db_row.get("project") if db_row else _project_from_path(rel)
            if doc_project != project:
                continue

        try:
            body_hash = _file_hash(path)
        except OSError:
            continue

        db_row = indexed.get(rel)
        local_status = "indexed"
        share_status = "not shared"
        if db_row is None:
            local_status = "new"
        elif db_row.get("body_hash") != body_hash:
            local_status = "changed"
        elif db_row.get("storage") == "db_only":
            local_status = "db_only"

        if db_row and db_row.get("remote_id"):
            share_status = "shared"
            if local_status == "changed":
                share_status = "remote changed"

        if not show_all and local_status == "indexed" and share_status == "shared":
            continue

        excerpt = ""
        try:
            excerpt = _preview(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            pass

        rows.append(
            {
                "path": rel,
                "kind": file_kind,
                "project": db_row.get("project") if db_row else None,
                "updated_at": _mtime_iso(path),
                "local_status": local_status,
                "share_status": share_status,
                "author_name": db_row.get("author_name") if db_row else None,
                "excerpt": excerpt,
            }
        )

    rows.sort(key=lambda r: r.get("updated_at") or "", reverse=True)
    return rows


def index_path_only(path: str) -> bool:
    fp = WORKSPACE_ROOT / path.replace("\\", "/")
    if not fp.is_file():
        return False
    with db.connect() as conn:
        db.init_db(conn)
        return index_file(conn, fp.resolve())


def index_paths(paths: list[str]) -> dict[str, int]:
    from .indexer import index_paths as _index_paths

    resolved = [WORKSPACE_ROOT / p.replace("\\", "/") for p in paths]
    return _index_paths(resolved)
