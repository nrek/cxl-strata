from __future__ import annotations

from cxl_strata.path_guard import is_scratch_path
from cxl_strata.pull import needs_pull


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
