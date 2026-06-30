"""Archive file-backed docs into SQLite (db_only storage)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from . import db
from .paths import WORKSPACE_ROOT
from .storage import verify_file_matches_db


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _is_older_than(row_updated_at: str | None, *, cutoff: datetime) -> bool:
    parsed = _parse_iso(row_updated_at)
    if parsed is None:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed < cutoff


def run_prune(
    *,
    kinds: list[str],
    execute: bool = False,
    plan_status: str | None = None,
    older_than_hours: int | None = None,
    archive_handoffs: bool = False,
) -> dict[str, Any]:
    if archive_handoffs:
        kinds = ["handoff"]
        if older_than_hours is None:
            older_than_hours = 96

    stats: dict[str, Any] = {
        "verified": 0,
        "pruned": 0,
        "skipped": 0,
        "too_recent": 0,
        "errors": [],
    }
    pruned_paths: list[str] = []
    cutoff = None
    if older_than_hours is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=older_than_hours)

    with db.connect() as conn:
        db.init_db(conn)
        clauses = [
            "COALESCE(storage, 'file') = 'file'",
            f"kind IN ({','.join('?' * len(kinds))})",
        ]
        params: list[Any] = list(kinds)
        if plan_status and "plan" in kinds:
            clauses.append("plan_status = ?")
            params.append(plan_status)

        rows = conn.execute(
            f"SELECT path, kind, plan_status, updated_at FROM documents WHERE {' AND '.join(clauses)}",
            params,
        ).fetchall()

        for row in rows:
            rel = row["path"]
            if cutoff is not None and not _is_older_than(row["updated_at"], cutoff=cutoff):
                stats["too_recent"] += 1
                continue
            ok, reason = verify_file_matches_db(conn, rel)
            if not ok:
                stats["skipped"] += 1
                stats["errors"].append({"path": rel, "reason": reason})
                continue
            stats["verified"] += 1
            fp = WORKSPACE_ROOT / rel
            if not fp.is_file():
                if execute:
                    conn.execute(
                        "UPDATE documents SET storage = 'db_only' WHERE path = ?",
                        (rel,),
                    )
                continue
            if execute:
                fp.unlink()
                conn.execute(
                    "UPDATE documents SET storage = 'db_only' WHERE path = ?",
                    (rel,),
                )
                pruned_paths.append(rel)
                stats["pruned"] += 1
            else:
                pruned_paths.append(rel)

    key = "pruned" if execute else "would_prune"
    return {"stats": stats, key: pruned_paths, "dry_run": not execute}
