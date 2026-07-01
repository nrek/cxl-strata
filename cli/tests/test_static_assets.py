from __future__ import annotations

from pathlib import Path

import cxl_strata


def _package_root() -> Path:
    return Path(cxl_strata.__file__).resolve().parent


def test_local_app_includes_strata_logo_asset() -> None:
    root = _package_root()
    logo = root / "static" / "strata-logo.png"
    index = (root / "static" / "index.html").read_text(encoding="utf-8")

    assert logo.is_file()
    assert logo.read_bytes().startswith(b"\x89PNG")
    assert "/static/strata-logo.png" in index


def test_project_click_browses_project_without_search_text() -> None:
    root = _package_root()
    app_js = (root / "static" / "app.js").read_text(encoding="utf-8")

    assert "async function browseProject(project)" in app_js
    assert "enterProject(btn.dataset.project, { browse: true })" in app_js
    assert 'q: ""' in app_js


def test_search_cards_include_sync_button_wiring() -> None:
    root = _package_root()
    app_js = (root / "static" / "app.js").read_text(encoding="utf-8")
    index = (root / "static" / "index.html").read_text(encoding="utf-8")

    assert "function canSyncResult(item)" in app_js
    assert "result-sync-btn" in app_js
    assert "syncSearchResult(el.dataset.path)" in app_js
    assert "async function syncSearchResult(path)" in app_js
    assert "Upload Local to STRATA API" in index
