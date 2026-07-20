from __future__ import annotations

from pathlib import Path

from cxl_strata import pull as pull_mod
from cxl_strata.path_guard import is_scratch_path
from cxl_strata.pull import needs_pull, remote_transfer_state
from cxl_strata.workspace_index import db
from cxl_strata.workspace_index.paths import set_workspace_root


def test_needs_pull_when_missing_local() -> None:
    row = {"path": ".md/handoff/x/a.md", "body_hash": "abc", "updated_at": "2026-01-01T00:00:00Z"}
    assert needs_pull(row, None) is True


def test_needs_pull_when_hash_differs() -> None:
    row = {"path": ".md/handoff/x/a.md", "body_hash": "new", "updated_at": "2026-01-01T00:00:00Z"}
    existing = {"body_hash": "old", "remote_updated_at": "2026-01-01T00:00:00Z"}
    assert needs_pull(row, existing) is True


def test_needs_pull_ignores_timestamp_format_or_value_when_hash_matches() -> None:
    row = {"path": ".md/handoff/x/a.md", "body_hash": "same", "updated_at": "2026-01-02T00:00:00Z"}
    existing = {"body_hash": "same", "remote_updated_at": "2026-01-01T00:00:00Z"}
    assert needs_pull(row, existing) is False


def test_needs_pull_when_fully_synced() -> None:
    row = {"path": ".md/handoff/x/a.md", "body_hash": "same", "updated_at": "2026-01-01T00:00:00Z"}
    existing = {"body_hash": "same", "remote_updated_at": "2026-01-01T00:00:00Z"}
    assert needs_pull(row, existing) is False


def test_needs_pull_when_hash_matches_and_remote_updated_null() -> None:
    """Post-stash legacy rows: content matches but remote_updated_at was never stamped."""
    row = {"path": ".md/handoff/x/a.md", "body_hash": "same", "updated_at": "2026-01-02T00:00:00Z"}
    existing = {"body_hash": "same", "remote_updated_at": None}
    assert needs_pull(row, existing) is False


def test_needs_pull_skips_locally_archived_tombstone() -> None:
    row = {"path": ".md/handoff/x/a.md", "body_hash": "new", "updated_at": "2026-01-02T00:00:00Z"}
    existing = {
        "body_hash": "archived-local",
        "remote_updated_at": "2026-01-01T00:00:00Z",
        "sync_ignored_at": "2026-01-01T12:00:00Z",
    }
    assert needs_pull(row, existing) is False


def test_remote_divergence_catalogues_instead_of_conflict() -> None:
    row = {
        "path": ".md/handoff/x/a.md",
        "body_hash": "remote-new",
        "updated_at": "2026-01-02T00:00:00Z",
    }
    existing = {
        "body_hash": "local-new",
        "last_pushed_body_hash": "shared-base",
        "remote_body_hash": "shared-base",
        "remote_id": "remote-1",
        "remote_updated_at": "2026-01-01T00:00:00+00:00",
        "sync_ignored_at": None,
    }

    assert remote_transfer_state(row, existing) == "catalog"
    assert needs_pull(row, existing) is True


def test_catalog_sibling_path_increments() -> None:
    assert (
        pull_mod.catalog_sibling_path(".md/handoff/x/a.md")
        == ".md/handoff/x/a_1.md"
    )
    assert (
        pull_mod.catalog_sibling_path(
            ".md/handoff/x/a.md", taken={".md/handoff/x/a_1.md"}
        )
        == ".md/handoff/x/a_2.md"
    )
    assert (
        pull_mod.catalog_sibling_path(".cursor/rules/blueprints.mdc")
        == ".cursor/rules/blueprints_1.mdc"
    )


def test_pull_catalogues_divergent_remote_as_sibling(
    tmp_path: Path, monkeypatch
) -> None:
    set_workspace_root(tmp_path)
    path = ".md/handoff/x/2026-01-01T00-00-00Z.md"
    with db.connect() as conn:
        db.init_db(conn)
        db.upsert_document(
            conn,
            {
                "id": "local-doc",
                "kind": "handoff",
                "project": "x",
                "path": path,
                "title": "Local edit",
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-02T00:00:00Z",
                "body": "# local\n",
                "body_hash": "local-new",
                "plan_status": None,
                "linear_task_id": None,
                "files_changed": None,
                "deploy_commands": None,
                "tags": None,
                "folder_status": None,
                "status_mismatch": 0,
                "storage": "db_only",
                "origin": "local",
                "remote_id": "remote-1",
                "author_name": "Local Author",
                "author_email": "local@example.com",
                "shared_at": "2026-01-01T00:00:00Z",
                "synced_at": "2026-01-01T00:00:00Z",
                "remote_updated_at": "2026-01-01T00:00:00Z",
                "last_pushed_body_hash": "shared-base",
                "remote_body_hash": "shared-base",
            },
        )

    rows = [
        {
            "id": "remote-1",
            "kind": "handoff",
            "project_slug": "x",
            "path": path,
            "title": "Remote edit",
            "body": "# remote\n",
            "body_hash": "remote-new",
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-02T12:00:00Z",
            "author_name": "Remote Author",
            "author_email": "remote@example.com",
            "comments": [],
        }
    ]
    monkeypatch.setattr(pull_mod.api_client, "list_documents", lambda **kwargs: rows)

    result = pull_mod.pull_documents()

    assert result["conflicts"] == 0
    assert result["catalogued"] == 1
    assert result["pulled"] == 1
    catalog = ".md/handoff/x/2026-01-01T00-00-00Z_1.md"
    with db.connect() as conn:
        local = conn.execute(
            "SELECT body, body_hash, remote_body_hash, last_pushed_body_hash"
            " FROM documents WHERE path = ?",
            (path,),
        ).fetchone()
        twin = conn.execute(
            "SELECT body, body_hash, title, author_name, remote_id, storage"
            " FROM documents WHERE path = ?",
            (catalog,),
        ).fetchone()
    assert local["body"] == "# local\n"
    assert local["body_hash"] == "local-new"
    assert local["remote_body_hash"] == "remote-new"
    assert local["last_pushed_body_hash"] == "shared-base"
    assert twin["body"] == "# remote\n"
    assert twin["body_hash"] == "remote-new"
    assert twin["author_name"] == "Remote Author"
    assert twin["remote_id"] is None
    assert twin["storage"] == "db_only"
    assert "Remote Author" in twin["title"]

    # Same remote tip must not create another sibling.
    result2 = pull_mod.pull_documents()
    assert result2["catalogued"] == 0
    with db.connect() as conn:
        twins = conn.execute(
            "SELECT path FROM documents WHERE path GLOB ?",
            (".md/handoff/x/2026-01-01T00-00-00Z_[0-9]*.md",),
        ).fetchall()
    assert [r["path"] for r in twins] == [catalog]


def test_fetch_all_remote_documents_has_no_legacy_2000_row_cap(monkeypatch) -> None:
    rows = [
        {"id": f"remote-{i}", "path": f".md/handoff/x/{i}.md", "body_hash": str(i)}
        for i in range(2105)
    ]

    def fake_list_documents(**kwargs) -> list[dict]:
        offset = kwargs["offset"]
        limit = kwargs["limit"]
        return rows[offset : offset + limit]

    monkeypatch.setattr(pull_mod.api_client, "list_documents", fake_list_documents)

    assert len(pull_mod.fetch_all_remote_documents()) == 2105


def test_is_scratch_path_blocks_hidden_subdirectories() -> None:
    assert is_scratch_path(".codex/.tmp/plugins/plugins/zoom/SKILL.md") is True
    assert is_scratch_path(".claude/.cache/notes.md") is True
    assert is_scratch_path(".md/.handoff/legacy/2026-01-01T00-00-00Z.md") is True
    assert is_scratch_path(".codex\\.tmp\\win\\style.md") is True


def test_is_scratch_path_allows_workspace_knowledge() -> None:
    assert is_scratch_path(".md/handoff/cxl-strata/2026-07-08T12-00-00Z.md") is False
    assert is_scratch_path(".cursor/rules/blueprints.mdc") is False
    assert is_scratch_path(".cursor/skills/strata/SKILL.md") is False
    assert is_scratch_path(".codex/AGENTS.md") is False
    assert is_scratch_path("") is False


def _remote_row(*, kind: str, path: str, body: str) -> dict:
    return {
        "id": f"remote-{kind}-1",
        "kind": kind,
        "project_slug": "test-proj",
        "path": path,
        "title": "Shared doc",
        "body": body,
        "body_hash": "hash1",
        "created_at": "2026-07-01T00:00:00Z",
        "updated_at": "2026-07-01T00:00:00Z",
    }


def test_pull_materializes_rule_to_disk(tmp_path: Path, monkeypatch) -> None:
    set_workspace_root(tmp_path)
    rows = [_remote_row(kind="rule", path=".cursor/rules/blueprints.mdc", body="# Rule body\n")]
    monkeypatch.setattr(pull_mod.api_client, "list_documents", lambda **kwargs: rows)

    result = pull_mod.pull_documents()

    assert result["pulled"] == 1
    assert result["materialized"] == 1
    rule_file = tmp_path / ".cursor" / "rules" / "blueprints.mdc"
    assert rule_file.is_file()
    assert rule_file.read_text(encoding="utf-8") == "# Rule body\n"
    with db.connect() as conn:
        row = conn.execute(
            "SELECT storage FROM documents WHERE path = ?",
            (".cursor/rules/blueprints.mdc",),
        ).fetchone()
    assert row["storage"] == "file"


def test_pull_does_not_materialize_handoffs(tmp_path: Path, monkeypatch) -> None:
    set_workspace_root(tmp_path)
    rows = [
        _remote_row(
            kind="handoff",
            path=".md/handoff/test-proj/2026-07-01T00-00-00Z.md",
            body="# Handoff\n",
        )
    ]
    monkeypatch.setattr(pull_mod.api_client, "list_documents", lambda **kwargs: rows)

    result = pull_mod.pull_documents()

    assert result["pulled"] == 1
    assert result["materialized"] == 0
    assert not (tmp_path / ".md" / "handoff" / "test-proj" / "2026-07-01T00-00-00Z.md").exists()
