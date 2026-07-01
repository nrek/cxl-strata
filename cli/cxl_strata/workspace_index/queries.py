from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from . import db
from .paths import BLUEPRINT_ALIASES, WORKSPACE_ROOT

InclusionReason = Literal["within_window", "carry_forward", "recent_activity"]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_since_hours(hours: int) -> str:
    return (_utc_now() - timedelta(hours=hours)).isoformat().replace("+00:00", "Z")


def _snippet(text: str, max_len: int = 400) -> str:
    t = text.strip()
    if len(t) <= max_len:
        return t
    return t[: max_len - 3] + "..."


def _sync_status(row: dict[str, Any]) -> str:
    if not row.get("remote_id"):
        return "not_shared"
    updated_at = str(row.get("updated_at") or "")
    synced_at = str(row.get("synced_at") or "")
    if updated_at and synced_at and updated_at > synced_at:
        return "changed"
    return "shared"


def _with_sync_status(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    status = _sync_status(item)
    item["sync_status"] = status
    item["syncable"] = status in {"not_shared", "changed"}
    return item


def local_default_author() -> str | None:
    try:
        from ..local_store import load_config

        name = (load_config().get("actor_name") or "").strip()
        return name or None
    except FileNotFoundError:
        return None


def effective_author_name(row: dict[str, Any] | None) -> str | None:
    if row and row.get("author_name"):
        name = str(row["author_name"]).strip()
        if name:
            return name
    return local_default_author()


def list_authors(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        """
        SELECT DISTINCT author_name
        FROM documents
        WHERE author_name IS NOT NULL AND TRIM(author_name) != ''
        ORDER BY author_name COLLATE NOCASE
        """
    ).fetchall()
    names = {r["author_name"] for r in rows}
    default = local_default_author()
    if default:
        names.add(default)
    return sorted(names, key=lambda s: s.lower())


def filter_by_author(items: list[dict[str, Any]], author: str | None) -> list[dict[str, Any]]:
    if not author:
        return items
    key = author.strip().lower()
    if not key:
        return items
    out: list[dict[str, Any]] = []
    for item in items:
        name = (item.get("author_name") or effective_author_name(item) or "").strip().lower()
        if name == key:
            out.append(item)
    return out


def _handoff_documents_since(
    conn: sqlite3.Connection,
    project: str,
    since_iso: str,
    limit: int,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT path, kind, project, title, updated_at, created_at, plan_status,
               substr(body, 1, 800) AS excerpt
        FROM documents
        WHERE kind = 'handoff'
          AND project = ?
          AND (updated_at >= ? OR created_at >= ?)
        ORDER BY updated_at DESC
        LIMIT ?
        """,
        (project, since_iso, since_iso, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def handoffs_recent_available(
    conn: sqlite3.Connection,
    project: str,
    *,
    hours: int = 48,
    limit: int = 10,
    min_items: int = 1,
    max_lookback_hours: int = 168,
) -> dict[str, Any]:
    """
    Rolling last `hours` of handoff *activity* (wall-clock), not calendar days.

    If strict window is empty or sparse (weekends, no sessions), carry forward the
    most recent handoff files back to the last documented activity, up to
    max_lookback_hours (default 7 days).
    """
    since_strict = _iso_since_hours(hours)
    strict = _handoff_documents_since(conn, project, since_strict, limit)

    result: list[dict[str, Any]] = []
    seen: set[str] = set()

    for row in strict:
        path = row["path"]
        if path in seen:
            continue
        seen.add(path)
        item = dict(row)
        item["inclusion"] = "within_window"
        item["window_hours"] = hours
        result.append(item)

    if len(result) >= min_items:
        return {
            "project": project,
            "window_hours": hours,
            "max_lookback_hours": max_lookback_hours,
            "mode": "strict_window",
            "handoffs": result[:limit],
        }

    since_wide = _iso_since_hours(max_lookback_hours)
    wide = _handoff_documents_since(conn, project, since_wide, limit)
    for row in wide:
        path = row["path"]
        if path in seen:
            continue
        seen.add(path)
        item = dict(row)
        item["inclusion"] = "carry_forward"
        item["window_hours"] = hours
        result.append(item)
        if len(result) >= limit:
            break

    mode = "carry_forward" if any(h["inclusion"] == "carry_forward" for h in result) else "strict_window"
    if not result and wide:
        mode = "recent_activity"

    return {
        "project": project,
        "window_hours": hours,
        "max_lookback_hours": max_lookback_hours,
        "mode": mode,
        "handoffs": result[:limit],
    }


def knowledge_recent(
    conn: sqlite3.Connection,
    *,
    project: str | None = None,
    hours: int = 48,
    kind: str | None = None,
    limit: int = 10,
    available_handoffs: bool = True,
) -> list[dict[str, Any]] | dict[str, Any]:
    if project and (kind == "handoff" or kind is None) and available_handoffs:
        if kind == "handoff":
            return handoffs_recent_available(
                conn, project, hours=hours, limit=limit
            )

    since = _iso_since_hours(hours)
    clauses = ["(updated_at >= ? OR created_at >= ?)"]
    params: list[Any] = [since, since]
    if project:
        clauses.append("project = ?")
        params.append(project)
    if kind:
        clauses.append("kind = ?")
        params.append(kind)
    where = " AND ".join(clauses)
    params.append(limit)
    rows = conn.execute(
        f"""
        SELECT path, kind, project, title, updated_at, plan_status,
               substr(body, 1, 800) AS excerpt
        FROM documents
        WHERE {where}
        ORDER BY updated_at DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    items = [dict(r) for r in rows]
    if project and kind is None and available_handoffs:
        handoffs = handoffs_recent_available(conn, project, hours=hours, limit=limit)
        sections = sections_recent_available(conn, project, hours=hours, limit=limit)
        return {
            "documents": items,
            "handoffs_available": handoffs,
            "sections": sections,
        }
    return items


def list_recent_local_documents(
    conn: sqlite3.Connection,
    *,
    hours: int = 168,
    limit: int = 500,
    kind: str | None = None,
    author: str | None = None,
) -> list[dict[str, Any]]:
    """Indexed local documents with activity in the rolling window — all projects."""
    since = _iso_since_hours(hours)
    clauses = [
        "(updated_at >= ? OR created_at >= ? OR shared_at >= ? OR synced_at >= ?)"
    ]
    params: list[Any] = [since, since, since, since]
    if kind:
        clauses.append("kind = ?")
        params.append(kind)

    rows = conn.execute(
        f"""
        SELECT path, kind, project, title, created_at, updated_at, origin,
               remote_id, shared_at, synced_at, author_name, storage,
               substr(body, 1, 180) AS excerpt
        FROM documents
        WHERE {" AND ".join(clauses)}
        ORDER BY COALESCE(updated_at, synced_at, shared_at, created_at) DESC
        LIMIT ?
        """,
        (*params, limit),
    ).fetchall()

    items: list[dict[str, Any]] = []
    for row in rows:
        item = _with_sync_status(row)
        storage = item.get("storage") or "file"
        rel = item["path"]
        fp = WORKSPACE_ROOT / rel.replace("\\", "/")
        if storage == "db_only" or not fp.is_file():
            local_status = "archived" if storage == "db_only" else "indexed"
        else:
            local_status = "indexed"
        share_status = "shared" if item.get("remote_id") else "not shared"
        if item.get("sync_status") == "changed":
            share_status = "remote changed"
            local_status = "changed"
        activity_at = max(
            str(v)
            for v in (
                item.get("updated_at"),
                item.get("synced_at"),
                item.get("shared_at"),
                item.get("created_at"),
            )
            if v
        )
        item.update(
            {
                "updated_at": activity_at,
                "local_status": local_status,
                "share_status": share_status,
                "author_name": effective_author_name(item),
                "excerpt": item.get("excerpt") or "",
            }
        )
        items.append(item)

    return filter_by_author(items, author)


def list_recent_local_files(
    conn: sqlite3.Connection,
    *,
    hours: int = 168,
    limit: int = 500,
    kind: str | None = None,
    author: str | None = None,
) -> list[dict[str, Any]]:
    """Locally active indexed documents within the rolling window, newest first."""
    return list_recent_local_documents(
        conn, hours=hours, limit=limit, kind=kind, author=author
    )


def knowledge_search(
    conn: sqlite3.Connection,
    *,
    query: str,
    project: str | None = None,
    kind: str | None = None,
    plan_status: str | None = None,
    author: str | None = None,
    limit: int = 15,
) -> list[dict[str, Any]]:
    clauses = ["documents_fts MATCH ?"]
    params: list[Any] = [query]
    joins = "JOIN documents d ON d.id = documents_fts.document_id"
    if project:
        clauses.append("d.project = ?")
        params.append(project)
    if kind:
        clauses.append("d.kind = ?")
        params.append(kind)
    if plan_status:
        clauses.append("d.plan_status = ?")
        params.append(plan_status)
    where = " AND ".join(clauses)
    params.append(limit)
    rows = conn.execute(
        f"""
        SELECT d.path, d.kind, d.project, d.title, d.plan_status,
               d.updated_at, d.created_at, d.origin, d.remote_id,
               d.shared_at, d.synced_at, d.author_name,
               snippet(documents_fts, 1, '**', '**', '…', 32) AS snippet,
               bm25(documents_fts) AS rank
        FROM documents_fts
        {joins}
        WHERE {where}
        ORDER BY rank
        LIMIT ?
        """,
        params,
    ).fetchall()
    items = [_with_sync_status(r) for r in rows]
    return filter_by_author(items, author) if author else items


def knowledge_get(conn: sqlite3.Connection, path: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM documents WHERE path = ?", (path.replace("\\", "/"),)
    ).fetchone()
    if not row:
        return None
    out = dict(row)
    for key in ("files_changed", "deploy_commands", "tags"):
        if out.get(key):
            try:
                out[key] = json.loads(out[key])
            except json.JSONDecodeError:
                pass
    return _with_sync_status(out)


def knowledge_blueprint(
    conn: sqlite3.Connection, project: str, *, max_chars: int = 2000
) -> dict[str, Any] | None:
    alias = project.lower().strip()
    filename = BLUEPRINT_ALIASES.get(alias)
    bp_dir = WORKSPACE_ROOT / ".md" / "blueprints"
    candidates: list[Path] = []
    if filename:
        candidates.append(bp_dir / filename)
    candidates.append(bp_dir / f"{alias}.md")
    for c in candidates:
        if c.is_file():
            rel = c.relative_to(WORKSPACE_ROOT).as_posix()
            doc = knowledge_get(conn, rel)
            if doc:
                doc["excerpt"] = _snippet(doc.get("body", ""), max_chars)
                return doc
    row = conn.execute(
        """
        SELECT path, title, substr(body, 1, ?) AS excerpt
        FROM documents
        WHERE kind = 'blueprint' AND (project = ? OR path LIKE ?)
        LIMIT 1
        """,
        (max_chars, alias, f"%.md/blueprints/%{alias}%"),
    ).fetchone()
    return dict(row) if row else None


def plan_list(
    conn: sqlite3.Connection,
    *,
    status: str | None = None,
    project: str | None = None,
    linear_task_id: str | None = None,
    author: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    clauses = ["1=1"]
    params: list[Any] = []
    if status:
        clauses.append("p.status = ?")
        params.append(status)
    if project:
        clauses.append("p.project = ?")
        params.append(project)
    if linear_task_id:
        clauses.append("p.linear_task_id = ?")
        params.append(linear_task_id.upper())
    params.append(limit)
    rows = conn.execute(
        f"""
        SELECT d.path, p.status, p.name, p.project, p.linear_task_id,
               p.todo_total, p.todo_done, p.overview, d.updated_at, d.author_name
        FROM plans p
        JOIN documents d ON d.id = p.document_id
        WHERE {" AND ".join(clauses)}
        ORDER BY d.updated_at DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    items = [dict(r) for r in rows]
    return filter_by_author(items, author) if author else items


def plan_get(conn: sqlite3.Connection, path: str) -> dict[str, Any] | None:
    doc = knowledge_get(conn, path)
    if not doc:
        return None
    plan = conn.execute(
        """
        SELECT status, name, overview, project, linear_task_id,
               todo_total, todo_done, status_changed_at
        FROM plans WHERE document_id = ?
        """,
        (doc["id"],),
    ).fetchone()
    if plan:
        doc["plan"] = dict(plan)
        doc["overview_snippet"] = _snippet(plan["overview"] or "", 500)
    return doc


def _sections_since(
    conn: sqlite3.Connection,
    project: str,
    since_iso: str,
    limit: int,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT d.path, d.project, s.heading, s.section_at,
               substr(s.body, 1, 600) AS excerpt, s.ordinal, d.updated_at
        FROM sections s
        JOIN documents d ON d.id = s.document_id
        WHERE d.kind = 'handoff'
          AND d.project = ?
          AND (s.section_at >= ? OR d.updated_at >= ?)
        ORDER BY COALESCE(s.section_at, d.updated_at) DESC
        LIMIT ?
        """,
        (project, since_iso, since_iso, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def sections_recent_available(
    conn: sqlite3.Connection,
    project: str,
    *,
    hours: int = 48,
    limit: int = 8,
    max_lookback_hours: int = 168,
) -> dict[str, Any]:
    since_strict = _iso_since_hours(hours)
    strict = _sections_since(conn, project, since_strict, limit)
    if strict:
        return {
            "project": project,
            "window_hours": hours,
            "mode": "strict_window",
            "sections": [{**s, "inclusion": "within_window"} for s in strict],
        }
    since_wide = _iso_since_hours(max_lookback_hours)
    wide = _sections_since(conn, project, since_wide, limit)
    return {
        "project": project,
        "window_hours": hours,
        "mode": "carry_forward" if wide else "empty",
        "sections": [{**s, "inclusion": "carry_forward"} for s in wide],
    }


def recent_sections(
    conn: sqlite3.Connection,
    *,
    project: str,
    hours: int = 48,
    limit: int = 8,
) -> list[dict[str, Any]]:
    """Backward-compatible: returns section list from available-window query."""
    payload = sections_recent_available(conn, project, hours=hours, limit=limit)
    return payload.get("sections", [])
