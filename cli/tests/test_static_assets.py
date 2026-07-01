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


def test_home_tabs_recent_local_and_share_to_team() -> None:
    root = _package_root()
    app_js = (root / "static" / "app.js").read_text(encoding="utf-8")
    index = (root / "static" / "index.html").read_text(encoding="utf-8")

    assert "Recent Locally Changed Files" in index
    assert "Share to Team" in index
    assert 'id="tab-recent"' in index
    assert 'id="tab-share"' in index
    assert "Upload Local to STRATA API" not in index
    assert "function switchHomeTab(tab)" in app_js
    assert "async function openRecentFile(path, project)" in app_js
    assert "/api/documents/recent-local" in app_js
    assert "RECENT_PAGE_SIZE = 6" in app_js


def test_author_filter_controls() -> None:
    root = _package_root()
    app_js = (root / "static" / "app.js").read_text(encoding="utf-8")
    index = (root / "static" / "index.html").read_text(encoding="utf-8")

    assert 'id="files-filter-author"' in index
    assert 'id="scoped-filter-author"' in index
    assert "/api/authors" in app_js
    assert "async function loadAuthors()" in app_js
    assert "function filesFilterParams()" in app_js


def test_modal_and_action_ctas() -> None:
    root = _package_root()
    app_js = (root / "static" / "app.js").read_text(encoding="utf-8")
    index = (root / "static" / "index.html").read_text(encoding="utf-8")

    assert 'id="doc-share-btn"' in index
    assert 'id="doc-index-btn"' in index
    assert "Share to Team" in app_js
    assert "Re-index Locally" in app_js
    assert "shareTooltip" in app_js
    assert "indexTooltip" in app_js
    assert "function updateDocModalActions(doc, path)" in app_js
    assert "async function shareDocFromModal()" in app_js


def test_search_cards_include_sync_button_wiring() -> None:
    root = _package_root()
    app_js = (root / "static" / "app.js").read_text(encoding="utf-8")
    index = (root / "static" / "index.html").read_text(encoding="utf-8")

    assert "function canSyncResult(item)" in app_js
    assert "result-share-btn" in app_js
    assert "result-index-btn" in app_js
    assert "shareSearchResult(el.dataset.path)" in app_js
    assert "async function shareSearchResult(path)" in app_js
    assert "Share to Team" in index
