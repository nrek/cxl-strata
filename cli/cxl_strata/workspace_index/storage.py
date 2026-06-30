from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import db, parsers
from .paths import WORKSPACE_ROOT
from .parsers import (
    doc_id_for_path,
    dumps_json,
    handoff_body_for_append,
    normalize_handoff_append_content,
    parse_document,
    next_handoff_iteration,
    split_handoff_sections,
    split_frontmatter,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def file_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def write_markdown_file(rel_path: str, text: str) -> Path:
    """Write a repo-relative markdown path under WORKSPACE_ROOT."""
    fp = WORKSPACE_ROOT / rel_path.replace("\\", "/")
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(text, encoding="utf-8")
    return fp


def verify_file_matches_db(conn, rel_path: str) -> tuple[bool, str]:
    row = conn.execute(
        "SELECT body_hash, storage FROM documents WHERE path = ?",
        (rel_path,),
    ).fetchone()
    if not row:
        return False, "not in database"
    fp = WORKSPACE_ROOT / rel_path
    if not fp.is_file():
        if row["storage"] == "db_only":
            return True, "already db_only"
        return False, "file missing but not marked db_only"
    text = fp.read_text(encoding="utf-8")
    if file_hash(text) != row["body_hash"]:
        return False, "hash mismatch"
    return True, "ok"


def upsert_from_text(
    conn,
    *,
    rel_path: str,
    text: str,
    kind: str,
    storage: str = "file",
) -> dict[str, Any]:
    path_obj = Path(rel_path)
    parsed = parse_document(rel_path, text, kind=kind, path_obj=path_obj)
    doc_id = doc_id_for_path(rel_path)
    now = utc_now()
    created = parsers.parse_iso_from_filename(path_obj.name) or now
    body_hash = file_hash(text)

    row = {
        "id": doc_id,
        "kind": kind,
        "project": parsed.project,
        "path": rel_path,
        "title": parsed.title,
        "created_at": created,
        "updated_at": now,
        "body": text,
        "body_hash": body_hash,
        "plan_status": parsed.plan_status,
        "linear_task_id": parsed.linear_task_id,
        "files_changed": dumps_json(parsed.files_changed),
        "deploy_commands": dumps_json(parsed.deploy_commands),
        "tags": dumps_json(parsed.tags),
        "folder_status": parsed.plan_status if kind == "plan" else None,
        "status_mismatch": 0,
        "storage": storage,
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
                "status_changed_at": now,
            },
        )
    if kind == "handoff":
        db.replace_sections(conn, doc_id, split_handoff_sections(doc_id, parsed.body))

    return {"path": rel_path, "id": doc_id, "storage": storage}


def handoff_append(
    conn,
    *,
    project: str,
    content: str,
    path: str | None = None,
) -> dict[str, Any]:
    if path:
        rel = path.replace("\\", "/")
        row = conn.execute(
            "SELECT body FROM documents WHERE path = ? AND kind = 'handoff'",
            (rel,),
        ).fetchone()
        db_body = row["body"] if row else None
        body = handoff_body_for_append(rel, db_body)
        clean = normalize_handoff_append_content(content)
        iteration = next_handoff_iteration(body)
        block = f"\n\n---\n\n## i{iteration}\n\n{clean}\n"
        text = body.rstrip() + block
        write_markdown_file(rel, text)
        return upsert_from_text(
            conn, rel_path=rel, text=text, kind="handoff", storage="file"
        )

    stamp = utc_now().replace(":", "-")[:19] + "Z"
    rel = f".md/handoff/{project}/{stamp}.md"
    clean = normalize_handoff_append_content(content)
    text = f"# Handoff — {stamp}\n\n{clean}\n"
    write_markdown_file(rel, text)
    return upsert_from_text(conn, rel_path=rel, text=text, kind="handoff", storage="file")


def plan_set_status_db(
    conn,
    path: str,
    status: str,
    *,
    linear_task_id: str | None = None,
) -> dict[str, Any]:
    from .plan_ops import normalize_status

    status = normalize_status(status)
    rel = path.replace("\\", "/")
    row = conn.execute(
        "SELECT body, id FROM documents WHERE path = ? AND kind = 'plan'",
        (rel,),
    ).fetchone()
    if not row:
        raise FileNotFoundError(path)

    meta, body = split_frontmatter(row["body"])
    meta["status"] = status
    if linear_task_id:
        meta["linear_task_id"] = linear_task_id.upper()

    try:
        import yaml

        new_text = (
            f"---\n{yaml.safe_dump(meta, sort_keys=False, allow_unicode=True)}---\n{body}"
        )
    except ImportError:
        new_text = f"---\nstatus: {status}\n---\n{body}"

    name = Path(rel).name
    new_rel = f".cursor/plans/{status}/{name}"
    old_fp = WORKSPACE_ROOT / rel
    if old_fp.is_file():
        old_fp.unlink()
    new_fp = WORKSPACE_ROOT / new_rel
    if new_fp.is_file() and new_rel != rel:
        new_fp.unlink()

    if new_rel != rel:
        db.delete_document(conn, row["id"])

    return upsert_from_text(
        conn, rel_path=new_rel, text=new_text, kind="plan", storage="db_only"
    )
