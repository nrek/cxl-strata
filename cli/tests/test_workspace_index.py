from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from cxl_strata import documents, pull
from cxl_strata.workspace_index import db, indexer, nl_query, prune, queries, sync_review
from cxl_strata.workspace_index.parsers import infer_published_at
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
        comment_cols = {
            r["name"]
            for r in conn.execute("PRAGMA table_info(document_comments)").fetchall()
        }
    for name in (
        "remote_id",
        "author_name",
        "shared_at",
        "synced_at",
        "sync_ignored_at",
        "sync_ignore_reason",
        "published_at",
    ):
        assert name in cols
    for name in ("document_path", "remote_comment_id", "body", "created_at", "synced_at"):
        assert name in comment_cols


def test_infer_published_at_prefers_filename_then_frontmatter_then_title() -> None:
    assert (
        infer_published_at(filename="2026-07-02T22-29-11Z.md")
        == "2026-07-02T22:29:11Z"
    )
    assert (
        infer_published_at(
            filename="notes.md", frontmatter={"published_at": "2026-06-15"}
        )
        == "2026-06-15T00:00:00Z"
    )
    assert (
        infer_published_at(
            filename="notes.md",
            frontmatter={},
            title="Handoff — 2026-06-04T12-00-00Z",
        )
        == "2026-06-04T12:00:00Z"
    )
    assert infer_published_at(filename="notes.md") is None


def test_indexed_handoff_has_published_at_from_filename(workspace: Path) -> None:
    indexer.index_all(prune=False)
    with db.connect() as conn:
        db.init_db(conn)
        row = conn.execute(
            "SELECT published_at FROM documents WHERE path LIKE '%handoff%'"
        ).fetchone()
    assert row is not None
    assert row["published_at"] == "2026-06-30T12:00:00Z"


def test_recent_local_documents_sorted_by_published_date(workspace: Path) -> None:
    # Older handoff by filename stamp but touched most recently on disk.
    older = workspace / ".md" / "handoff" / "test-proj" / "2026-06-20T12-00-00Z.md"
    older.write_text("# Handoff — 2026-06-20T12-00-00Z\n\n- older doc\n", encoding="utf-8")
    indexer.index_all(prune=False)
    future = (datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp()
    os.utime(older, (future, future))
    indexer.index_all(prune=False)

    with db.connect() as conn:
        db.init_db(conn)
        items = queries.list_recent_local_documents(conn, hours=24 * 30, limit=50)

    paths = [item["path"] for item in items]
    newer_path = ".md/handoff/test-proj/2026-06-30T12-00-00Z.md"
    older_path = ".md/handoff/test-proj/2026-06-20T12-00-00Z.md"
    assert paths.index(newer_path) < paths.index(older_path)
    row = next(item for item in items if item["path"] == older_path)
    assert row["published_at"] == "2026-06-20T12:00:00Z"


def test_index_backfills_published_at_for_unchanged_rows(workspace: Path) -> None:
    indexer.index_all(prune=False)
    path = ".md/handoff/test-proj/2026-06-30T12-00-00Z.md"
    with db.connect() as conn:
        db.init_db(conn)
        conn.execute("UPDATE documents SET published_at = NULL WHERE path = ?", (path,))

    indexer.index_all(prune=False)

    with db.connect() as conn:
        db.init_db(conn)
        row = conn.execute(
            "SELECT published_at FROM documents WHERE path = ?", (path,)
        ).fetchone()
    assert row["published_at"] == "2026-06-30T12:00:00Z"


def test_recent_local_documents_kinds_and_project_filters(workspace: Path) -> None:
    (workspace / ".md" / "blueprints" / "test-proj.md").write_text(
        "# Test proj blueprint\n", encoding="utf-8"
    )
    indexer.index_all(prune=False)
    with db.connect() as conn:
        db.init_db(conn)
        both = queries.list_recent_local_documents(
            conn, hours=168, limit=50, kinds=["handoff", "blueprint"]
        )
        handoffs = queries.list_recent_local_documents(
            conn, hours=168, limit=50, kinds=["handoff"]
        )
        scoped = queries.list_recent_local_documents(
            conn, hours=168, limit=50, project="test-proj", kinds=["handoff"]
        )

    assert {item["kind"] for item in both} == {"handoff", "blueprint"}
    assert {item["kind"] for item in handoffs} == {"handoff"}
    assert all(item["project"] == "test-proj" for item in scoped)


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


def test_delete_remote_path_rejects_non_author(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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

    monkeypatch.setattr(
        documents.api_client,
        "delete_document",
        lambda remote_id: (_ for _ in ()).throw(AssertionError("should not delete")),
    )

    result = documents.delete_remote_path(path, actor_name="Someone Else")

    assert result["deleted"] is False
    assert result["error"] == "not author"


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


def test_list_shared_from_team_excludes_own_shares(workspace: Path) -> None:
    own_path = ".md/handoff/test-proj/2026-06-30T12-00-00Z.md"
    team_path = "shared/remote-handoff-1"
    with db.connect() as conn:
        db.init_db(conn)
        db.upsert_document(
            conn,
            {
                "id": "own-shared-handoff",
                "kind": "handoff",
                "project": "test-proj",
                "path": own_path,
                "title": "My shared handoff",
                "created_at": "2026-07-01T12:00:00Z",
                "updated_at": "2026-07-01T12:00:00Z",
                "body": "# Handoff\n\nShared by me.",
                "body_hash": "mine123",
                "plan_status": None,
                "linear_task_id": None,
                "files_changed": None,
                "deploy_commands": None,
                "tags": None,
                "folder_status": None,
                "status_mismatch": 0,
                "storage": "file",
                "origin": "shared",
                "remote_id": "remote-own-1",
                "author_name": "Enrique",
                "author_email": "enrique@example.com",
                "shared_at": "2026-07-01T12:00:00Z",
                "synced_at": "2026-07-01T12:00:00Z",
                "remote_updated_at": "2026-07-01T12:00:00Z",
            },
        )
        db.upsert_document(
            conn,
            {
                "id": "shared-remote-handoff-1",
                "kind": "handoff",
                "project": "test-proj",
                "path": team_path,
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
        items = queries.list_shared_from_team_documents(conn, limit=50, local_actor="Enrique")

    paths = {item["path"] for item in items}
    assert team_path in paths
    assert own_path not in paths


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


def test_scan_pending_includes_db_only_not_shared(workspace: Path) -> None:
    indexer.index_all(prune=False)
    path = ".md/handoff/test-proj/2026-06-30T12-00-00Z.md"
    with db.connect() as conn:
        db.init_db(conn)
        conn.execute(
            "UPDATE documents SET storage = 'db_only', remote_id = NULL WHERE path = ?",
            (path,),
        )

    pending = sync_review.scan_pending(project="test-proj", kind="handoff")
    paths = {item["path"] for item in pending}
    assert path in paths
    row = next(item for item in pending if item["path"] == path)
    assert row["local_status"] == "archived"
    assert row["sync_status"] == "not_shared"


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
    assert row.get("sync_locked") is False
    assert row.get("storage") == "file"


def test_project_library_includes_storage_meta(workspace: Path) -> None:
    indexer.index_all(prune=False)
    path = ".md/handoff/test-proj/2026-06-30T12-00-00Z.md"
    with db.connect() as conn:
        db.init_db(conn)
        conn.execute("UPDATE documents SET storage = 'db_only' WHERE path = ?", (path,))
        result = nl_query.project_library(conn, project="test-proj", limit=50)

    row = next(r for r in result["events"] if r["path"] == path)
    assert row["storage"] == "db_only"


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


def test_sync_locked_excludes_doc_from_batch_stash(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    indexer.index_all(prune=False)
    path = ".md/handoff/test-proj/2026-06-30T12-00-00Z.md"

    with db.connect() as conn:
        db.init_db(conn)
        db.set_sync_locked(conn, path=path, locked=True)

    captured: list[list[dict]] = []

    def fake_import_batch(payload: list[dict]) -> dict:
        captured.append(payload)
        return {"synced": [], "failed": []}

    monkeypatch.setattr(documents, "_author_from_config", lambda: (None, None))
    monkeypatch.setattr(documents.api_client, "documents_import_batch", fake_import_batch)

    result = documents.stash_paths([path])

    assert not captured
    assert result["skipped"] == [{"path": path, "reason": "sync_locked"}]

    result_allowed = documents.stash_paths([path], allow_locked=True)
    assert result_allowed["skipped"] == []
    assert len(captured) == 1


def test_sync_locked_marks_doc_not_syncable(workspace: Path) -> None:
    indexer.index_all(prune=False)
    path = ".md/handoff/test-proj/2026-06-30T12-00-00Z.md"

    with db.connect() as conn:
        db.init_db(conn)
        db.set_sync_locked(conn, path=path, locked=True)
        doc = queries.knowledge_get(conn, path)

    assert doc is not None
    assert doc["sync_locked"] is True
    assert doc["syncable"] is False

    with db.connect() as conn:
        db.init_db(conn)
        library = nl_query.project_library(conn, project="test-proj", limit=50)
    lib_row = next(r for r in library["events"] if r["path"] == path)
    assert lib_row["sync_locked"] is True


def test_stash_payload_includes_published_at(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    indexer.index_all(prune=False)
    captured: list[dict] = []

    def fake_import_batch(payload: list[dict]) -> dict:
        captured.extend(payload)
        return {"synced": [{"path": payload[0]["path"], "remote_id": "remote-1"}], "failed": []}

    monkeypatch.setattr(documents, "_author_from_config", lambda: (None, None))
    monkeypatch.setattr(documents.api_client, "documents_import_batch", fake_import_batch)

    result = documents.stash_paths([".md/handoff/test-proj/2026-06-30T12-00-00Z.md"])

    assert not result["failed"]
    assert captured[0]["published_at"] == "2026-06-30T12:00:00Z"


def test_local_comments_persist_and_sync_on_stash(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    indexer.index_all(prune=False)
    path = ".md/handoff/test-proj/2026-06-30T12-00-00Z.md"

    with db.connect() as conn:
        db.init_db(conn)
        db.add_comment(
            conn,
            comment_id="local-comment-1",
            document_path=path,
            body="Ship after QA.",
            author_name="Enrique",
        )
        comments = db.list_comments(conn, path)
        assert len(comments) == 1
        assert comments[0]["synced_at"] is None

    pushed: list[tuple[str, str]] = []

    def fake_create_comment(document_id: str, body: str, **kwargs) -> dict:
        pushed.append((document_id, body))
        return {"id": "remote-comment-1"}

    monkeypatch.setattr(documents, "_author_from_config", lambda: (None, None))
    monkeypatch.setattr(
        documents.api_client,
        "documents_import_batch",
        lambda payload: {
            "synced": [{"path": payload[0]["path"], "remote_id": "remote-1"}],
            "failed": [],
        },
    )
    monkeypatch.setattr(documents.api_client, "create_document_comment", fake_create_comment)

    result = documents.stash_paths([path])

    assert not result["failed"]
    assert pushed == [("remote-1", "Ship after QA.")]
    with db.connect() as conn:
        db.init_db(conn)
        comments = db.list_comments(conn, path)
    assert comments[0]["synced_at"]
    assert comments[0]["remote_comment_id"] == "remote-comment-1"


def test_pull_documents_upserts_published_at_and_comments(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    remote_row = {
        "id": "remote-doc-1",
        "path": ".md/handoff/team-proj/2026-06-25T09-00-00Z.md",
        "kind": "handoff",
        "project_slug": "team-proj",
        "title": "Team handoff",
        "body": "# Handoff\n\nFrom teammate.",
        "body_hash": "hash-1",
        "author_name": "Teammate",
        "author_email": "teammate@example.com",
        "published_at": "2026-06-25T09:00:00Z",
        "created_at": "2026-06-26T10:00:00Z",
        "updated_at": "2026-06-26T10:00:00Z",
        "shared_at": "2026-06-26T10:00:00Z",
        "storage_state": "db_only",
        "comments": [
            {
                "id": "remote-comment-9",
                "body": "Looks good.",
                "author_name": "Reviewer",
                "created_at": "2026-06-27T08:00:00Z",
            }
        ],
    }

    def fake_list_documents(**kwargs) -> list[dict]:
        return [remote_row] if kwargs.get("offset", 0) == 0 else []

    monkeypatch.setattr(pull.api_client, "list_documents", fake_list_documents)

    result = pull.pull_documents()

    assert result["pulled"] == 1
    assert result["comments_pulled"] == 1
    with db.connect() as conn:
        db.init_db(conn)
        row = conn.execute(
            "SELECT published_at, origin FROM documents WHERE path = ?",
            (remote_row["path"],),
        ).fetchone()
        comments = db.list_comments(conn, remote_row["path"])
    assert row["published_at"] == "2026-06-25T09:00:00Z"
    assert row["origin"] == "shared"
    assert comments[0]["body"] == "Looks good."
    assert comments[0]["remote_comment_id"] == "remote-comment-9"
    assert comments[0]["synced_at"]

    # Re-pull must not duplicate comments.
    result_again = pull.pull_documents()
    assert result_again["skipped"] == 1
    with db.connect() as conn:
        db.init_db(conn)
        comments = db.list_comments(conn, remote_row["path"])
    assert len(comments) == 1


def test_scan_pending_supports_multiple_kinds(workspace: Path) -> None:
    (workspace / ".cursor" / "plans" / "draft" / "sample-plan.md").write_text(
        "# Plan\n\nDo the thing.\n", encoding="utf-8"
    )
    indexer.index_all(prune=False)

    both = sync_review.scan_pending(kinds=["handoff", "plan"])
    plans_only = sync_review.scan_pending(kinds=["plan"])

    assert {item["kind"] for item in both} >= {"handoff", "plan"}
    assert {item["kind"] for item in plans_only} == {"plan"}
    assert all("published_at" in item for item in both)


def test_query_kind_filter_scopes_project_library(workspace: Path) -> None:
    (workspace / ".md" / "blueprints" / "test-proj.md").write_text(
        "---\nproject: test-proj\n---\n\n# Test proj blueprint\n", encoding="utf-8"
    )
    indexer.index_all(prune=False)

    with db.connect() as conn:
        db.init_db(conn)
        all_kinds = nl_query.parse_and_run(conn, "", project="test-proj", all_time=True)
        handoffs = nl_query.parse_and_run(
            conn, "", project="test-proj", all_time=True, kinds=["handoff"]
        )

    assert {e["kind"] for e in all_kinds["events"]} == {"handoff", "blueprint"}
    assert {e["kind"] for e in handoffs["events"]} == {"handoff"}


def test_project_library_events_include_remote_id_for_shared_docs(
    workspace: Path,
) -> None:
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
        library = nl_query.project_library(conn, project="test-proj", limit=50)

    row = next(r for r in library["events"] if r["path"] == path)
    assert row["remote_id"] == "remote-1"
    assert row["sync_status"] == "shared"
    assert row["syncable"] is False
