from __future__ import annotations

from pathlib import Path

from cxl_strata import pull as pull_mod
from cxl_strata.path_guard import is_scratch_path
from cxl_strata.pull import needs_pull
from cxl_strata.workspace_index import db
from cxl_strata.workspace_index.paths import set_workspace_root


def test_needs_pull_when_missing_local() -> None:
    row = {"path": ".md/handoff/x/a.md", "body_hash": "abc", "updated_at": "2026-01-01T00:00:00Z"}
    assert needs_pull(row, None) is True


def test_needs_pull_when_hash_differs() -> None:
    row = {"path": ".md/handoff/x/a.md", "body_hash": "new", "updated_at": "2026-01-01T00:00:00Z"}
    existing = {"body_hash": "old", "remote_updated_at": "2026-01-01T00:00:00Z"}
    assert needs_pull(row, existing) is True


def test_needs_pull_when_remote_updated_differs() -> None:
    row = {"path": ".md/handoff/x/a.md", "body_hash": "same", "updated_at": "2026-01-02T00:00:00Z"}
    existing = {"body_hash": "same", "remote_updated_at": "2026-01-01T00:00:00Z"}
    assert needs_pull(row, existing) is True


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
