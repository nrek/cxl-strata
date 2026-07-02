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
    style = (root / "static" / "style.css").read_text(encoding="utf-8")

    assert "Recent Local Files" in index
    assert "Recent Locally Changed Files" not in index
    assert "Share to Team" in index
    assert "Potential Secrets" in index
    assert 'id="tab-recent"' in index
    assert 'id="tab-share"' in index
    assert 'id="tab-secrets"' in index
    assert 'id="panel-secrets"' in index
    assert 'id="secrets-local-table"' in index
    assert "Upload Local to STRATA API" not in index
    assert "function switchHomeTab(tab)" in app_js
    assert "async function openRecentFile(path, project)" in app_js
    assert "async function loadPotentialSecrets" in app_js
    assert "/api/documents/recent-local" in app_js
    assert "/api/sync/potential-secrets" in app_js
    assert 'hours: "168"' in app_js
    assert "RECENT_PAGE_SIZE = 12" in app_js
    assert "line-height: 1.45" in style
    assert "margin: 0.5rem 0 0.75rem" in style


def test_potential_secrets_rows_do_not_offer_share_to_team() -> None:
    root = _package_root()
    app_js = (root / "static" / "app.js").read_text(encoding="utf-8")
    secret_row = app_js.split("function secretRowHtml(item)", 1)[1].split(
        "function renderPagedList", 1
    )[0]

    assert "shareButtonHtml" not in secret_row
    assert "sync-one" not in secret_row
    assert "indexButtonHtml" in secret_row


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


def test_shared_rows_offer_remote_delete_action() -> None:
    root = _package_root()
    app_js = (root / "static" / "app.js").read_text(encoding="utf-8")
    sync_row = app_js.split("function syncRowHtml(item)", 1)[1].split(
        "function recentRowHtml", 1
    )[0]

    assert "deleteRemoteButtonHtml" in app_js
    assert "async function deleteRemotePath(path)" in app_js
    assert "/api/sync/delete-remote" in app_js
    assert "item.remote_id" in sync_row
    assert "deleteRemoteButtonHtml" in sync_row
    assert "shareButtonHtml" in sync_row


def test_sync_uses_non_blocking_redaction_toast() -> None:
    root = _package_root()
    app_js = (root / "static" / "app.js").read_text(encoding="utf-8")
    index = (root / "static" / "index.html").read_text(encoding="utf-8")
    style = (root / "static" / "style.css").read_text(encoding="utf-8")

    assert 'id="app-toast"' in index
    assert "function showToast(message" in app_js
    assert 'showToast("redacting secrets from sync..."' in app_js
    assert "alert(result.failed" not in app_js
    assert ".app-toast" in style
    assert ".app-toast.visible" in style


def test_tool_drawer_static_wiring() -> None:
    root = _package_root()
    app_js = (root / "static" / "app.js").read_text(encoding="utf-8")
    index = (root / "static" / "index.html").read_text(encoding="utf-8")
    style = (root / "static" / "style.css").read_text(encoding="utf-8")

    assert 'id="tool-drawer"' in index
    assert 'id="tool-drawer-toggle"' in index
    assert "fa-wrench" in index
    assert "Quick Commands" in index
    assert "SETUP STATUS" in index
    assert 'id="setup-status-list"' in index
    assert 'id="setup-status-refresh"' in index
    assert "Sync From Remote" in index
    assert "Sync All Local" in index
    assert "Strata Index" in index
    assert "Copy Prompts" in index
    assert "Strata Prune" in index
    assert "Strata Summarize" in index

    assert "function setToolDrawerOpen(open)" in app_js
    assert "function initToolDrawer()" in app_js
    assert "async function runToolCommand(command)" in app_js
    assert "async function copyToolPrompt(promptKey, btn)" in app_js
    assert "async function loadSetupStatus()" in app_js
    assert "function setupStatusHeading(checks)" in app_js
    assert "SETUP STATUS (${ready}/${total})" in app_js
    assert 'el.classList.toggle("collapsed", data?.ok === true && checks.length > 0)' in app_js
    assert "/api/setup/status" in app_js
    assert "TOOL_PROMPTS" in app_js
    assert 'prune: "/strata prune"' in app_js
    assert 'summarize: "/strata summary"' in app_js
    assert "Use STRATA prune" not in app_js
    assert "cursor-rules/strata-commands.md" not in app_js
    assert "/strata prune" in index
    assert "fa-times" in app_js

    assert "--tool-drawer-width: min(22.75rem, calc(100vw - 1rem))" in style
    assert "width: 36px" in style
    assert "height: 36px" in style
    assert "height: 75vh" in style
    assert "border-radius: 24px 0 0 24px" in style
    assert "transform: translate(100%, -50%)" in style
    assert "transform: translate(0, -50%)" in style
    assert "right: calc(var(--tool-drawer-width) - 18px)" in style
    assert ".tool-drawer" in style
    assert ".setup-status-list" in style
    assert ".setup-status-list.collapsed" in style
    assert ".setup-status-item" in style
    assert ".setup-status-dot" in style
    assert ".tool-drawer.open" in style
    assert ".tool-drawer-toggle" in style
    assert ".tool-drawer-toggle.open" in style


def test_quickstart_leads_with_workspace_defaults() -> None:
    repo_root = _package_root().parents[1]
    quickstart = (repo_root / "docs" / "quickstart.md").read_text(encoding="utf-8")

    assert "## 2. Initialize The Workspace" in quickstart
    assert "## 2. Initialize The Current Repo" not in quickstart
    assert "--repo my-repo" not in quickstart
    assert "strata pull --project my-project" not in quickstart
    assert "strata stash --project my-project" not in quickstart
