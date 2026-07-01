"""Natural-language-ish query parsing for workspace explorer."""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from . import queries
from .paths import DB_PATH, WORKSPACE_ROOT
from .text_cleanup import fix_mojibake

Intent = Literal["timeline", "search", "recent", "plans", "library"]

# Keyword → project slugs (folder names under .md/handoff/)
PROJECT_ALIASES: dict[str, list[str]] = {
    "commonspace": [
        "commonspace-app",
        "commonspace-ui-v3",
        "cs-space-builder",
        "commonspace",
    ],
    "prompli": ["v5.prompli.com", "v4.prompli.com"],
    "synq": [
        "synq-forge",
        "synq-phalanx",
        "synq-filters",
        "synq-jarvis",
        "synq-market-scrapers",
        "synq-net-scrapers",
        "synq_stones",
        "synq-net",
        "synq-market",
        "synq-tech",
    ],
    "phalanx": ["synq-phalanx"],
    "forge": ["synq-forge"],
    "jarvis": ["synq-jarvis"],
    "scout": ["cxl-scout"],
    "sentinel": ["cxl-sentinel", "cxl-sentinel-saas"],
    "sanctum": ["cxl-sanctum"],
    "spore": ["cxl-spore"],
    "synapse": ["cxl-synapse"],
    "blind": ["blind-insight", "blind-llm", "blind-ml"],
    "seersite": ["seersite-server", "seersite-frontend"],
    "invivaria": ["invivaria-backend", "invivaria-frontend", "invivaria"],
    "workspace": ["workspace"],
}

TIMELINE_HINTS = (
    "timeline",
    "history",
    "what did we do",
    "what have we done",
    "show me",
    "activity",
    "work log",
    "handoffs",
)
PLAN_HINTS = ("plan", "plans", "backlog", "in queue", "in progress", "draft")
RECENT_HINTS = ("recent", "latest", "last handoff")
LAST_TIME_RE = re.compile(
    r"\b(?:"
    r"last time (?:i|we)|"
    r"when did (?:i|we) last|"
    r"when was the last time (?:i|we)"
    r")\s+(?:"
    r"touched|worked on|changed|modified|updated|used|mentioned|looked at|edited"
    r")?\s*(.+)$",
    re.I,
)

NOISE_WORDS_RE = re.compile(
    r"\b("
    r"show|me|a|an|the|for|what|did|we|do|last|week|timeline|of|recent|latest|"
    r"in|on|about|find|search|please|my|our|project|handoffs|handoff|activity|"
    r"time|i|touched|worked|changed|modified|updated|used|mentioned|when|was"
    r")\b",
    re.I,
)

TIME_PATTERNS: list[tuple[re.Pattern[str], int]] = [
    (re.compile(r"\blast\s+week\b", re.I), 168),
    (re.compile(r"\bpast\s+week\b", re.I), 168),
    (re.compile(r"\blast\s+7\s+days?\b", re.I), 168),
    (re.compile(r"\blast\s+month\b", re.I), 720),
    (re.compile(r"\bpast\s+month\b", re.I), 720),
    (re.compile(r"\blast\s+30\s+days?\b", re.I), 720),
    (re.compile(r"\blast\s+fortnight\b", re.I), 336),
    (re.compile(r"\blast\s+2\s+weeks?\b", re.I), 336),
    (re.compile(r"\byesterday\b", re.I), 48),
    (re.compile(r"\btoday\b", re.I), 24),
    (re.compile(r"\blast\s+48\s+hours?\b", re.I), 48),
    (re.compile(r"\blast\s+24\s+hours?\b", re.I), 24),
    (re.compile(r"\blast\s+(\d+)\s+days?\b", re.I), 0),  # handled specially
]


def _has_time_phrase(text: str) -> bool:
    lower = text.lower()
    for pat, _hours in TIME_PATTERNS:
        if pat.search(lower):
            return True
    return False


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


_PATH_TS_RE = re.compile(r"/(\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z)\.md")


def normalize_event_at(at: str | None, path: str = "") -> str | None:
    """Normalize handoff/section timestamps for display and sorting."""
    if at:
        fixed = at.strip()
        if len(fixed) > 10 and fixed[4] == ":":
            fixed = f"{fixed[0:4]}-{fixed[5:7]}-{fixed[8:10]}{fixed[10:]}"
        return fixed
    m = _PATH_TS_RE.search(path.replace("\\", "/"))
    if not m:
        return None
    raw = m.group(1)
    date_part, time_part = raw.split("T", 1)
    time_part = time_part.rstrip("Z").replace("-", ":")
    return f"{date_part}T{time_part}Z"


def event_sort_key(at: str | None, path: str = "") -> float:
    normalized = normalize_event_at(at, path)
    if not normalized:
        return float("-inf")
    try:
        dt = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except ValueError:
        return float("-inf")


def sort_events_newest_first(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        events,
        key=lambda e: event_sort_key(
            e.get("at") or e.get("updated_at") or e.get("created_at"),
            e.get("path", ""),
        ),
        reverse=True,
    )


def _sync_status(row: sqlite3.Row | dict[str, Any]) -> str:
    remote_id = row["remote_id"] if isinstance(row, sqlite3.Row) else row.get("remote_id")
    if not remote_id:
        return "not_shared"
    updated_at = str(row["updated_at"] if isinstance(row, sqlite3.Row) else row.get("updated_at") or "")
    synced_at = str(row["synced_at"] if isinstance(row, sqlite3.Row) else row.get("synced_at") or "")
    if updated_at and synced_at and updated_at > synced_at:
        return "changed"
    return "shared"


def _sync_meta(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    status = _sync_status(row)
    data = dict(row) if isinstance(row, sqlite3.Row) else row
    return {
        "sync_status": status,
        "syncable": status in {"not_shared", "changed"},
        "author_name": queries.effective_author_name(data),
    }


def parse_hours(text: str, *, default: int = 168) -> int:
    lower = text.lower()
    for pat, hours in TIME_PATTERNS:
        m = pat.search(lower)
        if not m:
            continue
        if hours:
            return hours
        return int(m.group(1)) * 24
    return default


def detect_projects(text: str, conn: sqlite3.Connection | None = None) -> list[str]:
    lower = text.lower()
    found: list[str] = []
    seen: set[str] = set()

    for alias, projects in PROJECT_ALIASES.items():
        if alias in lower:
            for p in projects:
                if p not in seen:
                    seen.add(p)
                    found.append(p)

    if conn is not None:
        db_projects = [
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT project FROM documents WHERE project IS NOT NULL"
            ).fetchall()
        ]
        for p in db_projects:
            slug = p.lower()
            if slug in lower or slug.replace(".", " ") in lower:
                if p not in seen:
                    seen.add(p)
                    found.append(p)

    return found


def detect_intent(text: str, *, has_projects: bool = False, has_time: bool = False) -> Intent:
    lower = text.lower()
    if LAST_TIME_RE.search(text):
        return "search"
    if any(h in lower for h in PLAN_HINTS):
        return "plans"
    if any(h in lower for h in TIMELINE_HINTS):
        return "timeline"
    if has_projects and has_time:
        return "timeline"
    if any(h in lower for h in RECENT_HINTS):
        return "recent"
    return "search"


def extract_fts_query(text: str) -> str:
    m = LAST_TIME_RE.search(text.strip())
    if m:
        topic = m.group(1).strip()
        topic = re.sub(r"\?$", "", topic).strip()
        return topic or text

    cleaned = NOISE_WORDS_RE.sub(" ", text)
    cleaned = " ".join(cleaned.split())
    return cleaned or text


def is_last_time_query(text: str) -> bool:
    return bool(LAST_TIME_RE.search(text.strip()))


def format_fts_query(text: str) -> str:
    text = " ".join(text.split())
    if not text or '"' in text:
        return text
    words = text.split()
    if len(words) >= 2:
        return f'"{text}" OR ({" AND ".join(words)})'
    return text


def _iso_since_hours(hours: int) -> str:
    return (_utc_now() - timedelta(hours=hours)).isoformat().replace("+00:00", "Z")


def timeline(
    conn: sqlite3.Connection,
    *,
    projects: list[str] | None = None,
    hours: int | None = 168,
    limit: int = 80,
    include_sections: bool = True,
    author: str | None = None,
) -> dict[str, Any]:
    doc_clauses = ["kind = 'handoff'"]
    doc_params: list[Any] = []
    if hours is not None:
        since = _iso_since_hours(hours)
        doc_clauses.append("(updated_at >= ? OR created_at >= ?)")
        doc_params.extend([since, since])
    if projects:
        placeholders = ",".join("?" * len(projects))
        doc_clauses.append(f"project IN ({placeholders})")
        doc_params.extend(projects)

    events: list[dict[str, Any]] = []
    rows = conn.execute(
        f"""
        SELECT path, kind, project, title, updated_at, created_at,
               origin, remote_id, shared_at, synced_at, author_name,
               substr(body, 1, 500) AS excerpt
        FROM documents
        WHERE {" AND ".join(doc_clauses)}
        ORDER BY COALESCE(updated_at, created_at) DESC
        LIMIT ?
        """,
        (*doc_params, limit),
    ).fetchall()

    for row in rows:
        ts = normalize_event_at(row["updated_at"] or row["created_at"], row["path"])
        events.append(
            {
                "type": "handoff",
                "at": ts,
                "project": row["project"],
                "title": fix_mojibake(row["title"] or PathStem(row["path"])),
                "path": row["path"],
                "excerpt": fix_mojibake(row["excerpt"]),
                **_sync_meta(row),
            }
        )

    if include_sections and projects:
        sec_clauses = ["d.kind = 'handoff'"]
        sec_params: list[Any] = []
        if hours is not None:
            since = _iso_since_hours(hours)
            sec_clauses.append("(s.section_at >= ? OR d.updated_at >= ?)")
            sec_params.extend([since, since])
        placeholders = ",".join("?" * len(projects))
        sec_clauses.append(f"d.project IN ({placeholders})")
        sec_params.extend(projects)

        sec_rows = conn.execute(
            f"""
            SELECT d.path, d.project, d.title, d.updated_at, d.created_at,
                   d.origin, d.remote_id, d.shared_at, d.synced_at, d.author_name,
                   s.heading, s.section_at,
                   substr(s.body, 1, 400) AS excerpt, s.ordinal
            FROM sections s
            JOIN documents d ON d.id = s.document_id
            WHERE {" AND ".join(sec_clauses)}
            ORDER BY COALESCE(s.section_at, d.updated_at) DESC
            LIMIT ?
            """,
            (*sec_params, min(limit, 40)),
        ).fetchall()

        for row in sec_rows:
            ts = normalize_event_at(
                row["section_at"] or row["updated_at"] or row["created_at"],
                row["path"],
            )
            events.append(
                {
                    "type": "section",
                    "at": ts,
                    "project": row["project"],
                    "title": fix_mojibake(row["heading"] or row["title"] or "Section"),
                    "path": row["path"],
                    "excerpt": fix_mojibake(row["excerpt"]),
                    "ordinal": row["ordinal"],
                    **_sync_meta(row),
                }
            )

    for row in events:
        if row.get("type") == "handoff":
            row["at"] = normalize_event_at(row.get("at"), row.get("path", ""))

    events = sort_events_newest_first(events)
    if author:
        events = queries.filter_by_author(events, author)
    return {
        "intent": "timeline",
        "hours": hours,
        "projects": projects or [],
        "event_count": len(events),
        "events": events[:limit],
    }


def project_library(
    conn: sqlite3.Connection,
    *,
    project: str,
    limit: int = 500,
    author: str | None = None,
) -> dict[str, Any]:
    """All indexed documents for a project — no time window (knowledge library browse)."""
    rows = conn.execute(
        """
        SELECT path, kind, project, title, updated_at, created_at,
               origin, remote_id, shared_at, synced_at, author_name,
               substr(body, 1, 500) AS excerpt
        FROM documents
        WHERE project = ?
        ORDER BY COALESCE(updated_at, created_at) DESC
        LIMIT ?
        """,
        (project, limit),
    ).fetchall()

    events: list[dict[str, Any]] = []
    for row in rows:
        ts = normalize_event_at(row["updated_at"] or row["created_at"], row["path"])
        events.append(
            {
                "type": row["kind"],
                "kind": row["kind"],
                "at": ts,
                "project": row["project"],
                "title": fix_mojibake(row["title"] or PathStem(row["path"])),
                "path": row["path"],
                "excerpt": fix_mojibake(row["excerpt"]),
                **_sync_meta(row),
            }
        )

    events = sort_events_newest_first(events)
    if author:
        events = queries.filter_by_author(events, author)

    total = conn.execute(
        "SELECT COUNT(*) AS n FROM documents WHERE project = ?",
        (project,),
    ).fetchone()["n"]

    return {
        "intent": "library",
        "hours": None,
        "all_time": True,
        "projects": [project],
        "event_count": len(events),
        "total_in_index": total,
        "truncated": total > len(events),
        "events": events,
    }


def PathStem(path: str) -> str:
    return path.rsplit("/", 1)[-1].replace(".md", "")


def parse_and_run(
    conn: sqlite3.Connection,
    query: str,
    *,
    limit: int = 50,
    project: str | None = None,
    author: str | None = None,
    hours: int | None = None,
    all_time: bool = False,
) -> dict[str, Any]:
    text = query.strip()

    if not text and project:
        if all_time or hours == 0:
            out = project_library(conn, project=project, limit=limit, author=author)
        else:
            browse_hours = hours if hours is not None else 168
            out = timeline(
                conn,
                projects=[project],
                hours=browse_hours,
                limit=limit,
                include_sections=True,
                author=author,
            )
        return {
            "query": "",
            "intent": out.get("intent", "library"),
            "projects": [project],
            "scoped_project": project,
            "all_time": bool(out.get("all_time")),
            "hours": out.get("hours"),
            **out,
        }

    if not text:
        return {"error": "empty query", "intent": "search", "results": []}

    scoped = project.strip() if project else None
    detected = detect_projects(text, conn) if not scoped else []
    projects = [scoped] if scoped else detected

    has_time = _has_time_phrase(text)
    parsed_hours = parse_hours(text, default=168 if projects else 720)
    effective_hours = hours if hours is not None else parsed_hours
    if all_time or hours == 0:
        effective_hours = None
    intent = detect_intent(text, has_projects=bool(projects), has_time=has_time)
    last_time = is_last_time_query(text)

    meta: dict[str, Any] = {
        "query": text,
        "intent": intent,
        "projects": projects,
        "scoped_project": scoped,
        "hours": effective_hours,
        "all_time": effective_hours is None,
        "last_time": last_time,
    }

    if intent == "timeline" or (projects and intent == "search" and "timeline" in text.lower()):
        out = timeline(
            conn,
            projects=projects or None,
            hours=effective_hours,
            limit=limit,
            author=author,
        )
        return {**meta, **out}

    if intent == "recent" and projects:
        recent_hours = effective_hours if effective_hours is not None else 168
        payload = queries.handoffs_recent_available(
            conn, projects[0], hours=recent_hours, limit=limit
        )
        handoffs = sort_events_newest_first(payload.get("handoffs", []))
        for row in handoffs:
            row["author_name"] = queries.effective_author_name(row)
        if author:
            handoffs = queries.filter_by_author(handoffs, author)
        return {**meta, "intent": "recent", "handoffs": handoffs}

    if intent == "plans":
        status = None
        lower = text.lower()
        for st in ("in_progress", "in_queue", "draft", "backlog", "done"):
            if st.replace("_", " ") in lower or st in lower:
                status = st
                break
        plan_project = scoped or (projects[0] if len(projects) == 1 else None)
        items = queries.plan_list(
            conn, status=status, project=plan_project, limit=limit, author=author
        )
        if projects and len(projects) > 1:
            pset = set(projects)
            items = [p for p in items if p.get("project") in pset]
        return {**meta, "intent": "plans", "plans": items}

    fts_query = format_fts_query(extract_fts_query(text))
    project_filter = scoped or (projects[0] if len(projects) == 1 else None)
    search_limit = min(limit, 8) if last_time else limit

    results = queries.knowledge_search(
        conn,
        query=fts_query,
        project=project_filter,
        limit=search_limit * 3 if last_time else search_limit,
        author=author,
    )

    if projects and len(projects) > 1 and not scoped:
        pset = set(projects)
        results = [r for r in results if r.get("project") in pset]

    for row in results:
        row["at"] = normalize_event_at(row.get("updated_at"), row.get("path", ""))
        row["title"] = fix_mojibake(row.get("title") or PathStem(row.get("path", "")))
        row["snippet"] = fix_mojibake(row.get("snippet") or "")

    results = sort_events_newest_first(results)
    if last_time:
        results = results[: min(limit, 8)]

    if not results and projects and not last_time:
        out = timeline(
            conn,
            projects=projects,
            hours=effective_hours,
            limit=limit,
            author=author,
        )
        return {**meta, **out}

    return {**meta, "intent": "search", "fts_query": fts_query, "results": results}


def project_summary(conn: sqlite3.Connection, *, limit: int = 8) -> dict[str, list[dict[str, Any]]]:
    frequent = list_projects(conn)[:limit]

    rows = conn.execute(
        """
        SELECT project,
               MAX(COALESCE(updated_at, created_at)) AS last_at,
               COUNT(*) AS total
        FROM documents
        WHERE project IS NOT NULL
        GROUP BY project
        ORDER BY last_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()

    latest = [
        {
            "project": row["project"],
            "total": row["total"],
            "last_at": row["last_at"],
        }
        for row in rows
    ]

    return {"latest": latest, "frequent": frequent[:limit]}


def list_projects(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT project, kind, COUNT(*) AS n
        FROM documents
        WHERE project IS NOT NULL
        GROUP BY project, kind
        ORDER BY project, kind
        """
    ).fetchall()
    by_project: dict[str, dict[str, int]] = {}
    for row in rows:
        proj = row["project"]
        by_project.setdefault(proj, {})[row["kind"]] = row["n"]
    return [
        {"project": p, "counts": counts, "total": sum(counts.values())}
        for p, counts in sorted(by_project.items(), key=lambda x: -sum(x[1].values()))
    ]


def stats(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT kind, COUNT(*) AS n,
               SUM(CASE WHEN storage = 'db_only' THEN 1 ELSE 0 END) AS db_only
        FROM documents
        GROUP BY kind
        """
    ).fetchall()
    return {
        "by_kind": [dict(r) for r in rows],
        "db_path": str(DB_PATH),
        "workspace_root": str(WORKSPACE_ROOT),
    }
