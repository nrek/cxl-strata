from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import yaml

from . import indexer
from .paths import LEGACY_PLAN_FOLDER_STATUS, PLAN_STATUSES, WORKSPACE_ROOT
from .parsers import split_frontmatter, status_from_plan_path


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def normalize_status(status: str) -> str:
    s = status.lower().strip().replace("-", "_")
    if s == "in queue":
        return "in_queue"
    if s == "in progress":
        return "in_progress"
    if s not in PLAN_STATUSES:
        raise ValueError(f"Invalid status: {status}")
    return s


def resolve_plan_path(path: str) -> Path:
    p = Path(path)
    if not p.is_absolute():
        p = WORKSPACE_ROOT / path
    if not p.exists():
        raise FileNotFoundError(path)
    return p.resolve()


def set_plan_status(
    path: str,
    status: str,
    *,
    linear_task_id: str | None = None,
) -> dict[str, str]:
    from . import db
    from .storage import plan_set_status_db

    status = normalize_status(status)
    rel = path.replace("\\", "/")
    fp = WORKSPACE_ROOT / rel
    if not fp.is_file():
        with db.connect() as conn:
            db.init_db(conn)
            return plan_set_status_db(
                conn, rel, status, linear_task_id=linear_task_id
            )

    src = resolve_plan_path(path)
    rel = src.relative_to(WORKSPACE_ROOT)

    text = src.read_text(encoding="utf-8")
    meta, body = split_frontmatter(text)
    old_status = meta.get("status")
    meta["status"] = status
    if linear_task_id:
        meta["linear_task_id"] = linear_task_id.upper()

    new_text = f"---\n{yaml.safe_dump(meta, sort_keys=False, allow_unicode=True)}---\n{body}"
    if not body.endswith("\n") and body:
        new_text = new_text.rstrip("\n") + "\n"

    dest_dir = WORKSPACE_ROOT / ".cursor" / "plans" / status
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name

    src.write_text(new_text, encoding="utf-8")
    if dest != src:
        if dest.exists():
            dest.unlink()
        src.rename(dest)

    indexer.index_paths([dest])
    return {
        "path": dest.relative_to(WORKSPACE_ROOT).as_posix(),
        "status": status,
        "previous_status": str(old_status) if old_status else None,
    }


def migrate_plan_layout(*, dry_run: bool = False) -> dict[str, int]:
    """Move legacy new/built folders and add status frontmatter."""
    plans_root = WORKSPACE_ROOT / ".cursor" / "plans"
    stats = {
        "moved": 0,
        "frontmatter_added": 0,
        "skipped": 0,
    }

    for folder in ("draft", "backlog", "in_queue", "in_progress", "done"):
        (plans_root / folder).mkdir(parents=True, exist_ok=True)

    candidates: list[Path] = []
    for p in plans_root.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() != ".md" and not p.name.endswith(".plan.md"):
            continue
        if p.parent == plans_root:
            candidates.append(p)
        elif p.parent.name in LEGACY_PLAN_FOLDER_STATUS or p.parent.name in PLAN_STATUSES:
            candidates.append(p)

    for src in candidates:
        folder_status = status_from_plan_path(src)
        if not folder_status and src.parent == plans_root:
            folder_status = "draft"
        if not folder_status:
            stats["skipped"] += 1
            continue

        text = src.read_text(encoding="utf-8")
        meta, body = split_frontmatter(text)
        if not meta.get("status"):
            meta["status"] = folder_status
            stats["frontmatter_added"] += 1

        dest_dir = plans_root / folder_status
        dest = dest_dir / src.name

        if dry_run:
            continue

        if meta:
            new_text = (
                f"---\n{yaml.safe_dump(meta, sort_keys=False, allow_unicode=True)}---\n{body}"
            )
            src.write_text(new_text, encoding="utf-8")

        if dest != src:
            if dest.exists():
                dest.unlink()
            src.rename(dest)
            stats["moved"] += 1

    if not dry_run:
        for legacy in ("new", "built"):
            legacy_dir = plans_root / legacy
            if legacy_dir.is_dir() and not any(legacy_dir.iterdir()):
                legacy_dir.rmdir()

    return stats
