#!/usr/bin/env python3
"""sessionStart hook: inject a compact STRATA knowledge digest into every session.

Reads .md/workspace_index.sqlite directly (no server dependency), emits
{"additional_context": "..."} capped at ~1.5 KB. Fails open on any error.
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_TS_RE = re.compile(r"(\d{4}-\d{2}-\d{2})T(\d{2})-(\d{2})-(\d{2})Z")

WORKSPACE = Path(__file__).resolve().parents[2]
DB_PATH = WORKSPACE / ".md" / "workspace_index.sqlite"
MAX_CHARS = 1500
WINDOW_HOURS = 48
MAX_ROWS = 10

CARD = (
    "[STRATA knowledge graph] DB routes discovery; markdown is payload. Before "
    "Plan/Build on non-trivial work, run bootstrap in "
    ".cursor/rules/agent-context-bootstrap.mdc then the Plan gate in "
    "agent-work-lifecycle.mdc (simple edits exempt). MCP workspace-knowledge "
    "or `strata app --open`."
)


def _doc_ts(path: str, updated_at: str | None) -> str:
    """Handoff filenames carry the true UTC timestamp; updated_at resets on bulk reindex."""
    m = _TS_RE.search(path or "")
    if m:
        return f"{m.group(1)}T{m.group(2)}:{m.group(3)}:{m.group(4)}"
    return (updated_at or "")[:19]


def _digest() -> str:
    conn = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT project, title, path, updated_at FROM documents WHERE kind = 'handoff'"
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    finally:
        conn.close()

    stamped = sorted(
        ((_doc_ts(r[2], r[3]), r) for r in rows), key=lambda t: t[0], reverse=True
    )
    cutoff = (
        datetime.now(timezone.utc) - timedelta(hours=WINDOW_HOURS)
    ).strftime("%Y-%m-%dT%H:%M:%S")
    recent = [t for t in stamped if t[0] >= cutoff][:MAX_ROWS] or stamped[:MAX_ROWS]

    lines = [CARD, "", f"Recent handoff activity (last {WINDOW_HOURS}h, {total} docs indexed):"]
    for ts, (project, title, path, _updated) in recent:
        lines.append(f"- {project or '?'} — {title or path} ({ts[:10]})")
    text = "\n".join(lines)
    if len(text) > MAX_CHARS:
        text = text[: MAX_CHARS - 1] + "…"
    return text


def main() -> int:
    try:
        sys.stdin.read()  # consume hook input; contents unused
    except Exception:
        pass
    try:
        payload = {"additional_context": _digest()}
    except Exception:
        payload = {}
    # ensure_ascii keeps output pure ASCII so Windows codepage piping can't mangle it
    print(json.dumps(payload, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
