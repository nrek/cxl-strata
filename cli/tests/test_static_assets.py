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
    assert "Shared to Team" in index
    assert "Shared from Team" in index
    assert "Potential Secrets" in index
    assert 'id="tab-recent"' in index
    assert 'id="tab-share"' in index
    assert 'id="tab-received"' in index
    assert 'id="tab-secrets"' in index
    assert 'id="panel-received"' in index
    assert 'id="received-from-team-table"' in index
    assert 'id="panel-secrets"' in index
    assert 'id="secrets-local-table"' in index
    assert "Upload Local to STRATA API" not in index
    assert "function switchHomeTab(tab)" in app_js
    assert "function bindHomeTabControls()" in app_js
    assert "async function openRecentFile(path, project)" in app_js
    assert "async function loadPotentialSecrets" in app_js
    assert "async function loadSharedFromTeam" in app_js
    assert "/api/documents/recent-local" in app_js
    assert "/api/documents/shared-from-team" in app_js
    assert "/api/sync/potential-secrets" in app_js
    assert 'hours: "168"' in app_js
    assert "RECENT_PAGE_SIZE = 12" in app_js
    assert "line-height: 1.45" in style
    assert "margin: 0.5rem 0 0.75rem" in style


def test_potential_secrets_rows_do_not_offer_share_to_team() -> None:
    root = _package_root()
    app_js = (root / "static" / "app.js").read_text(encoding="utf-8")
    secret_row = app_js.split("function secretRowHtml(item)", 1)[1].split(
        "function bindRecentRowActions", 1
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
    assert "function syncHomeAuthorToScoped()" in app_js


def test_modal_and_action_ctas() -> None:
    root = _package_root()
    app_js = (root / "static" / "app.js").read_text(encoding="utf-8")
    index = (root / "static" / "index.html").read_text(encoding="utf-8")
    style = (root / "static" / "style.css").read_text(encoding="utf-8")

    assert 'id="doc-share-btn"' in index
    assert 'id="doc-index-btn"' in index
    assert 'id="doc-lock-btn"' in index
    assert 'id="doc-delete-strata-btn"' in index
    assert 'id="delete-strata-modal"' in index
    assert "fa-lock-open" in index
    assert "fa-trash" in index
    assert "Share to Team" in app_js
    assert "Re-index Locally" in app_js
    assert "canShowLockItem" in app_js
    assert "canDeleteFromStrata" in app_js
    assert "isIndexedDoc" in app_js
    assert "lockButtonHtml" in app_js
    assert "bindRecentRowActions" in app_js
    assert "toggleSyncLock" in app_js
    assert "/api/sync/lock" in app_js
    assert "lock-btn-unlocked" in style
    assert "lock-btn-locked" in style
    assert "shareTooltip" in app_js
    assert "indexTooltip" in app_js
    assert "function updateDocModalActions(doc, path)" in app_js
    assert "async function loadRemoteConfig(stats)" in app_js
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

    assert "deleteStrataButtonHtml" in app_js
    assert "canDeleteFromStrata" in app_js
    assert "isIndexedDoc" in app_js
    assert "openDeleteStrataConfirm" in app_js
    assert "/api/sync/delete-remote" in app_js
    assert "canDeleteFromStrata(item)" in sync_row
    assert "deleteStrataButtonHtml" in sync_row
    assert "canShowLockItem(item)" in sync_row
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
    assert "Files to Strata" in index
    assert "Sync to Remote" in index
    assert "Pull from Remote" in index
    # Files to Strata (index) must be the first quick command
    assert index.find('data-tool-command="index-local"') < index.find(
        'data-tool-command="sync-local"'
    )
    assert index.find('data-tool-command="sync-local"') < index.find(
        'data-tool-command="sync-remote"'
    )
    assert 'id="count-index-pending"' in index
    assert 'id="count-sync-pending"' in index
    assert 'id="count-pull-pending"' in index
    assert "function confirmLargeSync(count)" in app_js
    assert "async function refreshToolCounts()" in app_js
    assert "function setToolActionDot(hasActions)" in app_js
    assert 'id="tool-drawer-dot"' in index
    assert ".tool-drawer-dot" in style
    assert 'id="client-update-btn"' in index
    assert "[ update ]" in index
    assert 'data-accent-picker' in index
    assert "fa-paintbrush" in index
    assert "function initAccentThemePicker()" in app_js
    assert "function applyAccentTheme(themeId)" in app_js
    assert 'strata:accent-theme' in app_js
    assert "ACCENT_THEMES" in app_js
    assert ".accent-theme-picker" in style
    assert ".accent-theme-menu" in style
    assert "function renderUpdateCta(status)" in app_js
    assert "async function refreshUpdateStatus()" in app_js
    assert "async function runClientUpdate()" in app_js
    assert "/api/update/status" in app_js
    assert "/api/update/run" in app_js
    assert ".client-update-btn" in style
    assert "remote-sync-btn" not in app_js
    assert "stats-sync-btn" not in style
    assert "function pullRemote(" not in app_js
    assert "/api/sync/status" in app_js
    assert "/api/index/run" in app_js
    assert "Are you sure you want to sync ${count} files to Strata?" in app_js
    assert ".tool-count" in style
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
    assert ".tool-drawer-toggle.open .tool-drawer-dot" in style


def test_kind_filter_chips_replace_kind_select() -> None:
    root = _package_root()
    app_js = (root / "static" / "app.js").read_text(encoding="utf-8")
    index = (root / "static" / "index.html").read_text(encoding="utf-8")
    style = (root / "static" / "style.css").read_text(encoding="utf-8")

    assert 'id="files-filter-kinds"' in index
    assert 'id="scoped-filter-kinds"' in index
    assert 'id="files-filter-kind"' not in index
    assert 'value="section"' in index
    assert "function selectedKinds(containerSel)" in app_js
    assert 'params.set("kinds", kinds.join(","))' in app_js
    assert "function scopedKindsFilter()" in app_js
    assert ".kind-chip" in style
    assert ".kind-filter" in style


def test_author_dropdown_hidden_without_other_authors() -> None:
    root = _package_root()
    app_js = (root / "static" / "app.js").read_text(encoding="utf-8")
    index = (root / "static" / "index.html").read_text(encoding="utf-8")

    assert "function hasNonLocalAuthors()" in app_js
    assert "function updateAuthorFilterVisibility()" in app_js
    # Author selects start hidden and only show when teammates exist.
    assert 'id="files-filter-author" class="strata-select hidden"' in index
    assert 'id="scoped-filter-author" class="strata-select hidden"' in index
    # Regression: loadAuthors must use id selectors with '#'.
    assert 'const el = $(`#${id}`);' in app_js


def test_doc_modal_comment_wiring() -> None:
    root = _package_root()
    app_js = (root / "static" / "app.js").read_text(encoding="utf-8")
    index = (root / "static" / "index.html").read_text(encoding="utf-8")
    style = (root / "static" / "style.css").read_text(encoding="utf-8")

    assert 'id="doc-comments"' in index
    assert 'id="doc-comments-list"' in index
    assert 'id="doc-comment-form"' in index
    assert 'id="doc-comment-input"' in index
    assert "async function submitDocComment(event)" in app_js
    assert "function renderDocComments(comments)" in app_js
    assert "/api/documents/comment" in app_js
    assert ".doc-comments" in style
    assert ".doc-comment-form" in style


def test_sync_commands_scope_to_active_project() -> None:
    root = _package_root()
    app_js = (root / "static" / "app.js").read_text(encoding="utf-8")

    assert "const scopedProject =" in app_js
    assert 'JSON.stringify(scopedProject ? { project: scopedProject } : {})' in app_js
    assert "project=${encodeURIComponent(project)}" in app_js


def test_results_sort_by_published_date() -> None:
    root = _package_root()
    app_js = (root / "static" / "app.js").read_text(encoding="utf-8")

    assert "function publishedAt(ev)" in app_js
    assert "ev.at || ev.published_at || ev.created_at || ev.updated_at" in app_js
    assert "item.published_at || item.created_at || item.updated_at" in app_js


def test_quickstart_leads_with_workspace_defaults() -> None:
    repo_root = _package_root().parents[1]
    quickstart = (repo_root / "docs" / "quickstart.md").read_text(encoding="utf-8")

    assert "## 2. Initialize The Workspace" in quickstart
    assert "## 2. Initialize The Current Repo" not in quickstart
    assert "--repo my-repo" not in quickstart
    assert "strata pull --project my-project" not in quickstart
    assert "strata stash --project my-project" not in quickstart


def test_public_docs_use_neutral_org_and_workspace_examples() -> None:
    repo_root = _package_root().parents[1]
    public_docs = [
        repo_root / "README.md",
        repo_root / "cli" / "README.md",
        repo_root / "cli" / "cxl_strata.egg-info" / "PKG-INFO",
        repo_root / "docs" / "quickstart.md",
        repo_root / "docs" / "client-installation.md",
        repo_root / "docs" / "troubleshooting.md",
    ]

    for path in public_docs:
        text = path.read_text(encoding="utf-8")
        assert "commonspace" not in text.lower(), path
        assert "D:\\projects" not in text, path
