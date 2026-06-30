from __future__ import annotations

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
