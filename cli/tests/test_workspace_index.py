from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from cxl_strata.workspace_index import db, indexer, nl_query, queries, sync_review
from cxl_strata.workspace_index.paths import set_workspace_root


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    (tmp_path / ".md" / "handoff" / "test-proj").mkdir(parents=True)
    handoff = tmp_path / ".md" / "handoff" / "test-proj" / "2026-06-30T12-00-00Z.md"
    handoff.write_text(
        "# Handoff — 2026-06-30T12-00-00Z\n\n- **Changed:** indexed test handoff\n",
        encoding="utf-8",
    )
    (tmp_path / ".md" / "blueprints").mkdir()
    (tmp_path / ".cursor" / "plans" / "draft").mkdir(parents=True)
    set_workspace_root(tmp_path)
    return tmp_path


def test_index_handoff(workspace: Path) -> None:
    stats = indexer.index_all(prune=False)
    assert stats["indexed"] >= 1

    with db.connect() as conn:
        db.init_db(conn)
        row = conn.execute(
            "SELECT kind, project, storage, origin FROM documents WHERE path LIKE '%handoff%'"
        ).fetchone()
    assert row is not None
    assert row["kind"] == "handoff"
    assert row["storage"] == "file"
    assert row["origin"] == "local"


def test_schema_migration_columns(workspace: Path) -> None:
    indexer.index_all(prune=False)
    with db.connect() as conn:
        db.init_db(conn)
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(documents)").fetchall()}
    for name in ("remote_id", "author_name", "shared_at", "synced_at"):
        assert name in cols


def test_indexes_cursor_claude_and_codex_instruction_files(tmp_path: Path) -> None:
    (tmp_path / ".cursor" / "rules").mkdir(parents=True)
    (tmp_path / ".cursor" / "rules" / "strata-memory.mdc").write_text(
        "# Cursor STRATA rule\n",
        encoding="utf-8",
    )
    (tmp_path / "CLAUDE.md").write_text("# Claude instructions\n", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("# Codex instructions\n", encoding="utf-8")
    set_workspace_root(tmp_path)

    stats = indexer.index_all(prune=False)

    assert stats["indexed"] == 3
    with db.connect() as conn:
        db.init_db(conn)
        rows = conn.execute(
            "SELECT path, kind FROM documents WHERE kind = 'rule' ORDER BY path"
        ).fetchall()
    assert [(row["path"], row["kind"]) for row in rows] == [
        (".cursor/rules/strata-memory.mdc", "rule"),
        ("AGENTS.md", "rule"),
        ("CLAUDE.md", "rule"),
    ]


def test_search_results_include_sync_status_for_local_documents(workspace: Path) -> None:
    stats = indexer.index_all(prune=False)
    assert stats["indexed"] >= 1

    path = ".md/handoff/test-proj/2026-06-30T12-00-00Z.md"
    with db.connect() as conn:
        db.init_db(conn)
        result = nl_query.parse_and_run(conn, "indexed test", project="test-proj")

        row = next(r for r in result["results"] if r["path"] == path)
        assert row["sync_status"] == "not_shared"
        assert row["syncable"] is True

        db.mark_shared(
            conn,
            path=path,
            remote_id="remote-1",
            author_name="Tester",
            author_email="tester@example.com",
        )
        shared = nl_query.parse_and_run(conn, "indexed test", project="test-proj")
        row = next(r for r in shared["results"] if r["path"] == path)
        assert row["sync_status"] == "shared"
        assert row["syncable"] is False

    handoff = workspace / path
    handoff.write_text(
        "# Handoff — 2026-06-30T12-00-00Z\n\n- **Changed:** indexed test handoff changed\n",
        encoding="utf-8",
    )
    future = (datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp()
    os.utime(handoff, (future, future))
    indexer.index_all(prune=False)

    with db.connect() as conn:
        db.init_db(conn)
        changed = nl_query.parse_and_run(conn, "changed", project="test-proj")
        row = next(r for r in changed["results"] if r["path"] == path)
        assert row["sync_status"] == "changed"
        assert row["syncable"] is True


def test_knowledge_get_includes_sync_status(workspace: Path) -> None:
    indexer.index_all(prune=False)
    path = ".md/handoff/test-proj/2026-06-30T12-00-00Z.md"
    with db.connect() as conn:
        db.init_db(conn)
        doc = queries.knowledge_get(conn, path)
    assert doc is not None
    assert doc["sync_status"] == "not_shared"
    assert doc["syncable"] is True


def test_list_recent_local_files_orders_newest_first(workspace: Path) -> None:
    stats = indexer.index_all(prune=False)
    assert stats["indexed"] >= 1

    with db.connect() as conn:
        db.init_db(conn)
        items = queries.list_recent_local_files(conn, limit=10)

    assert items
    assert items[0]["path"].endswith("2026-06-30T12-00-00Z.md")
    assert "sync_status" in items[0]


def test_scan_recent_locally_changed_keeps_recently_shared_files(workspace: Path) -> None:
    indexer.index_all(prune=False)
    path = ".md/handoff/test-proj/2026-06-30T12-00-00Z.md"
    stale = workspace / ".md" / "handoff" / "test-proj" / "2026-01-01T12-00-00Z.md"
    stale.write_text("# Handoff — stale\n", encoding="utf-8")
    past = (datetime.now(timezone.utc) - timedelta(days=30)).timestamp()
    os.utime(stale, (past, past))
    indexer.index_all(prune=False)

    with db.connect() as conn:
        db.init_db(conn)
        db.mark_shared(
            conn,
            path=path,
            remote_id="remote-1",
            author_name="Tester",
            author_email="tester@example.com",
        )

    items = sync_review.scan_recent_locally_changed(hours=168, limit=50)
    paths = {item["path"] for item in items}
    shared = next(item for item in items if item["path"] == path)

    assert path in paths
    assert shared["share_status"] == "shared"
    assert shared["local_status"] == "indexed"
    assert ".md/handoff/test-proj/2026-01-01T12-00-00Z.md" not in paths


def test_scan_recent_locally_changed_excludes_stale_files(workspace: Path) -> None:
    indexer.index_all(prune=False)

    stale = workspace / ".md" / "handoff" / "test-proj" / "2026-01-01T12-00-00Z.md"
    stale.write_text("# Handoff — stale\n", encoding="utf-8")
    past = (datetime.now(timezone.utc) - timedelta(days=30)).timestamp()
    os.utime(stale, (past, past))
    indexer.index_all(prune=False)

    recent_path = ".md/handoff/test-proj/2026-06-30T12-00-00Z.md"
    stale_path = ".md/handoff/test-proj/2026-01-01T12-00-00Z.md"
    items = sync_review.scan_recent_locally_changed(hours=168, limit=50)
    paths = {item["path"] for item in items}

    assert recent_path in paths
    assert stale_path not in paths


def test_project_timeline_events_include_sync_status(workspace: Path) -> None:
    stats = indexer.index_all(prune=False)
    assert stats["indexed"] >= 1

    path = ".md/handoff/test-proj/2026-06-30T12-00-00Z.md"
    with db.connect() as conn:
        db.init_db(conn)
        result = nl_query.parse_and_run(conn, "", project="test-proj")

    row = next(r for r in result["events"] if r["path"] == path)
    assert row["sync_status"] == "not_shared"
    assert row["syncable"] is True
