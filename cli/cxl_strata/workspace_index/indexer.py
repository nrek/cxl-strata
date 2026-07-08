from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path

from . import db, parsers
from . import paths as _paths
from .parsers import (
    doc_id_for_path,
    infer_published_at,
    parse_document,
    parse_iso_from_filename,
    split_handoff_sections,
)
from .parsers import dumps_json


def _rel(path: Path) -> str:
    return path.relative_to(_paths.WORKSPACE_ROOT).as_posix()


def _mtime_iso(path: Path) -> str:
    ts = path.stat().st_mtime
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def discover_files() -> list[tuple[str, Path]]:
    out: list[tuple[str, Path]] = []
    root = _paths.WORKSPACE_ROOT

    handoff_root = root / ".md" / "handoff"
    if handoff_root.is_dir():
        for p in handoff_root.rglob("*.md"):
            if p.name.startswith("_"):
                continue
            out.append(("handoff", p))

    bp_root = root / ".md" / "blueprints"
    if bp_root.is_dir():
        for p in bp_root.glob("*.md"):
            out.append(("blueprint", p))

    plans_root = root / ".cursor" / "plans"
    if plans_root.is_dir():
        for p in plans_root.rglob("*"):
            if not p.is_file():
                continue
            if p.suffix.lower() in (".md",) or p.name.endswith(".plan.md"):
                if p.name.startswith("."):
                    continue
                out.append(("plan", p))

    rules_root = root / ".cursor" / "rules"
    if rules_root.is_dir():
        for p in rules_root.glob("*.mdc"):
            out.append(("rule", p))

    skills_root = root / ".cursor" / "skills"
    if skills_root.is_dir():
        for p in skills_root.rglob("SKILL.md"):
            out.append(("rule", p))

    for p in (root / "CLAUDE.md", root / "AGENTS.md"):
        if p.is_file():
            out.append(("rule", p))

    for agent_dir in (root / ".claude", root / ".codex"):
        if agent_dir.is_dir():
            for p in agent_dir.rglob("*.md"):
                if p.is_file() and not p.name.startswith("."):
                    out.append(("rule", p))

    return out


def index_file(conn, path: Path, kind: str | None = None) -> bool:
    if kind is None:
        rel = _rel(path)
        if rel.startswith(".md/handoff/"):
            kind = "handoff"
        elif rel.startswith(".md/blueprints/"):
            kind = "blueprint"
        elif rel.startswith(".cursor/plans/"):
            kind = "plan"
        elif rel.startswith(".cursor/rules/") or rel.startswith(".cursor/skills/"):
            kind = "rule"
        elif rel in {"CLAUDE.md", "AGENTS.md"}:
            kind = "rule"
        elif rel.startswith(".claude/") or rel.startswith(".codex/"):
            kind = "rule"
        else:
            return False

    rel_path = _rel(path)
    text = path.read_text(encoding="utf-8", errors="replace")
    body_hash = hashlib.sha256(text.encode()).hexdigest()

    existing = conn.execute(
        "SELECT body_hash, published_at FROM documents WHERE path = ?", (rel_path,)
    ).fetchone()
    if existing and existing["body_hash"] == body_hash:
        if not existing["published_at"]:
            _backfill_published_at(conn, rel_path, path, text, kind)
        return False

    parsed = parse_document(rel_path, text, kind=kind, path_obj=path)
    doc_id = doc_id_for_path(rel_path)

    created = parse_iso_from_filename(path.name) or _mtime_iso(path)
    updated = _mtime_iso(path)
    published = (
        infer_published_at(
            filename=path.name,
            frontmatter=parsed.frontmatter,
            title=parsed.title,
        )
        or created
    )

    folder_status = parsers.status_from_plan_path(path) if kind == "plan" else None
    status_mismatch = 0
    if kind == "plan" and parsed.plan_status and folder_status:
        if parsed.plan_status != folder_status:
            status_mismatch = 1

    row = {
        "id": doc_id,
        "kind": kind,
        "project": parsed.project,
        "path": rel_path,
        "title": parsed.title,
        "created_at": created,
        "updated_at": updated,
        "published_at": published,
        "body": text,
        "body_hash": body_hash,
        "plan_status": parsed.plan_status,
        "linear_task_id": parsed.linear_task_id,
        "files_changed": dumps_json(parsed.files_changed),
        "deploy_commands": dumps_json(parsed.deploy_commands),
        "tags": dumps_json(parsed.tags),
        "folder_status": folder_status,
        "status_mismatch": status_mismatch,
        "storage": "file",
    }
    db.upsert_document(conn, row)

    if kind == "plan" and parsed.plan_status:
        db.upsert_plan(
            conn,
            {
                "document_id": doc_id,
                "status": parsed.plan_status,
                "name": parsed.name or parsed.title,
                "overview": parsed.overview,
                "project": parsed.project,
                "linear_task_id": parsed.linear_task_id,
                "todo_total": parsed.todo_total,
                "todo_done": parsed.todo_done,
                "status_changed_at": updated,
            },
        )
    elif kind == "plan":
        conn.execute("DELETE FROM plans WHERE document_id = ?", (doc_id,))

    if kind == "handoff":
        sections = split_handoff_sections(doc_id, parsed.body)
        db.replace_sections(conn, doc_id, sections)

    return True


def _backfill_published_at(
    conn, rel_path: str, path: Path, text: str, kind: str
) -> None:
    """Populate published_at on unchanged legacy rows without a full re-upsert."""
    parsed = parse_document(rel_path, text, kind=kind, path_obj=path)
    published = (
        infer_published_at(
            filename=path.name,
            frontmatter=parsed.frontmatter,
            title=parsed.title,
        )
        or parse_iso_from_filename(path.name)
        or _mtime_iso(path)
    )
    conn.execute(
        "UPDATE documents SET published_at = ? WHERE path = ? AND published_at IS NULL",
        (published, rel_path),
    )


def index_all(*, prune: bool = True) -> dict[str, int]:
    stats = {"indexed": 0, "skipped": 0, "removed": 0, "warnings": 0}
    paths_seen: set[str] = set()

    with db.connect() as conn:
        db.init_db(conn)
        for kind, path in discover_files():
            rel = _rel(path)
            paths_seen.add(rel)
            if index_file(conn, path, kind):
                stats["indexed"] += 1
            else:
                stats["skipped"] += 1

        if prune:
            stats["removed"] = db.prune_missing(conn, paths_seen)

        warnings = conn.execute(
            "SELECT COUNT(*) AS c FROM documents WHERE status_mismatch = 1"
        ).fetchone()
        stats["warnings"] = int(warnings["c"]) if warnings else 0

    return stats


def index_paths(paths: list[Path]) -> dict[str, int]:
    stats = {"indexed": 0, "skipped": 0}
    with db.connect() as conn:
        db.init_db(conn)
        for path in paths:
            if not path.is_file():
                continue
            try:
                if index_file(conn, path.resolve()):
                    stats["indexed"] += 1
                else:
                    stats["skipped"] += 1
            except (ValueError, OSError):
                continue
    return stats
