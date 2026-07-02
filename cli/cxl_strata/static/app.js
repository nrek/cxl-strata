// Display-only pluralization; API/db kinds stay singular.
const KIND_PLURALS = {
  blueprint: "blueprints",
  handoff: "handoffs",
  plan: "plans",
  rule: "rules",
};

function kindLabel(kind, count) {
  if (count !== 0 && KIND_PLURALS[kind]) return KIND_PLURALS[kind];
  return kind;
}

const EXAMPLES = [
  "last time I touched font awesome",
  "what did we do last week",
  "deploy apache2",
];

const SYNC_PAGE_SIZE = 6;
const RECENT_PAGE_SIZE = 12;

const ACTION = {
  shareLabel: "Share to Team",
  shareBusy: "Sharing…",
  shareTooltip:
    "Upload this file to the STRATA API so teammates can search and read it centrally.",
  indexLabel: "Re-index Locally",
  indexBusy: "Indexing…",
  indexTooltip:
    "Re-read this file from disk and refresh your local SQLite index without uploading.",
  deleteRemoteLabel: "Delete Remote",
  deleteRemoteBusy: "Deleting…",
  deleteRemoteTooltip:
    "Delete the shared copy from STRATA and ignore this local file in future sync prompts.",
  deleteStrataTooltip: "Delete your shared copy from STRATA (local file is kept).",
  lockUnlockedTooltip: "Unlocked — included in batch sync to STRATA API.",
  lockLockedTooltip: "Locked — excluded from batch sync to STRATA API.",
};

const TOOL_PROMPTS = {
  prune: "/strata prune",
  summarize: "/strata summary",
};
let toastTimer = null;

const $ = (sel) => document.querySelector(sel);

marked.setOptions({ gfm: true, breaks: true });

const state = {
  view: "home",
  activeProject: null,
  allProjects: [],
  latestProjects: [],
  apiOnline: false,
  syncItems: [],
  syncPage: 0,
  secretItems: [],
  secretPage: 0,
  recentItems: [],
  recentPage: 0,
  receivedItems: [],
  receivedPage: 0,
  homeTab: "recent",
  activeDocPath: null,
  pendingDeletePath: null,
  authors: [],
  localActorName: "",
  hasSearched: false,
  remotePending: 0,
};

const MOJIBAKE_MARKERS = /â[\u0080-\u00BF]|Ã.|Â.|\uFFFD/;

function recoverUtf8FromLatin1(text) {
  try {
    const bytes = new Uint8Array(text.length);
    for (let i = 0; i < text.length; i += 1) {
      bytes[i] = text.charCodeAt(i) & 0xff;
    }
    const recovered = new TextDecoder("utf-8", { fatal: false }).decode(bytes);
    const before = (text.match(/â€|Ã.|Â./g) || []).length;
    const after = (recovered.match(/â€|Ã.|Â./g) || []).length;
    if (after < before || (text.includes("â€") && !recovered.includes("â€"))) {
      return recovered;
    }
    if (recovered.includes("\u2014") && !text.includes("\u2014")) {
      return recovered;
    }
  } catch (_) {
    /* keep original */
  }
  return text;
}

function fixMojibake(text) {
  if (!text) return "";
  let out = text;

  if (MOJIBAKE_MARKERS.test(out)) {
    out = recoverUtf8FromLatin1(out);
  }

  out = out
    .replace(/â€./g, "\u2014")
    .replace(/â€™/g, "\u2019")
    .replace(/â€œ/g, "\u201c")
    .replace(/â€\u009d/g, "\u201d")
    .replace(/â†'/g, "\u2192")
    .replace(/â†\u0090/g, "\u2190")
    .replace(/Ã©/g, "é")
    .replace(/Ã¯/g, "ï")
    .replace(/Â·/g, "\u00b7")
    .replace(/Â /g, " ");

  return out
    .replace(/Handoff\s+\uFFFD\s+/g, "Handoff \u2014 ")
    .replace(/Handoff\s+(?=\d{4}-)/g, "Handoff \u2014 ")
    .replace(/(\S)\uFFFD(\s)/g, "$1\u2014$2");
}

function titleFromPath(path) {
  const name = (path || "").split("/").pop()?.replace(/\.md$/i, "") || "";
  const m = name.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2})-(\d{2})-(\d{2})Z$/);
  if (!m) return fixMojibake(name);
  const iso = `${m[1]}-${m[2]}-${m[3]}T${m[4]}:${m[5]}:${m[6]}Z`;
  return fmtDate(iso);
}

function prepareBodyForDisplay(body) {
  let text = fixMojibake(body || "");
  let strippedLead = false;

  text = text.replace(/^#\s+Handoff\s+[—–-]\s*.+$/gim, (line) => {
    if (!strippedLead) {
      strippedLead = true;
      return "";
    }
    return line.replace(/^#\s+/, "## ");
  });

  return text.replace(/\n{3,}/g, "\n\n").trim();
}

function displayDocTitle(doc, path) {
  const project = doc.project || "";
  const when = titleFromPath(path);
  if (project && when) return `${project} · ${when}`;
  return when || fixMojibake(doc.title || "") || path.split("/").pop();
}

function friendlyCardTitle(item) {
  const path = item.path || "";
  const type = item.type || item.kind || "doc";
  const project = item.project || "";
  const when = titleFromPath(path);

  if (type === "section") {
    const heading = fixMojibake(item.title || "");
    if (heading && !/^Handoff\s/i.test(heading)) {
      return heading.replace(/^#+\s*/, "").slice(0, 80);
    }
  }

  if (type === "plan") {
    return fixMojibake(item.name || item.title || "Plan");
  }

  if (when) {
    return project ? `${project} · ${when}` : when;
  }

  return fixMojibake(item.title || item.name || path.split("/").pop() || "Untitled");
}

function renderMarkdown(text) {
  if (!text) return "<p><em>(empty)</em></p>";
  return marked.parse(text);
}

function stripMarkdown(text) {
  if (!text) return "";
  return fixMojibake(
    text
      .replace(/```[\s\S]*?```/g, " ")
      .replace(/`([^`]+)`/g, "$1")
      .replace(/^#{1,6}\s+/gm, "")
      .replace(/\*\*([^*]+)\*\*/g, "$1")
      .replace(/\*([^*]+)\*/g, "$1")
      .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
      .replace(/^>\s+/gm, "")
      .replace(/^[-*+]\s+/gm, "")
      .replace(/\s+/g, " ")
      .trim()
  );
}

function fmtDate(iso) {
  if (!iso) return "unknown date";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso.slice(0, 10);
  return d.toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

function normalizeEventAt(at, path = "") {
  if (at) {
    if (at[4] === ":") {
      return `${at.slice(0, 4)}-${at.slice(5, 7)}-${at.slice(8, 10)}${at.slice(10)}`;
    }
    return at;
  }
  const m = path.match(/\/(\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z)\.md/);
  if (!m) return "";
  const raw = m[1];
  const [datePart, timePartRaw] = raw.split("T");
  return `${datePart}T${timePartRaw.replace(/-/g, ":").replace(/Z$/, "")}Z`;
}

function dayKey(iso, path = "") {
  const normalized = normalizeEventAt(iso, path);
  if (!normalized) return "Unknown";
  return normalized.slice(0, 10);
}

function eventSortKey(ev) {
  const at = normalizeEventAt(ev.at || ev.updated_at || ev.created_at, ev.path || "");
  const t = Date.parse(at);
  return Number.isNaN(t) ? 0 : t;
}

function sortEventsNewestFirst(events) {
  return [...events].sort((a, b) => eventSortKey(b) - eventSortKey(a));
}

function esc(s) {
  const el = document.createElement("span");
  el.textContent = s ?? "";
  return el.innerHTML;
}

async function api(path, opts) {
  const res = await fetch(path, opts);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

function showView(name) {
  state.view = name;
  $("#view-home").classList.toggle("hidden", name !== "home");
  $("#view-home").classList.toggle("view-active", name === "home");
  $("#view-app").classList.toggle("hidden", name !== "app");
  $("#view-app").classList.toggle("view-active", name === "app");
}

function setAppSidebarVisible(visible) {
  $("#sidebar")?.classList.toggle("hidden", !visible);
  $("#view-app")?.classList.toggle("pre-search", !visible);
}

function setAppResultsVisible(visible) {
  $("#output")?.classList.toggle("hidden", !visible);
  if (!visible) {
    $("#meta")?.classList.add("hidden");
  }
}

function setToolDrawerOpen(open) {
  const drawer = $("#tool-drawer");
  const toggle = $("#tool-drawer-toggle");
  const icon = toggle?.querySelector("i");
  if (!drawer || !toggle || !icon) return;

  drawer.classList.toggle("open", open);
  drawer.setAttribute("aria-hidden", open ? "false" : "true");
  toggle.classList.toggle("open", open);
  toggle.setAttribute("aria-expanded", open ? "true" : "false");
  toggle.setAttribute("aria-label", open ? "Close tool drawer" : "Open tool drawer");
  icon.classList.toggle("fa-wrench", !open);
  icon.classList.toggle("fa-times", open);
}

function setToolStatus(message) {
  const el = $("#tool-drawer-status");
  if (el) el.textContent = message || "";
}

function showToast(message, { timeout = 2600 } = {}) {
  const el = $("#app-toast");
  if (!el) {
    setToolStatus(message);
    return;
  }
  window.clearTimeout(toastTimer);
  el.textContent = message;
  el.hidden = false;
  window.requestAnimationFrame(() => el.classList.add("visible"));
  if (timeout > 0) {
    toastTimer = window.setTimeout(() => {
      el.classList.remove("visible");
      window.setTimeout(() => {
        if (!el.classList.contains("visible")) el.hidden = true;
      }, 180);
    }, timeout);
  }
}

function setupStatusHtml(item) {
  const stateClass = item.ok ? "ok" : "missing";
  const stateLabel = item.ok ? "Ready" : "Needs setup";
  return `
    <article class="setup-status-item ${stateClass}">
      <div class="setup-status-main">
        <span class="setup-status-dot" aria-hidden="true"></span>
        <div>
          <strong>${esc(item.label)}</strong>
          <span>${esc(item.path || "")}</span>
        </div>
      </div>
      ${
        item.ok
          ? `<code>${stateLabel}</code>`
          : `<button type="button" class="tool-mini-btn setup-fix-copy" data-fix="${esc(item.fix || "")}">Copy fix</button>`
      }
    </article>`;
}

function setupStatusHeading(checks) {
  const total = checks.length || 4;
  const ready = checks.filter((item) => item.ok).length;
  return `SETUP STATUS (${ready}/${total})`;
}

function renderSetupStatus(data) {
  const el = $("#setup-status-list");
  const heading = $("#tool-setup-title");
  if (!el) return;
  const checks = data?.checks || [];
  if (heading) heading.textContent = setupStatusHeading(checks);
  if (!checks.length) {
    el.classList.remove("collapsed");
    el.innerHTML = '<p class="tool-muted">No setup checks returned.</p>';
    return;
  }
  el.classList.toggle("collapsed", data?.ok === true && checks.length > 0);
  el.innerHTML = checks.map(setupStatusHtml).join("");
  el.querySelectorAll(".setup-fix-copy").forEach((btn) => {
    btn.addEventListener("click", () => copySetupFix(btn));
  });
}

async function loadSetupStatus() {
  const el = $("#setup-status-list");
  const heading = $("#tool-setup-title");
  if (heading) heading.textContent = "SETUP STATUS";
  if (el) el.innerHTML = '<p class="tool-muted">Checking local setup…</p>';
  try {
    const data = await api("/api/setup/status");
    renderSetupStatus(data);
    setToolStatus(data.ok ? "Setup ready." : "Setup needs attention.");
  } catch (err) {
    if (el) el.innerHTML = `<p class="tool-muted">Setup check failed: ${esc(err.message)}</p>`;
  }
}

async function copySetupFix(btn) {
  const fix = btn?.dataset.fix;
  if (!fix) return;
  const idle = btn.textContent;
  try {
    await copyText(fix);
    btn.textContent = "Copied";
    setToolStatus("Fix command copied.");
  } catch (err) {
    setToolStatus(`Copy failed: ${err.message}`);
  } finally {
    window.setTimeout(() => {
      btn.textContent = idle;
    }, 1400);
  }
}

function uniquePaths(items) {
  return [...new Set((items || []).map((item) => item.path).filter(Boolean))];
}

async function copyText(text) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }

  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  document.body.appendChild(textarea);
  textarea.select();
  document.execCommand("copy");
  textarea.remove();
}

async function copyToolPrompt(promptKey, btn) {
  const text = TOOL_PROMPTS[promptKey];
  if (!text) return;
  const idle = btn?.querySelector("code")?.textContent || "copy prompt";
  try {
    await copyText(text);
    setToolStatus("Prompt copied.");
    if (btn) btn.querySelector("code").textContent = "copied";
  } catch (err) {
    setToolStatus(`Copy failed: ${err.message}`);
  } finally {
    if (btn) {
      window.setTimeout(() => {
        btn.querySelector("code").textContent = idle;
      }, 1400);
    }
  }
}

async function runToolCommand(command) {
  const btn = document.querySelector(`[data-tool-command="${cssEscape(command)}"]`);
  if (btn?.disabled) return;
  if (btn) btn.disabled = true;
  setToolStatus("Running...");

  try {
    if (command === "sync-remote") {
      if (!state.apiOnline) {
        setToolStatus("Remote API is offline. Local search remains available.");
        return;
      }
      await api("/api/pull", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      await refreshDashboard();
      setToolStatus("Remote sync complete.");
      return;
    }

    if (command === "sync-local") {
      if (!state.syncItems.length) await loadSyncLocal({ resetPage: false });
      const paths = batchSyncPaths(state.syncItems);
      if (!paths.length) {
        setToolStatus("All local artifacts are already shared or locked.");
        return;
      }
      await syncPaths(paths);
      await refreshRemotePending();
      setToolStatus(`Shared ${paths.length} local artifact${paths.length === 1 ? "" : "s"}.`);
      return;
    }

    if (command === "index-local") {
      await Promise.all([
        loadRecentLocal({ resetPage: false }),
        loadSyncLocal({ resetPage: false }),
      ]);
      const paths = uniquePaths([...state.recentItems, ...state.syncItems]);
      if (!paths.length) {
        setToolStatus("No local artifacts found to index.");
        return;
      }
      await indexPaths(paths);
      setToolStatus(`Indexed ${paths.length} local artifact${paths.length === 1 ? "" : "s"}.`);
      return;
    }
  } catch (err) {
    setToolStatus(`Command failed: ${err.message}`);
  } finally {
    if (btn) btn.disabled = false;
  }
}

function initToolDrawer() {
  const toggle = $("#tool-drawer-toggle");
  const drawer = $("#tool-drawer");
  if (!toggle || !drawer) return;

  toggle.addEventListener("click", () => {
    const open = !drawer.classList.contains("open");
    setToolDrawerOpen(open);
    if (open) loadSetupStatus();
  });

  $("#setup-status-refresh")?.addEventListener("click", () => loadSetupStatus());

  drawer.querySelectorAll("[data-tool-command]").forEach((btn) => {
    btn.addEventListener("click", () => runToolCommand(btn.dataset.toolCommand));
  });

  drawer.querySelectorAll("[data-tool-prompt]").forEach((btn) => {
    btn.addEventListener("click", () => copyToolPrompt(btn.dataset.toolPrompt, btn));
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && drawer.classList.contains("open")) {
      setToolDrawerOpen(false);
    }
  });
}

function detectProjectFromQuery(q) {
  const lower = q.toLowerCase();
  for (const p of state.allProjects) {
    const slug = p.project.toLowerCase();
    if (lower.includes(slug)) return p.project;
    const short = slug.split(".").pop();
    if (short.length > 3 && lower.includes(short)) return p.project;
  }
  return null;
}

function projectRowHtml(p, { showLast = false } = {}) {
  const count = p.total ?? 0;
  const sub = showLast && p.last_at ? fmtDate(p.last_at) : null;
  return `
    <li>
      <button type="button" class="project-row" data-project="${esc(p.project)}">
        <span class="project-name">${esc(p.project)}</span>
        <span class="project-meta">
          ${sub ? `<span class="project-sub">${esc(sub)}</span>` : ""}
          <span class="project-count">${count}</span>
        </span>
      </button>
    </li>`;
}

function renderProjectPanels(summary) {
  state.latestProjects = summary.latest || [];
  $("#latest-projects").innerHTML = state.latestProjects
    .map((p) => projectRowHtml(p, { showLast: true }))
    .join("");

  const frequent = summary.frequent || [];
  $("#frequent-projects").innerHTML = frequent
    .map((p) => projectRowHtml(p))
    .join("");

  document.querySelectorAll("#latest-projects button, #frequent-projects button").forEach((btn) => {
    btn.addEventListener("click", () => enterProject(btn.dataset.project, { browse: true }));
  });
}

function renderSidebar() {
  const list = $("#project-list");
  list.innerHTML = state.allProjects
    .slice(0, 60)
    .map((p) => projectRowHtml(p))
    .join("");

  list.querySelectorAll("button").forEach((btn) => {
    btn.addEventListener("click", () => selectProject(btn.dataset.project));
  });

  highlightActiveProject();
}

function highlightActiveProject() {
  document.querySelectorAll(".project-row").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.project === state.activeProject);
  });
}

function enterProject(project, initialQueryOrOptions = "") {
  const options =
    typeof initialQueryOrOptions === "object" && initialQueryOrOptions !== null
      ? initialQueryOrOptions
      : { initialQuery: initialQueryOrOptions };
  state.activeProject = project;
  $("#active-project").textContent = project;
  showView("app");
  renderSidebar();
  highlightActiveProject();
  setAppSidebarVisible(true);

  const q = (options.initialQuery || "").trim();
  $("#scoped-q").value = q;
  $("#scoped-q").placeholder = `Search within ${project}…`;

  if (q) {
    runScopedSearch(q);
  } else if (options.browse) {
    browseProject(project);
  } else {
    setAppResultsVisible(false);
  }
  $("#scoped-q").focus();
}

function selectProject(project) {
  state.activeProject = project;
  $("#active-project").textContent = project;
  highlightActiveProject();
  $("#scoped-q").placeholder = `Search within ${project}…`;
  const q = $("#scoped-q").value.trim();
  if (q) {
    runScopedSearch(q);
  } else {
    browseProject(project);
  }
}

function goHome() {
  state.activeProject = null;
  state.hasSearched = false;
  setAppResultsVisible(false);
  setAppSidebarVisible(false);
  $("#output").innerHTML = "";
  $("#meta").innerHTML = "";
  showView("home");
  $("#home-q").focus();
}

function renderMeta(data) {
  const el = $("#meta");
  const parts = [
    data.last_time ? "Most recent matches" : null,
    data.intent ? `<strong>${esc(data.intent)}</strong>` : null,
    data.fts_query && data.fts_query !== data.query
      ? `Searching: ${esc(data.fts_query)}`
      : null,
    data.all_time
      ? `All time${data.total_in_index != null ? ` · ${data.total_in_index} indexed` : ""}${data.truncated ? " · showing newest subset" : ""}`
      : data.hours
        ? `${data.hours}h window`
        : null,
  ].filter(Boolean);
  el.innerHTML = parts.join(" · ");
  el.classList.toggle("hidden", !parts.length);
}

function isLocalItem(item) {
  return (item.source || item.origin || "local") === "local";
}

function isActionableLocalDoc(item) {
  if (!item?.path) return false;
  const storage = item.storage || "file";
  return storage !== "db_only";
}

function canShareItem(item) {
  return (
    isActionableLocalDoc(item) &&
    (item.syncable === true ||
      item.sync_status === "not_shared" ||
      item.sync_status === "changed")
  );
}

function canShowLockItem(item) {
  return canShareItem(item);
}

function isDocumentAuthor(item) {
  const author = (item?.author_name || "").trim();
  if (!author) return false;
  const actor = (state.localActorName || "").trim();
  if (actor) return author.toLowerCase() === actor.toLowerCase();
  if (state.authors.length === 1) {
    return state.authors[0].trim().toLowerCase() === author.toLowerCase();
  }
  return false;
}

function canDeleteFromStrata(item) {
  return (
    isActionableLocalDoc(item) &&
    !canShareItem(item) &&
    isDocumentAuthor(item) &&
    Boolean(item.remote_id)
  );
}

function isSyncLocked(item) {
  return Boolean(item?.sync_locked);
}

function renderLockButtonState(btn, locked) {
  if (!btn) return;
  btn.dataset.locked = locked ? "1" : "0";
  btn.classList.toggle("lock-btn-locked", locked);
  btn.classList.toggle("lock-btn-unlocked", !locked);
  btn.title = locked ? ACTION.lockLockedTooltip : ACTION.lockUnlockedTooltip;
  btn.setAttribute(
    "aria-label",
    locked ? "Locked — excluded from batch sync" : "Unlocked — included in batch sync"
  );
  const icon = btn.querySelector("i");
  if (icon) {
    icon.className = locked ? "fa-solid fa-lock" : "fa-solid fa-lock-open";
  }
}

function lockButtonHtml(path, locked, className = "result-lock-btn") {
  const stateClass = locked ? "lock-btn-locked" : "lock-btn-unlocked";
  const icon = locked ? "fa-lock" : "fa-lock-open";
  const title = locked ? ACTION.lockLockedTooltip : ACTION.lockUnlockedTooltip;
  const label = locked ? "Locked — excluded from batch sync" : "Unlocked — included in batch sync";
  return `<button type="button" class="icon-btn lock-btn ${stateClass} ${className}" data-path="${esc(path)}" data-locked="${locked ? "1" : "0"}" aria-label="${esc(label)}" title="${esc(title)}"><i class="fa-solid ${icon}" aria-hidden="true"></i></button>`;
}

function deleteStrataButtonHtml(path, className = "result-delete-strata-btn") {
  return `<button type="button" class="icon-btn delete-strata-btn ${className}" data-path="${esc(path)}" aria-label="Delete from STRATA" title="${esc(ACTION.deleteStrataTooltip)}"><i class="fa-solid fa-trash" aria-hidden="true"></i></button>`;
}

function shareButtonHtml(path, className = "result-share-btn") {
  return `<button type="button" class="cta-btn cta-share ${className}" data-path="${esc(path)}" title="${esc(ACTION.shareTooltip)}">${ACTION.shareLabel}</button>`;
}

function indexButtonHtml(path, className = "result-index-btn") {
  return `<button type="button" class="cta-btn cta-index ${className}" data-path="${esc(path)}" title="${esc(ACTION.indexTooltip)}">${ACTION.indexLabel}</button>`;
}

function localActionButtonsHtml(item, { shareClass = "result-share-btn", indexClass = "result-index-btn" } = {}) {
  const path = item.path;
  if (!isActionableLocalDoc(item)) return "";

  const share = canShareItem(item) ? shareButtonHtml(path, shareClass) : "";
  const lock = canShowLockItem(item) ? lockButtonHtml(path, isSyncLocked(item)) : "";
  const deleteStrata = canDeleteFromStrata(item) ? deleteStrataButtonHtml(path) : "";
  const index = indexButtonHtml(path, indexClass);
  const actions = [share, lock, deleteStrata, index].filter(Boolean);
  return `<div class="card-actions">${actions.join('<span class="action-sep" aria-hidden="true">|</span>')}</div>`;
}

function setActionBusy(btn, busyLabel) {
  if (!btn) return;
  btn.disabled = true;
  btn.dataset.idleLabel = btn.textContent;
  btn.textContent = busyLabel;
}

function setActionIdle(btn, idleLabel) {
  if (!btn) return;
  btn.disabled = false;
  btn.textContent = idleLabel || btn.dataset.idleLabel || btn.textContent;
}

function updateDocModalActions(doc, path) {
  const actions = $("#doc-actions");
  const shareBtn = $("#doc-share-btn");
  const indexBtn = $("#doc-index-btn");
  const lockBtn = $("#doc-lock-btn");
  const deleteBtn = $("#doc-delete-strata-btn");
  const sep = actions?.querySelector(".action-sep");
  if (!actions || !shareBtn || !indexBtn || !lockBtn || !deleteBtn) return;

  state.activeDocPath = path;
  const actionable = isActionableLocalDoc(doc);
  const showShare = actionable && canShareItem(doc);
  const showLock = showShare;
  const showDelete = actionable && canDeleteFromStrata(doc);

  actions.classList.toggle("hidden", !actionable);
  shareBtn.classList.toggle("hidden", !showShare);
  sep?.classList.toggle("hidden", !showShare);
  indexBtn.classList.toggle("hidden", !actionable);
  lockBtn.classList.toggle("hidden", !showLock);
  deleteBtn.classList.toggle("hidden", !showDelete);

  shareBtn.title = ACTION.shareTooltip;
  indexBtn.title = ACTION.indexTooltip;
  setActionIdle(shareBtn, ACTION.shareLabel);
  setActionIdle(indexBtn, ACTION.indexLabel);
  lockBtn.dataset.path = path;
  deleteBtn.dataset.path = path;
  if (showLock) renderLockButtonState(lockBtn, isSyncLocked(doc));
}

function patchItemLockState(path, locked) {
  for (const items of [state.recentItems, state.syncItems, state.secretItems]) {
    const item = items.find((row) => row.path === path);
    if (item) item.sync_locked = locked;
  }
}

function syncLockButtonsForPath(path, locked, sourceBtn) {
  renderLockButtonState(sourceBtn, locked);
  document.querySelectorAll(`.result-lock-btn[data-path="${cssEscape(path)}"]`).forEach((el) => {
    if (el !== sourceBtn) renderLockButtonState(el, locked);
  });
  if (state.activeDocPath === path) {
    renderLockButtonState($("#doc-lock-btn"), locked);
  }
}

function cardHtml(item) {
  const type = item.type || item.kind || "search";
  const path = item.path || "";
  const title = friendlyCardTitle(item);
  const at = normalizeEventAt(item.at || item.updated_at || item.created_at, path);
  const project = item.project || item.project_slug || "";
  const excerpt = stripMarkdown(item.excerpt || item.snippet || item.overview || item.body || "");
  const source = item.source || item.origin || "local";
  const author = item.author_name || "";
  const actionButtons = localActionButtonsHtml(item);

  return `
    <article class="card" data-path="${esc(path)}">
      <div class="card-head">
        <span class="badge badge-${esc(type)}">${esc(type)}</span>
        <span class="badge badge-source">${esc(source)}</span>
        <span class="card-title">${esc(title)}</span>
      </div>
      <div class="card-meta">${esc(project)} · ${esc(fmtDate(at))}${author ? ` · ${esc(author)}` : ""}</div>
      ${excerpt ? `<p class="card-excerpt">${esc(excerpt)}</p>` : ""}
      ${actionButtons}
    </article>`;
}

function canSyncResult(item) {
  return canShareItem(item);
}

function renderTimeline(events, { emptyMessage } = {}) {
  if (!events?.length) {
    return `<p class="empty">${esc(emptyMessage || "No documents found. Try a search or run strata index.")}</p>`;
  }
  const sorted = sortEventsNewestFirst(events);
  const byDay = new Map();
  for (const ev of sorted) {
    const k = dayKey(ev.at || ev.updated_at || ev.created_at, ev.path || "");
    if (!byDay.has(k)) byDay.set(k, []);
    byDay.get(k).push(ev);
  }
  const days = [...byDay.entries()].sort((a, b) => {
    if (a[0] === "Unknown") return 1;
    if (b[0] === "Unknown") return -1;
    return b[0].localeCompare(a[0]);
  });
  let html = "";
  for (const [day, items] of days) {
    html += `<div class="timeline-day"><h3>${esc(day)}</h3>`;
    html += sortEventsNewestFirst(items).map(cardHtml).join("");
    html += "</div>";
  }
  return html;
}

function renderResults(data) {
  const out = $("#output");
  renderMeta(data);

  if ((data.intent === "timeline" || data.intent === "library") && data.events) {
    out.innerHTML = renderTimeline(data.events, {
      emptyMessage: data.intent === "library"
        ? "No indexed documents for this project. Run strata index --full."
        : undefined,
    });
  } else if (data.intent === "recent" && data.handoffs) {
    out.innerHTML = renderTimeline(
      data.handoffs.map((h) => ({ ...h, type: "handoff", at: h.updated_at }))
    );
  } else if (data.intent === "plans" && data.plans) {
    const plans = sortEventsNewestFirst(
      data.plans.map((p) => ({ ...p, at: p.updated_at }))
    );
    out.innerHTML = plans.length
      ? plans.map((p) => cardHtml({ ...p, type: "plan", at: p.updated_at })).join("")
      : '<p class="empty">No plans matched.</p>';
  } else if (data.results) {
    const results = sortEventsNewestFirst(data.results);
    out.innerHTML = results.length
      ? results.map((r) => cardHtml({ ...r, type: r.kind || "search" })).join("")
      : '<p class="empty">No matches in this project. Try different keywords.</p>';
  } else {
    out.innerHTML = '<p class="empty">No results.</p>';
  }

  out.querySelectorAll(".card[data-path]").forEach((el) => {
    el.addEventListener("click", (event) => {
      if (event.target.closest(".result-share-btn, .result-index-btn, .result-sync-btn, .result-lock-btn, .result-delete-strata-btn")) return;
      openDoc(el.dataset.path);
    });
  });
  out.querySelectorAll(".result-share-btn, .result-sync-btn").forEach((el) => {
    el.addEventListener("click", (event) => {
      event.stopPropagation();
      shareSearchResult(el.dataset.path);
    });
  });
  out.querySelectorAll(".result-index-btn").forEach((el) => {
    el.addEventListener("click", (event) => {
      event.stopPropagation();
      indexSearchResult(el.dataset.path);
    });
  });
  out.querySelectorAll(".result-lock-btn").forEach((el) => {
    el.addEventListener("click", (event) => {
      event.stopPropagation();
      toggleSyncLock(el.dataset.path, el);
    });
  });
  bindDeleteStrataButtons(out);
}

async function openDoc(path) {
  if (!path) return;
  const doc = await api(`/api/doc?path=${encodeURIComponent(path)}`);
  $("#doc-title").textContent = displayDocTitle(doc, path);
  $("#doc-subtitle").textContent = path.replace(/^\.md\//, "");
  $("#doc-body").innerHTML = renderMarkdown(prepareBodyForDisplay(doc.body));
  updateDocModalActions(doc, path);
  $("#doc-modal").showModal();
}

function cssEscape(value) {
  if (window.CSS?.escape) return window.CSS.escape(value);
  return String(value).replace(/["\\]/g, "\\$&");
}

async function refreshActiveProjectResults() {
  const q = $("#scoped-q").value.trim();
  if (q) {
    await runScopedSearch(q);
  } else if (state.activeProject) {
    await browseProject(state.activeProject);
  }
}

async function shareSearchResult(path) {
  if (!path) return;
  const btn = document.querySelector(
    `.result-share-btn[data-path="${cssEscape(path)}"], .result-sync-btn[data-path="${cssEscape(path)}"]`
  );
  if (btn) setActionBusy(btn, ACTION.shareBusy);

  showToast("redacting secrets from sync...", { timeout: 1800 });
  setToolStatus("redacting secrets from sync...");
  let result;
  try {
    result = await api("/api/sync/upload", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paths: [path], allow_locked: true }),
    });
  } catch (err) {
    showToast(`Sync failed: ${err.message}`);
    setToolStatus(`Sync failed: ${err.message}`);
    if (btn) setActionIdle(btn, ACTION.shareLabel);
    return;
  }
  if (result.failed?.length) {
    showToast("Some files could not be shared. Check sync details.");
    setToolStatus("Some files could not be shared. Check sync details.");
    if (btn) setActionIdle(btn, ACTION.shareLabel);
    return;
  }

  await refreshActiveProjectResults();
  await loadSyncLocal();
  await loadRecentLocal({ resetPage: false });
  await loadPotentialSecrets({ resetPage: false });
  await refreshRemotePending();

  if (state.activeDocPath === path && $("#doc-modal")?.open) {
    const doc = await api(`/api/doc?path=${encodeURIComponent(path)}`);
    updateDocModalActions(doc, path);
  }
  showToast("Sync complete.");
  setToolStatus("Sync complete.");
}

async function syncSearchResult(path) {
  return shareSearchResult(path);
}

async function indexSearchResult(path) {
  if (!path) return;
  const btn = document.querySelector(`.result-index-btn[data-path="${cssEscape(path)}"]`);
  if (btn) setActionBusy(btn, ACTION.indexBusy);
  await indexPaths([path]);
  if (btn) setActionIdle(btn, ACTION.indexLabel);
  await refreshActiveProjectResults();
  await loadRecentLocal({ resetPage: false });
  await loadPotentialSecrets({ resetPage: false });
}

async function shareDocFromModal() {
  const path = state.activeDocPath;
  if (!path) return;
  const btn = $("#doc-share-btn");
  setActionBusy(btn, ACTION.shareBusy);
  try {
    await shareSearchResult(path);
  } finally {
    setActionIdle(btn, ACTION.shareLabel);
  }
}

async function toggleSyncLock(path, btn) {
  if (!path || !btn || btn.disabled) return;
  const locked = btn.dataset.locked === "1";
  const nextLocked = !locked;
  btn.disabled = true;
  try {
    const result = await api("/api/sync/lock", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path, locked: nextLocked }),
    });
    const syncLocked = Boolean(result.sync_locked);
    patchItemLockState(path, syncLocked);
    syncLockButtonsForPath(path, syncLocked, btn);
    showToast(syncLocked ? "Locked — excluded from batch sync." : "Unlocked — included in batch sync.");
    if (state.homeTab === "recent") renderRecentPage();
    else if (state.homeTab === "share") renderSyncPage();
    else if (state.homeTab === "secrets") renderPotentialSecretsPage();
    if (state.view === "app" && state.activeProject) {
      await refreshActiveProjectResults();
    }
  } catch (err) {
    showToast(`Lock update failed: ${err.message}`);
  } finally {
    btn.disabled = false;
  }
}

async function toggleDocLockFromModal() {
  const path = state.activeDocPath;
  const btn = $("#doc-lock-btn");
  if (!path || !btn) return;
  await toggleSyncLock(path, btn);
}

async function indexDocFromModal() {
  const path = state.activeDocPath;
  if (!path) return;
  const btn = $("#doc-index-btn");
  setActionBusy(btn, ACTION.indexBusy);
  try {
    await indexPaths([path]);
    await loadRecentLocal({ resetPage: false });
    await loadPotentialSecrets({ resetPage: false });
  } finally {
    setActionIdle(btn, ACTION.indexLabel);
  }
}

function deleteRemotePath(path) {
  openDeleteStrataConfirm(path);
}

function openDeleteStrataConfirm(path) {
  if (!path) return;
  state.pendingDeletePath = path;
  const modal = $("#delete-strata-modal");
  const input = $("#delete-strata-confirm-input");
  const confirmBtn = $("#delete-strata-confirm");
  if (!modal || !input || !confirmBtn) return;
  $("#delete-strata-path").textContent = path;
  input.value = "";
  confirmBtn.disabled = true;
  modal.showModal();
  input.focus();
}

function closeDeleteStrataConfirm() {
  state.pendingDeletePath = null;
  $("#delete-strata-modal")?.close();
}

async function confirmDeleteFromStrata() {
  const path = state.pendingDeletePath;
  const input = $("#delete-strata-confirm-input");
  if (!path || !input || input.value.trim() !== "DELETE") return;
  closeDeleteStrataConfirm();
  await executeDeleteFromStrata(path);
}

async function executeDeleteFromStrata(path) {
  if (!path) return;
  const btn = document.querySelector(
    `.result-delete-strata-btn[data-path="${cssEscape(path)}"], .delete-strata-one[data-path="${cssEscape(path)}"], #doc-delete-strata-btn`
  );
  if (btn) btn.disabled = true;
  try {
    const result = await api("/api/sync/delete-remote", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path, actor_name: state.localActorName || undefined }),
    });
    if (!result.deleted) {
      showToast(result.error ? `Delete failed: ${result.error}` : "Delete failed.");
      return;
    }
    showToast("Removed from STRATA. Local file kept.");
    setToolStatus("Removed from STRATA. Local file kept.");
    if (state.activeDocPath === path) {
      $("#doc-modal")?.close();
    }
    if (state.homeTab === "recent") await loadRecentLocal({ resetPage: false });
    else if (state.homeTab === "share") await loadSyncLocal({ resetPage: false });
    if (state.view === "app" && state.activeProject) {
      await refreshActiveProjectResults();
    }
  } catch (err) {
    showToast(`Delete failed: ${err.message}`);
  } finally {
    if (btn) btn.disabled = false;
  }
}

function bindDeleteStrataButtons(container) {
  container.querySelectorAll(".result-delete-strata-btn, .delete-strata-one").forEach((btn) => {
    btn.addEventListener("click", (event) => {
      event.stopPropagation();
      openDeleteStrataConfirm(btn.dataset.path);
    });
  });
}

function initDeleteStrataModal() {
  const modal = $("#delete-strata-modal");
  const input = $("#delete-strata-confirm-input");
  const confirmBtn = $("#delete-strata-confirm");
  if (!modal || !input || !confirmBtn) return;

  input.addEventListener("input", () => {
    confirmBtn.disabled = input.value.trim() !== "DELETE";
  });
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !confirmBtn.disabled) {
      event.preventDefault();
      confirmDeleteFromStrata();
    }
  });
  $("#delete-strata-cancel")?.addEventListener("click", closeDeleteStrataConfirm);
  confirmBtn.addEventListener("click", () => confirmDeleteFromStrata());
  modal.addEventListener("click", (event) => {
    if (event.target === modal) closeDeleteStrataConfirm();
  });
}

function syncHomeAuthorToScoped() {
  const homeAuthor = ($("#files-filter-author") || {}).value || "";
  const scoped = $("#scoped-filter-author");
  if (scoped && homeAuthor && state.authors.includes(homeAuthor)) {
    scoped.value = homeAuthor;
  }
}

async function loadAuthors() {
  const data = await api("/api/authors").catch(() => ({ authors: [], local_actor: "" }));
  state.authors = data.authors || [];
  if (data.local_actor) state.localActorName = String(data.local_actor).trim();
  else if (!state.localActorName && state.authors.length === 1) {
    state.localActorName = state.authors[0].trim();
  }
  const options =
    '<option value="">All Authors</option>' +
    state.authors.map((name) => `<option value="${esc(name)}">${esc(name)}</option>`).join("");
  for (const id of ["files-filter-author", "scoped-filter-author"]) {
    const el = $(id);
    if (!el) continue;
    const prev = el.value;
    el.innerHTML = options;
    if (prev && state.authors.includes(prev)) el.value = prev;
  }
}

function filesFilterParams() {
  const params = new URLSearchParams({ hours: "168", limit: "500" });
  const kind = ($("#files-filter-kind") || {}).value || "";
  const author = ($("#files-filter-author") || {}).value || "";
  if (kind) params.set("kind", kind);
  if (author) params.set("author", author);
  return params;
}

function scopedAuthorFilter() {
  return ($("#scoped-filter-author") || {}).value || "";
}

function reloadHomeFileTabs() {
  return Promise.all([
    loadRecentLocal({ resetPage: true }),
    loadSyncLocal({ resetPage: true }),
    loadSharedFromTeam({ resetPage: true }),
    loadPotentialSecrets({ resetPage: true }),
  ]);
}

async function runScopedSearch(q) {
  const trimmed = (q || "").trim();
  if (!trimmed) return;

  state.hasSearched = true;
  setAppSidebarVisible(true);
  setAppResultsVisible(true);
  $("#output").innerHTML = '<p class="empty loading">Searching…</p>';
  const source = ($("#scoped-source") || {}).value || "local";
  const author = scopedAuthorFilter();
  const data = await api("/api/query", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      q: trimmed,
      limit: 80,
      project: state.activeProject,
      source,
      author: author || undefined,
    }),
  });
  renderResults(data);
}

async function browseProject(project) {
  state.activeProject = project;
  state.hasSearched = true;
  setAppSidebarVisible(true);
  setAppResultsVisible(true);
  $("#output").innerHTML = '<p class="empty loading">Loading project…</p>';
  const source = ($("#scoped-source") || {}).value || "local";
  const author = scopedAuthorFilter();
  const data = await api("/api/query", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      q: "",
      limit: 500,
      project,
      all_time: true,
      source,
      author: author || undefined,
    }),
  });
  renderResults(data);
}

function syncRowHtml(item) {
  const actions = [
    canShareItem(item) ? shareButtonHtml(item.path, "sync-one") : "",
    canShowLockItem(item) ? lockButtonHtml(item.path, isSyncLocked(item)) : "",
    canDeleteFromStrata(item) ? deleteStrataButtonHtml(item.path, "delete-strata-one") : "",
    indexButtonHtml(item.path, "index-one"),
  ].filter(Boolean);
  return `
    <article class="sync-row" data-path="${esc(item.path)}">
      <div class="sync-row-head">
        <span class="badge badge-${esc(item.kind)}">${esc(item.kind)}</span>
        <span class="sync-path">${esc(item.path)}</span>
      </div>
      <div class="sync-meta">
        ${esc(item.local_status)} · ${esc(item.share_status)}
        ${item.author_name ? ` · ${esc(item.author_name)}` : ""}
        · ${esc(fmtDate(item.updated_at))}
      </div>
      ${item.excerpt ? `<p class="card-excerpt">${esc(item.excerpt)}</p>` : ""}
      <div class="sync-actions">
        ${actions.join('<span class="action-sep" aria-hidden="true">|</span>')}
      </div>
    </article>`;
}

function recentRowHtml(item) {
  const title = item.title || titleFromPath(item.path);
  const localStatus = item.local_status || "indexed";
  const shareStatus = item.share_status || (item.sync_status === "shared" ? "shared" : "not shared");
  const actionButtons = localActionButtonsHtml(item, {
    shareClass: "sync-one",
    indexClass: "index-one",
  });
  return `
    <article class="sync-row recent-row" data-path="${esc(item.path)}" data-project="${esc(item.project || "")}" role="button" tabindex="0">
      <div class="sync-row-head">
        <span class="badge badge-${esc(item.kind)}">${esc(item.kind)}</span>
        <span class="recent-title">${esc(title)}</span>
      </div>
      <div class="sync-meta">
        ${item.project ? `${esc(item.project)} · ` : ""}${esc(localStatus)} · ${esc(shareStatus)}${item.author_name ? ` · ${esc(item.author_name)}` : ""} · ${esc(fmtDate(item.updated_at || item.created_at))}
      </div>
      <div class="sync-path">${esc(item.path)}</div>
      ${item.excerpt ? `<p class="card-excerpt">${esc(item.excerpt)}</p>` : ""}
      ${actionButtons}
    </article>`;
}

function sharedFromRowHtml(item) {
  const title = item.title || titleFromPath(item.path);
  const author = item.author_name || "";
  return `
    <article class="sync-row recent-row" data-path="${esc(item.path)}" data-project="${esc(item.project || "")}" role="button" tabindex="0">
      <div class="sync-row-head">
        <span class="badge badge-${esc(item.kind)}">${esc(item.kind)}</span>
        <span class="recent-title">${esc(title)}</span>
      </div>
      <div class="sync-meta">
        ${item.project ? `${esc(item.project)} · ` : ""}${author ? `${esc(author)} · ` : ""}received · ${esc(fmtDate(item.updated_at || item.synced_at || item.created_at))}
      </div>
      <div class="sync-path">${esc(item.path)}</div>
      ${item.excerpt ? `<p class="card-excerpt">${esc(item.excerpt)}</p>` : ""}
    </article>`;
}

function secretRowHtml(item) {
  const title = item.title || titleFromPath(item.path) || item.path.split("/").pop();
  return `
    <article class="sync-row" data-path="${esc(item.path)}">
      <div class="sync-row-head">
        <span class="badge badge-${esc(item.kind)}">${esc(item.kind)}</span>
        <span class="recent-title">${esc(title)}</span>
      </div>
      <div class="sync-meta">
        ${item.project ? `${esc(item.project)} · ` : ""}redacted before sync · ${esc(fmtDate(item.updated_at || item.created_at))}
      </div>
      <div class="sync-path">${esc(item.path)}</div>
      ${item.excerpt ? `<p class="card-excerpt">${esc(item.excerpt)}</p>` : ""}
      <div class="sync-actions">
        ${indexButtonHtml(item.path, "index-one")}
        ${canShowLockItem(item) ? lockButtonHtml(item.path, isSyncLocked(item)) : ""}
        ${canDeleteFromStrata(item) ? deleteStrataButtonHtml(item.path, "delete-strata-one") : ""}
      </div>
    </article>`;
}

function bindRecentRowActions(container) {
  container.querySelectorAll(".sync-one, .result-share-btn").forEach((btn) => {
    btn.addEventListener("click", (event) => {
      event.stopPropagation();
      shareSearchResult(btn.dataset.path);
    });
  });
  container.querySelectorAll(".index-one, .result-index-btn").forEach((btn) => {
    btn.addEventListener("click", (event) => {
      event.stopPropagation();
      indexSearchResult(btn.dataset.path);
    });
  });
  bindLockButtons(container);
  bindDeleteStrataButtons(container);
}

function bindLockButtons(container) {
  container.querySelectorAll(".result-lock-btn, .lock-one").forEach((btn) => {
    btn.addEventListener("click", (event) => {
      event.stopPropagation();
      toggleSyncLock(btn.dataset.path, btn);
    });
  });
}

function renderPagedList({
  items,
  page,
  pageSize,
  tableId,
  pagerId,
  pageInfoId,
  prevId,
  nextId,
  rowHtml,
  emptyMessage,
  onPageChange,
  onRowActivate,
}) {
  const el = $(tableId);
  const pager = $(pagerId);

  if (!items.length) {
    el.innerHTML = `<p class="empty">${emptyMessage}</p>`;
    pager?.classList.add("hidden");
    return;
  }

  const totalPages = Math.max(1, Math.ceil(items.length / pageSize));
  let currentPage = page;
  if (currentPage >= totalPages) currentPage = totalPages - 1;
  if (currentPage < 0) currentPage = 0;
  if (currentPage !== page) onPageChange(currentPage);

  const start = currentPage * pageSize;
  const pageItems = items.slice(start, start + pageSize);

  el.innerHTML = pageItems.map(rowHtml).join("");

  if (onRowActivate) {
    el.querySelectorAll(".recent-row").forEach((row) => {
      const activate = () => onRowActivate(row.dataset);
      row.addEventListener("click", (event) => {
        if (event.target.closest(".result-share-btn, .result-index-btn, .result-sync-btn, .result-lock-btn, .result-delete-strata-btn, .sync-one, .index-one, .delete-strata-one")) {
          return;
        }
        activate();
      });
      row.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          activate();
        }
      });
    });
  }

  if (pager) {
    const showPager = items.length > pageSize;
    pager.classList.toggle("hidden", !showPager);
    $(pageInfoId).textContent = `${currentPage + 1} / ${totalPages}`;
    $(prevId).disabled = currentPage <= 0;
    $(nextId).disabled = currentPage >= totalPages - 1;
  }
}

function renderRecentPage() {
  const el = $("#recent-local-table");
  renderPagedList({
    items: state.recentItems,
    page: state.recentPage,
    pageSize: RECENT_PAGE_SIZE,
    tableId: "#recent-local-table",
    pagerId: "#recent-pagination",
    pageInfoId: "#recent-page-info",
    prevId: "#recent-prev",
    nextId: "#recent-next",
    rowHtml: recentRowHtml,
    emptyMessage: "No local documents in the last 7 days.",
    onPageChange: (page) => {
      state.recentPage = page;
    },
    onRowActivate: (dataset) => openRecentFile(dataset.path, dataset.project),
  });
  bindRecentRowActions(el);
}

async function openRecentFile(path, project) {
  if (!path) return;
  if (project) {
    enterProject(project, { browse: true });
  }
  await openDoc(path);
}

function switchHomeTab(tab) {
  state.homeTab = tab;
  const isRecent = tab === "recent";
  const isShare = tab === "share";
  const isReceived = tab === "received";
  const isSecrets = tab === "secrets";
  $("#tab-recent")?.classList.toggle("active", isRecent);
  $("#tab-share")?.classList.toggle("active", isShare);
  $("#tab-received")?.classList.toggle("active", isReceived);
  $("#tab-secrets")?.classList.toggle("active", isSecrets);
  $("#tab-recent")?.setAttribute("aria-selected", isRecent ? "true" : "false");
  $("#tab-share")?.setAttribute("aria-selected", isShare ? "true" : "false");
  $("#tab-received")?.setAttribute("aria-selected", isReceived ? "true" : "false");
  $("#tab-secrets")?.setAttribute("aria-selected", isSecrets ? "true" : "false");
  $("#panel-recent")?.classList.toggle("hidden", !isRecent);
  $("#panel-share")?.classList.toggle("hidden", !isShare);
  $("#panel-received")?.classList.toggle("hidden", !isReceived);
  $("#panel-secrets")?.classList.toggle("hidden", !isSecrets);
  if (isRecent) loadRecentLocal({ resetPage: false });
  if (isShare) loadSyncLocal({ resetPage: false });
  if (isReceived) loadSharedFromTeam({ resetPage: false });
  if (isSecrets) loadPotentialSecrets({ resetPage: false });
}

async function loadRecentLocal({ resetPage = true } = {}) {
  const params = filesFilterParams();
  const data = await api(`/api/documents/recent-local?${params.toString()}`);
  state.recentItems = data.items || [];
  if (resetPage) state.recentPage = 0;
  renderRecentPage();
}

async function loadSharedFromTeam({ resetPage = true } = {}) {
  const params = filesFilterParams();
  params.delete("hours");
  const data = await api(`/api/documents/shared-from-team?${params.toString()}`).catch(() => ({
    items: [],
  }));
  state.receivedItems = data.items || [];
  if (resetPage) state.receivedPage = 0;
  renderReceivedPage();
}

function renderReceivedPage() {
  renderPagedList({
    items: state.receivedItems,
    page: state.receivedPage,
    pageSize: RECENT_PAGE_SIZE,
    tableId: "#received-from-team-table",
    pagerId: "#received-pagination",
    pageInfoId: "#received-page-info",
    prevId: "#received-prev",
    nextId: "#received-next",
    rowHtml: sharedFromRowHtml,
    emptyMessage: "No team documents pulled locally yet. Use Sync From Remote in the tool drawer or run strata pull.",
    onPageChange: (page) => {
      state.receivedPage = page;
    },
    onRowActivate: (dataset) => openRecentFile(dataset.path, dataset.project),
  });
}

function renderSyncPage() {
  const el = $("#sync-local-table");
  renderPagedList({
    items: state.syncItems,
    page: state.syncPage,
    pageSize: SYNC_PAGE_SIZE,
    tableId: "#sync-local-table",
    pagerId: "#sync-pagination",
    pageInfoId: "#sync-page-info",
    prevId: "#sync-prev",
    nextId: "#sync-next",
    rowHtml: syncRowHtml,
    emptyMessage: "All local artifacts are indexed and shared.",
    onPageChange: (page) => {
      state.syncPage = page;
    },
  });

  el.querySelectorAll(".sync-one, .result-share-btn").forEach((btn) => {
    btn.addEventListener("click", (event) => {
      event.stopPropagation();
      shareSearchResult(btn.dataset.path);
    });
  });
  el.querySelectorAll(".index-one, .result-index-btn").forEach((btn) => {
    btn.addEventListener("click", (event) => {
      event.stopPropagation();
      indexSearchResult(btn.dataset.path);
    });
  });
  bindLockButtons(el);
  bindDeleteStrataButtons(el);
}

function renderPotentialSecretsPage() {
  const el = $("#secrets-local-table");
  renderPagedList({
    items: state.secretItems,
    page: state.secretPage,
    pageSize: SYNC_PAGE_SIZE,
    tableId: "#secrets-local-table",
    pagerId: "#secrets-pagination",
    pageInfoId: "#secrets-page-info",
    prevId: "#secrets-prev",
    nextId: "#secrets-next",
    rowHtml: secretRowHtml,
    emptyMessage: "No local docs currently need redaction before sync.",
    onPageChange: (page) => {
      state.secretPage = page;
    },
  });

  el.querySelectorAll(".sync-one, .result-share-btn").forEach((btn) => {
    btn.addEventListener("click", (event) => {
      event.stopPropagation();
      shareSearchResult(btn.dataset.path);
    });
  });
  el.querySelectorAll(".index-one, .result-index-btn").forEach((btn) => {
    btn.addEventListener("click", (event) => {
      event.stopPropagation();
      indexSearchResult(btn.dataset.path);
    });
  });
  bindLockButtons(el);
  bindDeleteStrataButtons(el);
}

async function loadSyncLocal({ resetPage = true } = {}) {
  const params = filesFilterParams();
  const data = await api(`/api/sync/local?${params.toString()}`);
  state.syncItems = data.items || [];
  if (resetPage) state.syncPage = 0;
  renderSyncPage();
}

async function loadPotentialSecrets({ resetPage = true } = {}) {
  const params = filesFilterParams();
  const data = await api(`/api/sync/potential-secrets?${params.toString()}`);
  state.secretItems = data.items || [];
  if (resetPage) state.secretPage = 0;
  renderPotentialSecretsPage();
}

function batchSyncPaths(items) {
  return items.filter((item) => !isSyncLocked(item)).map((item) => item.path);
}

async function syncPaths(paths) {
  showToast("redacting secrets from sync...", { timeout: 1800 });
  setToolStatus("redacting secrets from sync...");
  const result = await api("/api/sync/upload", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ paths, allow_locked: false }),
  });
  if (result.skipped?.length) {
    const lockedCount = result.skipped.filter((row) => row.reason === "sync_locked").length;
    if (lockedCount) {
      showToast(`${lockedCount} locked file${lockedCount === 1 ? "" : "s"} skipped from batch sync.`);
    }
  }
  if (result.failed?.length) {
    showToast("Some files could not be shared. Check sync details.");
    setToolStatus("Some files could not be shared. Check sync details.");
  } else {
    showToast("Sync complete.");
    setToolStatus("Sync complete.");
  }
  await loadSyncLocal();
  await loadRecentLocal({ resetPage: false });
  await loadPotentialSecrets({ resetPage: false });
}

async function indexPaths(paths) {
  await api("/api/sync/index", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ paths }),
  });
  await loadSyncLocal();
  await loadRecentLocal({ resetPage: false });
  await loadPotentialSecrets({ resetPage: false });
}

function renderApiStatus(cfg) {
  const el = $("#api-status");
  if (!el) return;
  if (cfg.online) {
    el.textContent = `Online · ${cfg.actor || "authenticated"} @ ${cfg.organization || ""}`;
    el.classList.remove("hidden", "offline");
    state.apiOnline = true;
  } else {
    el.textContent = "Offline — searching local SQLite only";
    el.classList.remove("hidden");
    el.classList.add("offline");
    state.apiOnline = false;
  }
}

function renderStatsLine(stats, remotePending) {
  const el = $("#stats-line");
  if (!el) return;
  const kinds =
    stats.by_kind?.map((k) => `${kindLabel(k.kind, k.n)}: ${k.n}`).join(" · ") || "";
  let html = esc(kinds);
  const pending = remotePending?.pending ?? 0;
  if (state.apiOnline && remotePending?.online !== false && pending > 0) {
    html += ` · <button type="button" id="remote-sync-btn" class="stats-sync-btn">sync ${pending}</button>`;
  }
  el.innerHTML = html;
  $("#remote-sync-btn")?.addEventListener("click", pullRemote);
}

async function pullRemote() {
  const btn = $("#remote-sync-btn");
  if (!btn || btn.disabled) return;
  btn.disabled = true;
  btn.textContent = "syncing…";
  try {
    await api("/api/pull", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    await refreshDashboard();
  } catch (err) {
    alert(`Pull failed: ${err.message}`);
    btn.disabled = false;
    btn.textContent = `sync ${state.remotePending || ""}`.trim();
    await refreshRemotePending();
  }
}

async function refreshRemotePending() {
  if (!state.apiOnline) return;
  try {
    const remotePending = await api("/api/sync/remote-pending");
    state.remotePending = remotePending.pending || 0;
    const stats = await api("/api/stats");
    renderStatsLine(stats, remotePending);
  } catch (_) {
    /* keep current stats */
  }
}

async function refreshDashboard() {
  const [stats, summary, remotePending] = await Promise.all([
    api("/api/stats"),
    api("/api/projects/summary"),
    state.apiOnline
      ? api("/api/sync/remote-pending").catch(() => ({ online: false, pending: 0 }))
      : Promise.resolve({ online: false, pending: 0 }),
  ]);
  state.remotePending = remotePending.pending || 0;
  renderStatsLine(stats, remotePending);
  renderProjectPanels(summary);
  await loadAuthors();
  await Promise.allSettled([
    loadRecentLocal(),
    loadSyncLocal(),
    loadSharedFromTeam(),
    loadPotentialSecrets(),
  ]);
}

function handleHomeSearch(rawQ) {
  const q = rawQ.trim();
  if (!q) return;

  syncHomeAuthorToScoped();
  const source = ($("#home-source") || {}).value || "local";
  if (source !== "local" && q) {
    enterProject(state.latestProjects[0]?.project || state.allProjects[0]?.project || "—", q);
    return;
  }

  const detected = detectProjectFromQuery(q);
  if (detected) {
    const stripped = q.replace(new RegExp(detected, "i"), "").trim();
    enterProject(detected, stripped || q);
    return;
  }

  if (state.latestProjects.length) {
    enterProject(state.latestProjects[0].project, q);
    return;
  }

  if (state.allProjects.length) {
    enterProject(state.allProjects[0].project, q);
  }
}

function bindHomeTabControls() {
  if (bindHomeTabControls.bound) return;
  bindHomeTabControls.bound = true;

  $("#tab-recent")?.addEventListener("click", () => switchHomeTab("recent"));
  $("#tab-share")?.addEventListener("click", () => switchHomeTab("share"));
  $("#tab-received")?.addEventListener("click", () => switchHomeTab("received"));
  $("#tab-secrets")?.addEventListener("click", () => switchHomeTab("secrets"));

  $("#files-filter-kind")?.addEventListener("change", () => reloadHomeFileTabs());
  $("#files-filter-author")?.addEventListener("change", () => {
    syncHomeAuthorToScoped();
    reloadHomeFileTabs();
  });

  $("#sync-refresh-btn")?.addEventListener("click", () => loadSyncLocal({ resetPage: false }));
  $("#received-refresh-btn")?.addEventListener("click", () => loadSharedFromTeam({ resetPage: false }));
  $("#secrets-refresh-btn")?.addEventListener("click", () => loadPotentialSecrets({ resetPage: false }));
  $("#sync-all-btn")?.addEventListener("click", () => {
    syncPaths(batchSyncPaths(state.syncItems));
  });
  $("#sync-prev")?.addEventListener("click", () => {
    if (state.syncPage > 0) {
      state.syncPage -= 1;
      renderSyncPage();
    }
  });
  $("#sync-next")?.addEventListener("click", () => {
    const totalPages = Math.ceil(state.syncItems.length / SYNC_PAGE_SIZE);
    if (state.syncPage < totalPages - 1) {
      state.syncPage += 1;
      renderSyncPage();
    }
  });

  $("#recent-prev")?.addEventListener("click", () => {
    if (state.recentPage > 0) {
      state.recentPage -= 1;
      renderRecentPage();
    }
  });
  $("#recent-next")?.addEventListener("click", () => {
    const totalPages = Math.ceil(state.recentItems.length / RECENT_PAGE_SIZE);
    if (state.recentPage < totalPages - 1) {
      state.recentPage += 1;
      renderRecentPage();
    }
  });
  $("#received-prev")?.addEventListener("click", () => {
    if (state.receivedPage > 0) {
      state.receivedPage -= 1;
      renderReceivedPage();
    }
  });
  $("#received-next")?.addEventListener("click", () => {
    const totalPages = Math.ceil(state.receivedItems.length / RECENT_PAGE_SIZE);
    if (state.receivedPage < totalPages - 1) {
      state.receivedPage += 1;
      renderReceivedPage();
    }
  });
  $("#secrets-prev")?.addEventListener("click", () => {
    if (state.secretPage > 0) {
      state.secretPage -= 1;
      renderPotentialSecretsPage();
    }
  });
  $("#secrets-next")?.addEventListener("click", () => {
    const totalPages = Math.ceil(state.secretItems.length / SYNC_PAGE_SIZE);
    if (state.secretPage < totalPages - 1) {
      state.secretPage += 1;
      renderPotentialSecretsPage();
    }
  });
}
bindHomeTabControls.bound = false;

async function loadRemoteConfig(stats) {
  const cfg = await api("/api/config").catch(() => ({ online: false }));
  if (cfg.actor_name) state.localActorName = String(cfg.actor_name).trim();
  else if (cfg.actor) state.localActorName = String(cfg.actor).trim();
  else if (state.authors.length === 1) state.localActorName = state.authors[0].trim();
  renderApiStatus(cfg);
  if (!state.apiOnline) return;
  const remotePending = await api("/api/sync/remote-pending").catch(() => ({
    online: false,
    pending: 0,
  }));
  state.remotePending = remotePending.pending || 0;
  renderStatsLine(stats, remotePending);
}

async function init() {
  bindHomeTabControls();
  switchHomeTab("recent");

  const [stats, summary, projects] = await Promise.all([
    api("/api/stats"),
    api("/api/projects/summary"),
    api("/api/projects"),
  ]);

  state.allProjects = projects;
  state.remotePending = 0;
  renderStatsLine(stats, { online: false, pending: 0 });
  renderProjectPanels(summary);
  renderSidebar();
  await loadAuthors();
  await Promise.allSettled([
    loadRecentLocal(),
    loadSyncLocal(),
    loadSharedFromTeam(),
    loadPotentialSecrets(),
  ]);

  void loadRemoteConfig(stats);

  $("#scoped-filter-author")?.addEventListener("change", () => {
    if (state.view === "app" && state.activeProject) {
      const q = $("#scoped-q").value.trim();
      if (q) runScopedSearch(q);
      else browseProject(state.activeProject);
    }
  });

  const chips = $("#example-chips");
  chips.innerHTML = EXAMPLES.map(
    (ex) => `<button type="button" class="chip" data-q="${esc(ex)}">${esc(ex)}</button>`
  ).join("");
  chips.querySelectorAll(".chip").forEach((c) => {
    c.addEventListener("click", () => {
      if (state.view === "app" && state.activeProject) {
        $("#scoped-q").value = c.dataset.q;
        runScopedSearch(c.dataset.q);
      } else {
        $("#home-q").value = c.dataset.q;
        handleHomeSearch(c.dataset.q);
      }
    });
  });

  $("#home-search-form").addEventListener("submit", (e) => {
    e.preventDefault();
    handleHomeSearch($("#home-q").value);
  });

  $("#scoped-search-form").addEventListener("submit", (e) => {
    e.preventDefault();
    runScopedSearch($("#scoped-q").value.trim());
  });

  $("#home-btn").addEventListener("click", goHome);

  $("#doc-close").addEventListener("click", () => $("#doc-modal").close());
  $("#doc-share-btn")?.addEventListener("click", () => shareDocFromModal());
  $("#doc-index-btn")?.addEventListener("click", () => indexDocFromModal());
  $("#doc-lock-btn")?.addEventListener("click", () => toggleDocLockFromModal());
  $("#doc-delete-strata-btn")?.addEventListener("click", () => openDeleteStrataConfirm(state.activeDocPath));
  $("#doc-modal").addEventListener("click", (e) => {
    if (e.target === $("#doc-modal")) $("#doc-modal").close();
  });

  initToolDrawer();
  initDeleteStrataModal();
  showView("home");
}

init().catch((err) => {
  const el = $("#output") || $("#view-home");
  if (el) {
    el.innerHTML = `<p class="empty">Failed to load: ${esc(err.message)}</p>`;
  }
});
