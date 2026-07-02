from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from cxl_strata import documents
from cxl_strata.workspace_index import db, indexer, nl_query, prune, queries, sync_review
from cxl_strata.workspace_index.paths import resolve_workspace_root, set_workspace_root


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
    for name in (
        "remote_id",
        "author_name",
        "shared_at",
        "synced_at",
        "sync_ignored_at",
        "sync_ignore_reason",
    ):
        assert name in cols


def test_indexes_cursor_claude_and_codex_instruction_files(tmp_path: Path) -> None:
    (tmp_path / ".cursor" / "rules").mkdir(parents=True)
    (tmp_path / ".cursor" / "rules" / "strata-memory.mdc").write_text(
        "# Cursor STRATA rule\n",
        encoding="utf-8",
    )
    (tmp_path / ".cursor" / "skills" / "strata").mkdir(parents=True)
    (tmp_path / ".cursor" / "skills" / "strata" / "SKILL.md").write_text(
        "# Cursor STRATA skill\n",
        encoding="utf-8",
    )
    (tmp_path / "CLAUDE.md").write_text("# Claude instructions\n", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("# Codex instructions\n", encoding="utf-8")
    set_workspace_root(tmp_path)

    stats = indexer.index_all(prune=False)

    assert stats["indexed"] == 4
    with db.connect() as conn:
        db.init_db(conn)
        rows = conn.execute(
            "SELECT path, kind FROM documents WHERE kind = 'rule' ORDER BY path"
        ).fetchall()
    assert [(row["path"], row["kind"]) for row in rows] == [
        (".cursor/rules/strata-memory.mdc", "rule"),
        (".cursor/skills/strata/SKILL.md", "rule"),
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


def test_stash_paths_redacts_secret_markers_in_payload(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = workspace / ".cursor" / "plans" / "draft" / "secret-plan.md"
    plan.write_text(
        "# Plan\n\nUse password=supersecret123 only as a placeholder in docs.\n",
        encoding="utf-8",
    )
    indexer.index_all(prune=False)
    captured: list[dict] = []

    def fake_import_batch(payload: list[dict]) -> dict:
        captured.extend(payload)
        return {"synced": [{"path": payload[0]["path"], "remote_id": "remote-1"}], "failed": []}

    monkeypatch.setattr(documents, "_author_from_config", lambda: (None, None))
    monkeypatch.setattr(documents.api_client, "documents_import_batch", fake_import_batch)

    result = documents.stash_paths([".cursor/plans/draft/secret-plan.md"])

    assert not result["failed"]
    assert captured
    assert "supersecret123" not in captured[0]["body"]
    assert "password=[REDACTED_SECRET]" in captured[0]["body"]


def test_delete_remote_path_marks_local_doc_ignored(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    indexer.index_all(prune=False)
    path = ".md/handoff/test-proj/2026-06-30T12-00-00Z.md"
    deleted: list[str] = []
    with db.connect() as conn:
        db.init_db(conn)
        db.mark_shared(
            conn,
            path=path,
            remote_id="remote-1",
            author_name="Tester",
            author_email="tester@example.com",
        )

    monkeypatch.setattr(documents.api_client, "delete_document", lambda remote_id: deleted.append(remote_id) or {"deleted": True})

    result = documents.delete_remote_path(path)

    assert result == {"path": path, "remote_id": "remote-1", "deleted": True}
    assert deleted == ["remote-1"]
    with db.connect() as conn:
        db.init_db(conn)
        row = conn.execute(
            "SELECT remote_id, sync_ignored_at, sync_ignore_reason FROM documents WHERE path = ?",
            (path,),
        ).fetchone()
    assert row["remote_id"] is None
    assert row["sync_ignored_at"]
    assert row["sync_ignore_reason"] == "deleted_remote"


def test_scan_potential_secret_files_returns_redacted_previews(workspace: Path) -> None:
    plan = workspace / ".cursor" / "plans" / "draft" / "secret-plan.md"
    plan.write_text(
        "# Plan\n\nDeployment runbook is okay, but password=supersecret123 is redacted.\n",
        encoding="utf-8",
    )
    runbook = workspace / ".cursor" / "plans" / "draft" / "runbook-plan.md"
    runbook.write_text(
        "# Plan\n\nRun python scripts/deploy.py and follow Apache deployment instructions.\n",
        encoding="utf-8",
    )
    indexer.index_all(prune=False)

    rows = sync_review.scan_potential_secret_files()

    paths = {row["path"] for row in rows}
    assert ".cursor/plans/draft/secret-plan.md" in paths
    assert ".cursor/plans/draft/runbook-plan.md" not in paths
    row = next(row for row in rows if row["path"] == ".cursor/plans/draft/secret-plan.md")
    assert "supersecret123" not in row["excerpt"]
    assert "password=[REDACTED_SECRET]" in row["excerpt"]


def test_list_authors_and_filter_by_author(workspace: Path) -> None:
    indexer.index_all(prune=False)
    path = ".md/handoff/test-proj/2026-06-30T12-00-00Z.md"
    with db.connect() as conn:
        db.init_db(conn)
        db.mark_shared(
            conn,
            path=path,
            remote_id="remote-1",
            author_name="Tester",
            author_email="tester@example.com",
        )
        authors = queries.list_authors(conn)
        assert "Tester" in authors

    items = sync_review.scan_recent_locally_changed(hours=168, limit=50, author="Tester")
    assert any(item["path"] == path for item in items)

    other = sync_review.scan_recent_locally_changed(hours=168, limit=50, author="Nobody")
    assert not any(item["path"] == path for item in other)


def test_list_shared_from_team_documents_and_authors(workspace: Path) -> None:
    shared_path = "shared/remote-handoff-1"
    with db.connect() as conn:
        db.init_db(conn)
        db.upsert_document(
            conn,
            {
                "id": "shared-remote-handoff-1",
                "kind": "handoff",
                "project": "test-proj",
                "path": shared_path,
                "title": "Team handoff",
                "created_at": "2026-07-01T12:00:00Z",
                "updated_at": "2026-07-01T12:00:00Z",
                "body": "# Handoff\n\nShared by teammate.",
                "body_hash": "abc123",
                "plan_status": None,
                "linear_task_id": None,
                "files_changed": None,
                "deploy_commands": None,
                "tags": None,
                "folder_status": None,
                "status_mismatch": 0,
                "storage": "db_only",
                "origin": "shared",
                "remote_id": "remote-handoff-1",
                "author_name": "Teammate",
                "author_email": "teammate@example.com",
                "shared_at": "2026-07-01T12:00:00Z",
                "synced_at": "2026-07-02T12:00:00Z",
                "remote_updated_at": "2026-07-01T12:00:00Z",
            },
        )
        items = queries.list_shared_from_team_documents(conn, limit=50)
        authors = queries.list_authors(conn)
        filtered = queries.list_shared_from_team_documents(conn, limit=50, author="Teammate")
        empty = queries.list_shared_from_team_documents(conn, limit=50, author="Nobody")

    assert any(item["path"] == shared_path for item in items)
    row = next(item for item in items if item["path"] == shared_path)
    assert row["author_name"] == "Teammate"
    assert row["local_status"] == "received"
    assert "Teammate" in authors
    assert any(item["path"] == shared_path for item in filtered)
    assert not any(item["path"] == shared_path for item in empty)


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


def test_list_recent_local_documents_includes_db_only_in_window(workspace: Path) -> None:
    indexer.index_all(prune=False)
    path = ".md/handoff/test-proj/2026-06-30T12-00-00Z.md"
    recent_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    with db.connect() as conn:
        db.init_db(conn)
        conn.execute(
            """
            UPDATE documents
            SET storage = 'db_only', updated_at = ?
            WHERE path = ?
            """,
            (recent_iso, path),
        )

    with db.connect() as conn:
        db.init_db(conn)
        items = queries.list_recent_local_documents(conn, hours=168, limit=50)

    paths = {item["path"] for item in items}
    assert path in paths
    row = next(item for item in items if item["path"] == path)
    assert row["local_status"] == "archived"


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


def test_remote_deleted_files_are_hidden_from_future_sync_prompts(workspace: Path) -> None:
    indexer.index_all(prune=False)
    path = ".md/handoff/test-proj/2026-06-30T12-00-00Z.md"
    with db.connect() as conn:
        db.init_db(conn)
        db.mark_shared(
            conn,
            path=path,
            remote_id="remote-1",
            author_name="Tester",
            author_email="tester@example.com",
        )
        db.mark_remote_deleted(conn, path=path, reason="deleted_remote")

    handoff = workspace / path
    handoff.write_text(
        "# Handoff — 2026-06-30T12-00-00Z\n\n- **Changed:** changed after delete\n",
        encoding="utf-8",
    )
    future = (datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp()
    os.utime(handoff, (future, future))
    indexer.index_all(prune=False)

    pending = sync_review.scan_pending()
    assert path not in {item["path"] for item in pending}

    with db.connect() as conn:
        db.init_db(conn)
        doc = queries.knowledge_get(conn, path)
    assert doc is not None
    assert doc["sync_status"] == "ignored"
    assert doc["syncable"] is False


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
        result = nl_query.parse_and_run(conn, "", project="test-proj", all_time=True)

    assert result["intent"] == "library"
    assert result["all_time"] is True
    assert result["hours"] is None
    row = next(r for r in result["events"] if r["path"] == path)
    assert row["sync_status"] == "not_shared"
    assert row["syncable"] is True


def test_project_library_includes_old_handoffs(workspace: Path) -> None:
    old = workspace / ".md" / "handoff" / "test-proj" / "2026-01-15T12-00-00Z.md"
    old.write_text(
        "# Handoff — 2026-01-15T12-00-00Z\n\n- **Changed:** archived-era handoff\n",
        encoding="utf-8",
    )
    indexer.index_all(prune=False)

    with db.connect() as conn:
        db.init_db(conn)
        result = nl_query.project_library(conn, project="test-proj", limit=100)

    paths = {row["path"] for row in result["events"]}
    assert ".md/handoff/test-proj/2026-01-15T12-00-00Z.md" in paths
    assert result["all_time"] is True
    assert result["total_in_index"] >= 2


def test_prune_can_scope_to_project(workspace: Path) -> None:
    other = workspace / ".md" / "handoff" / "other-proj" / "2026-06-30T13-00-00Z.md"
    other.parent.mkdir(parents=True)
    other.write_text("# Handoff — other\n\n- **Changed:** other project\n", encoding="utf-8")
    indexer.index_all(prune=False)

    result = prune.run_prune(kinds=["handoff"], project="test-proj")

    assert ".md/handoff/test-proj/2026-06-30T12-00-00Z.md" in result["would_prune"]
    assert ".md/handoff/other-proj/2026-06-30T13-00-00Z.md" not in result["would_prune"]


def test_resolve_workspace_root_prefers_parent_memory_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("STRATA_WORKSPACE_ROOT", raising=False)
    workspace = tmp_path / "projects"
    repo = workspace / "cxl-strata"
    (workspace / ".md" / "handoff" / "cxl-strata").mkdir(parents=True)
    (repo / ".strata").mkdir(parents=True)
    (repo / ".strata" / "config.json").write_text("{}", encoding="utf-8")

    resolve_workspace_root.cache_clear()
    assert resolve_workspace_root(repo) == workspace.resolve()
