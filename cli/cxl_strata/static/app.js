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

// "ignored" is a machine status (excluded from sync); show a friendlier label.
function statusLabel(value) {
  return value === "ignored" ? "local only" : value;
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
  archiveTooltip:
    "Archive for me — remove from my local STRATA and never re-pull. The team's remote copy is kept.",
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
  updateAvailable: false,
  localVersion: "",
  remoteVersion: "",
  accentTheme: "blue",
  graphProject: null,
  graphReturnView: "home",
};

const ACCENT_STORAGE_KEY = "strata:accent-theme";
const ACCENT_THEMES = [
  {
    id: "blue",
    label: "Blue",
    accent: "#6ea8fe",
    dim: "#3d5a8a",
    soft: "rgba(110, 168, 254, 0.18)",
    text: "#9ec5ff",
  },
  {
    id: "purple",
    label: "Purple",
    accent: "#a78bfa",
    dim: "#5b4a8a",
    soft: "rgba(167, 139, 250, 0.18)",
    text: "#c4b5fd",
  },
  {
    id: "red",
    label: "Red",
    accent: "#f87171",
    dim: "#8a3d3d",
    soft: "rgba(248, 113, 113, 0.18)",
    text: "#fca5a5",
  },
  {
    id: "green",
    label: "Green",
    accent: "#4ade80",
    dim: "#2f6b45",
    soft: "rgba(74, 222, 128, 0.18)",
    text: "#86efac",
  },
  {
    id: "orange",
    label: "Orange",
    accent: "#fb923c",
    dim: "#8a5530",
    soft: "rgba(251, 146, 60, 0.18)",
    text: "#fdba74",
  },
  {
    id: "gray",
    label: "Gray",
    accent: "#94a3b8",
    dim: "#4b5563",
    soft: "rgba(148, 163, 184, 0.18)",
    text: "#cbd5e1",
  },
];

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

function publishedAt(ev) {
  return ev.at || ev.published_at || ev.created_at || ev.updated_at;
}

function eventSortKey(ev) {
  const at = normalizeEventAt(publishedAt(ev), ev.path || "");
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
  $("#view-graph")?.classList.toggle("hidden", name !== "graph");
  $("#view-graph")?.classList.toggle("view-active", name === "graph");
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

function confirmLargeSync(count) {
  if (count <= 50) return true;
  return window.confirm(`Are you sure you want to sync ${count} files to Strata?`);
}

function setToolCount(id, value) {
  const el = $(id);
  if (!el) return;
  const n = Number(value);
  if (Number.isFinite(n) && n > 0) {
    el.textContent = `(${n})`;
    el.hidden = false;
  } else {
    el.textContent = "";
    el.hidden = true;
  }
}

function setToolActionDot(hasActions) {
  const dot = $("#tool-drawer-dot");
  if (!dot) return;
  dot.hidden = !hasActions;
}

async function refreshToolCounts() {
  let indexCount = 0;
  let syncCount = 0;
  let pullCount = 0;

  try {
    const indexPending = await api("/api/index/pending");
    indexCount = Number(indexPending.count) || 0;
  } catch (_) {
    indexCount = 0;
  }
  setToolCount("#count-index-pending", indexCount);

  try {
    await loadSyncLocal({ resetPage: false });
    syncCount = batchSyncPaths(state.syncItems).length;
  } catch (_) {
    syncCount = 0;
  }
  setToolCount("#count-sync-pending", syncCount);

  if (state.apiOnline) {
    try {
      const remotePending = await api("/api/sync/remote-pending");
      state.remotePending = remotePending.pending || 0;
    } catch (_) {
      /* keep current count */
    }
  }
  pullCount = state.apiOnline ? Number(state.remotePending) || 0 : 0;
  setToolCount("#count-pull-pending", pullCount);
  setToolActionDot(indexCount + syncCount + pullCount > 0);
}

async function runToolCommand(command) {
  const btn = document.querySelector(`[data-tool-command="${cssEscape(command)}"]`);
  if (btn?.disabled) return;
  if (btn) btn.disabled = true;
  setToolStatus("Running...");

  try {
    const scopedProject =
      state.view === "app" && state.activeProject ? state.activeProject : null;

    if (command === "sync-remote") {
      if (!state.apiOnline) {
        setToolStatus("Remote API is offline. Local search remains available.");
        return;
      }
      await api("/api/pull", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(scopedProject ? { project: scopedProject } : {}),
      });
      await refreshDashboard();
      if (scopedProject) await refreshActiveProjectResults();
      await refreshToolCounts();
      setToolStatus(
        scopedProject
          ? `Remote pull complete for ${scopedProject}.`
          : "Remote pull complete."
      );
      return;
    }

    if (command === "sync-local") {
      let items = state.syncItems;
      if (scopedProject) {
        const params = filesFilterParams();
        params.set("project", scopedProject);
        const data = await api(`/api/sync/local?${params.toString()}`);
        items = data.items || [];
      } else if (!items.length) {
        await loadSyncLocal({ resetPage: false });
        items = state.syncItems;
      }
      const paths = batchSyncPaths(items);
      if (!paths.length) {
        setToolStatus("All local artifacts are already shared or locked.");
        return;
      }
      if (!confirmLargeSync(paths.length)) {
        setToolStatus("Sync cancelled.");
        return;
      }
      await syncPaths(paths);
      await refreshRemotePending();
      await refreshToolCounts();
      setToolStatus(
        `Shared ${paths.length} local artifact${paths.length === 1 ? "" : "s"}${scopedProject ? ` from ${scopedProject}` : ""}.`
      );
      return;
    }

    if (command === "index-local") {
      const stats = await api("/api/index/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
      await Promise.all([
        loadRecentLocal({ resetPage: false }),
        loadPotentialSecrets({ resetPage: false }),
      ]);
      await refreshToolCounts();
      const indexed = stats.indexed ?? 0;
      setToolStatus(
        indexed
          ? `Added ${indexed} file${indexed === 1 ? "" : "s"} to Strata.`
          : "All workspace files are already in Strata."
      );
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
    if (open) {
      loadSetupStatus();
      refreshToolCounts();
    }
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
  const allRow = `
    <li>
      <button type="button" class="project-row project-row-all" data-project="">
        <span class="project-name"><i class="fa-solid fa-layer-group" aria-hidden="true"></i> All Projects</span>
      </button>
    </li>`;
  list.innerHTML =
    allRow +
    state.allProjects
      .slice(0, 60)
      .map((p) => projectRowHtml(p))
      .join("");

  list.querySelectorAll("button").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (btn.dataset.project) selectProject(btn.dataset.project);
      else selectAllProjects();
    });
  });

  highlightActiveProject();
}

function renderHomeSidebar() {
  const list = $("#home-project-list");
  if (!list) return;
  list.innerHTML = state.allProjects.map((p) => projectRowHtml(p)).join("");
  list.querySelectorAll("button").forEach((btn) => {
    btn.addEventListener("click", () => {
      setHomeSidebarOpen(false);
      enterProject(btn.dataset.project, { browse: true });
    });
  });
}

function setHomeSidebarOpen(open) {
  const sidebar = $("#home-sidebar");
  const backdrop = $("#home-sidebar-backdrop");
  const toggle = $("#home-menu-btn");
  if (!sidebar) return;
  sidebar.classList.toggle("open", open);
  sidebar.setAttribute("aria-hidden", String(!open));
  if (backdrop) backdrop.hidden = !open;
  toggle?.setAttribute("aria-expanded", String(open));
}

function highlightActiveProject() {
  document.querySelectorAll(".project-row").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.project === (state.activeProject ?? ""));
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

function enterAllProjects(initialQuery = "") {
  state.activeProject = null;
  $("#active-project").textContent = "All Projects";
  showView("app");
  renderSidebar();
  highlightActiveProject();
  setAppSidebarVisible(true);

  const q = (initialQuery || "").trim();
  $("#scoped-q").value = q;
  $("#scoped-q").placeholder = "Search across all projects…";

  if (q) {
    runScopedSearch(q);
  } else {
    setAppResultsVisible(false);
  }
  $("#scoped-q").focus();
}

function selectAllProjects() {
  state.activeProject = null;
  $("#active-project").textContent = "All Projects";
  highlightActiveProject();
  $("#scoped-q").placeholder = "Search across all projects…";
  const q = $("#scoped-q").value.trim();
  if (q) {
    runScopedSearch(q);
  } else {
    setAppResultsVisible(false);
    $("#output").innerHTML = "";
    $("#meta").innerHTML = "";
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

function isIndexedDoc(item) {
  return Boolean(item?.path);
}

function canReindexDoc(item) {
  if (!item?.path) return false;
  return (item.storage || "file") !== "db_only";
}

function canShareItem(item) {
  return (
    isIndexedDoc(item) &&
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
    isIndexedDoc(item) &&
    !canShareItem(item) &&
    isDocumentAuthor(item) &&
    Boolean(item.remote_id)
  );
}

function canArchiveItem(item) {
  return (
    isIndexedDoc(item) &&
    (item.origin === "shared" || Boolean(item.remote_id)) &&
    item.sync_status !== "ignored"
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

function archiveButtonHtml(path, className = "result-archive-btn") {
  return `<button type="button" class="icon-btn archive-btn ${className}" data-path="${esc(path)}" aria-label="Archive for me" title="${esc(ACTION.archiveTooltip)}"><i class="fa-solid fa-box-archive" aria-hidden="true"></i></button>`;
}

function shareButtonHtml(path, className = "result-share-btn") {
  return `<button type="button" class="cta-btn cta-share ${className}" data-path="${esc(path)}" title="${esc(ACTION.shareTooltip)}">${ACTION.shareLabel}</button>`;
}

function indexButtonHtml(path, className = "result-index-btn") {
  return `<button type="button" class="cta-btn cta-index ${className}" data-path="${esc(path)}" title="${esc(ACTION.indexTooltip)}">${ACTION.indexLabel}</button>`;
}

function localActionButtonsHtml(item, { shareClass = "result-share-btn", indexClass = "result-index-btn" } = {}) {
  const path = item.path;
  if (!isIndexedDoc(item)) return "";

  const share = canShareItem(item) ? shareButtonHtml(path, shareClass) : "";
  const lock = canShowLockItem(item) ? lockButtonHtml(path, isSyncLocked(item)) : "";
  const deleteStrata = canDeleteFromStrata(item) ? deleteStrataButtonHtml(path) : "";
  const archive = canArchiveItem(item) ? archiveButtonHtml(path) : "";
  const index = canReindexDoc(item) ? indexButtonHtml(path, indexClass) : "";
  const actions = [share, lock, deleteStrata, archive, index].filter(Boolean);
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
  const archiveBtn = $("#doc-archive-btn");
  const sep = actions?.querySelector(".action-sep");
  if (!actions || !shareBtn || !indexBtn || !lockBtn || !deleteBtn) return;

  state.activeDocPath = path;
  const indexed = isIndexedDoc(doc);
  const showShare = indexed && canShareItem(doc);
  const showLock = showShare;
  const showDelete = indexed && canDeleteFromStrata(doc);
  const showArchive = indexed && canArchiveItem(doc);

  actions.classList.toggle("hidden", !indexed);
  shareBtn.classList.toggle("hidden", !showShare);
  sep?.classList.toggle("hidden", !showShare);
  indexBtn.classList.toggle("hidden", !canReindexDoc(doc));
  lockBtn.classList.toggle("hidden", !showLock);
  deleteBtn.classList.toggle("hidden", !showDelete);
  archiveBtn?.classList.toggle("hidden", !showArchive);

  shareBtn.title = ACTION.shareTooltip;
  indexBtn.title = ACTION.indexTooltip;
  setActionIdle(shareBtn, ACTION.shareLabel);
  setActionIdle(indexBtn, ACTION.indexLabel);
  lockBtn.dataset.path = path;
  deleteBtn.dataset.path = path;
  if (archiveBtn) archiveBtn.dataset.path = path;
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
  const at = normalizeEventAt(publishedAt(item), path);
  const project = item.project || item.project_slug || "";
  const excerpt = stripMarkdown(item.excerpt || item.snippet || item.overview || item.body || "");
  const source =
    (item.storage || "file") === "db_only"
      ? "archived"
      : item.source || item.origin || "local";
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
    const k = dayKey(publishedAt(ev), ev.path || "");
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

function renderGroupedResults(results) {
  const groups = new Map();
  for (const r of results) {
    const key = r.project || "(no project)";
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(r);
  }
  let html = "";
  for (const [project, items] of groups) {
    const kinds = [...new Set(items.map((r) => r.kind).filter(Boolean))];
    html += `
      <section class="project-group">
        <header class="project-group-head">
          <button type="button" class="project-group-title" data-project="${esc(project)}" title="Scope search to ${esc(project)}">
            <i class="fa-solid fa-folder-open" aria-hidden="true"></i> ${esc(project)}
          </button>
          <span class="project-group-meta">
            ${kinds.map((k) => `<span class="badge badge-${esc(k)}">${esc(k)}</span>`).join("")}
            <span class="project-group-count">${items.length}</span>
          </span>
        </header>
        ${items.map((r) => cardHtml({ ...r, type: r.kind || "search" })).join("")}
      </section>`;
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
    if (!results.length) {
      out.innerHTML = state.activeProject
        ? '<p class="empty">No matches in this project. Try different keywords.</p>'
        : '<p class="empty">No matches in any project. Try different keywords.</p>';
    } else if (!state.activeProject) {
      out.innerHTML = renderGroupedResults(results);
    } else {
      out.innerHTML = results.map((r) => cardHtml({ ...r, type: r.kind || "search" })).join("");
    }
  } else {
    out.innerHTML = '<p class="empty">No results.</p>';
  }

  out.querySelectorAll(".project-group-title").forEach((el) => {
    el.addEventListener("click", () => {
      const project = el.dataset.project;
      if (project && project !== "(no project)") selectProject(project);
    });
  });
  out.querySelectorAll(".card[data-path]").forEach((el) => {
    el.addEventListener("click", (event) => {
      if (event.target.closest(".result-share-btn, .result-index-btn, .result-sync-btn, .result-lock-btn, .result-delete-strata-btn, .result-archive-btn")) return;
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
  bindArchiveButtons(out);
}

async function openDoc(path) {
  if (!path) return;
  const doc = await api(`/api/doc?path=${encodeURIComponent(path)}`);
  $("#doc-title").textContent = displayDocTitle(doc, path);
  $("#doc-subtitle").textContent = path.replace(/^\.md\//, "");
  $("#doc-body").innerHTML = renderMarkdown(prepareBodyForDisplay(doc.body));
  updateDocModalActions(doc, path);
  renderDocComments(doc.comments || []);
  $("#doc-modal").showModal();
}

function docCommentHtml(comment) {
  const author = comment.author_name || "unknown";
  const syncedLabel = comment.synced_at || comment.remote_comment_id ? "synced" : "local";
  return `
    <li class="doc-comment">
      <div class="doc-comment-meta">
        <strong>${esc(author)}</strong>
        <span>${esc(fmtDate(comment.created_at))}</span>
        <span class="doc-comment-sync ${syncedLabel === "synced" ? "synced" : "local"}">${syncedLabel}</span>
      </div>
      <p class="doc-comment-body">${esc(fixMojibake(comment.body || ""))}</p>
    </li>`;
}

function renderDocComments(comments) {
  const list = $("#doc-comments-list");
  if (!list) return;
  list.innerHTML = comments.length
    ? comments.map(docCommentHtml).join("")
    : '<li class="doc-comment-empty">No comments yet.</li>';
}

async function submitDocComment(event) {
  event.preventDefault();
  const path = state.activeDocPath;
  const input = $("#doc-comment-input");
  const submitBtn = $("#doc-comment-submit");
  const body = (input?.value || "").trim();
  if (!path || !body) return;
  if (submitBtn) setActionBusy(submitBtn, "Adding…");
  try {
    const result = await api("/api/documents/comment", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path, body }),
    });
    renderDocComments(result.items || []);
    if (input) input.value = "";
    showToast(
      result.synced
        ? "Comment added and synced to STRATA."
        : "Comment saved locally — it syncs when this document is shared."
    );
  } catch (err) {
    showToast(`Comment failed: ${err.message}`);
  } finally {
    if (submitBtn) setActionIdle(submitBtn, "Add Comment");
  }
}

function cssEscape(value) {
  if (window.CSS?.escape) return window.CSS.escape(value);
  return String(value).replace(/["\\]/g, "\\$&");
}

/* ── Knowledge graph explorer ── */

const KIND_COLORS = {
  handoff: "#4ade80",
  blueprint: "#93c5fd",
  plan: "#a78bfa",
  rule: "#d1d5db",
  project: "#6ea8fe",
};
const GRAPH_DIM_COLOR = "rgba(139, 149, 168, 0.18)";

let graphInstance = null;
let graphHighlightSet = null;
let graphReloadTimer = null;

function graphNodeColor(node) {
  const base = KIND_COLORS[node.type === "project" ? "project" : node.kind] || "#8b95a8";
  if (graphHighlightSet && !graphHighlightSet.has(node.id)) return GRAPH_DIM_COLOR;
  return base;
}

function graphNodeVal(node) {
  if (node.type === "project") return 7 + Math.min(node.degree || 0, 24);
  return 2 + Math.min(node.degree || 0, 12);
}

function graphNodeLabel(node) {
  if (node.type === "project") {
    return `<div class="graph-tooltip"><strong>${esc(node.title || node.project)}</strong><span>project · ${node.degree || 0} documents</span></div>`;
  }
  const when = node.published_at ? fmtDate(node.published_at) : "";
  const parts = [
    node.kind ? `<span class="graph-tooltip-kind">${esc(node.kind)}</span>` : "",
    node.project ? esc(node.project) : "",
    when ? esc(when) : "",
  ].filter(Boolean);
  return `<div class="graph-tooltip"><strong>${esc(fixMojibake(node.title || node.id))}</strong><span>${parts.join(" · ")}</span><em>${esc(node.id)}</em></div>`;
}

function graphLinkColor(link) {
  return link.type === "similar"
    ? "rgba(110, 168, 254, 0.22)"
    : link.type === "project"
      ? "rgba(139, 149, 168, 0.14)"
      : "rgba(74, 222, 128, 0.35)";
}

function graphNodeMatches(node, needle) {
  return (
    (node.title || "").toLowerCase().includes(needle) ||
    (node.project || "").toLowerCase().includes(needle) ||
    (node.id || "").toLowerCase().includes(needle)
  );
}

function applyGraphHighlight(query) {
  const needle = (query || "").trim().toLowerCase();
  if (!needle || !graphInstance) {
    graphHighlightSet = null;
  } else {
    const { nodes } = graphInstance.graphData();
    graphHighlightSet = new Set(
      nodes.filter((n) => graphNodeMatches(n, needle)).map((n) => n.id)
    );
  }
  graphInstance?.nodeColor(graphNodeColor);
}

function graphKindsFilter() {
  return selectedKinds("#graph-filter-kinds");
}

function sizeGraphCanvas() {
  const el = $("#graph-canvas");
  if (!el || !graphInstance) return;
  graphInstance.width(el.clientWidth).height(el.clientHeight);
}

function ensureGraphInstance() {
  if (graphInstance) return graphInstance;
  const el = $("#graph-canvas");
  if (!el || typeof ForceGraph === "undefined") return null;

  graphInstance = ForceGraph()(el)
    .backgroundColor("rgba(0,0,0,0)")
    .nodeId("id")
    .nodeVal(graphNodeVal)
    .nodeColor(graphNodeColor)
    .nodeLabel(graphNodeLabel)
    .linkColor(graphLinkColor)
    .linkWidth((link) => (link.type === "similar" ? 1 : Math.min(1 + link.weight * 0.6, 3)))
    .linkLineDash((link) => (link.type === "similar" ? [3, 3] : null))
    .linkLabel((link) => (link.reason ? `<div class="graph-tooltip"><span>${esc(link.reason)}</span></div>` : ""))
    .nodeCanvasObjectMode(() => "after")
    .nodeCanvasObject((node, ctx, globalScale) => {
      if (node.type !== "project") return;
      const fontSize = Math.max(11 / globalScale, 3);
      ctx.font = `600 ${fontSize}px "Segoe UI", system-ui, sans-serif`;
      ctx.textAlign = "center";
      ctx.textBaseline = "top";
      ctx.fillStyle =
        graphHighlightSet && !graphHighlightSet.has(node.id)
          ? GRAPH_DIM_COLOR
          : "rgba(236, 238, 243, 0.85)";
      const radius = Math.sqrt(Math.max(graphNodeVal(node), 1)) * 4;
      ctx.fillText(node.title || node.project || "", node.x, node.y + radius / globalScale + 2 / globalScale);
    })
    .onNodeClick((node) => {
      if (node.type === "project") {
        openGraphView(node.project);
      } else {
        openDoc(node.id);
      }
    })
    .cooldownTicks(180);

  window.addEventListener("resize", sizeGraphCanvas);
  return graphInstance;
}

async function loadGraphData() {
  const instance = ensureGraphInstance();
  const statsEl = $("#graph-stats");
  if (!instance) {
    if (statsEl) statsEl.textContent = "Graph library failed to load.";
    return;
  }

  const params = new URLSearchParams();
  if (state.graphProject) params.set("project", state.graphProject);
  const kinds = graphKindsFilter();
  if (kinds.length) params.set("kinds", kinds.join(","));
  const threshold = parseFloat(($("#graph-threshold") || {}).value || "0");
  if (threshold > 0) params.set("min_weight", String(threshold));

  if (statsEl) statsEl.textContent = "Building graph…";
  let data;
  try {
    data = await api(`/api/graph?${params.toString()}`);
  } catch (err) {
    if (statsEl) statsEl.textContent = `Graph failed: ${err.message}`;
    return;
  }

  instance.graphData({ nodes: data.nodes || [], links: data.links || [] });
  sizeGraphCanvas();
  applyGraphHighlight(($("#graph-highlight") || {}).value || "");
  if (statsEl) {
    const s = data.stats || {};
    statsEl.textContent = `${s.documents ?? 0} documents · ${s.projects ?? 0} projects · ${s.links ?? 0} links`;
  }
}

function scheduleGraphReload() {
  window.clearTimeout(graphReloadTimer);
  graphReloadTimer = window.setTimeout(() => loadGraphData(), 250);
}

function openGraphView(project) {
  if (state.view !== "graph") state.graphReturnView = state.view;
  state.graphProject = project || null;
  $("#graph-scope").textContent = project
    ? `${project} + neighbors`
    : "All projects";
  showView("graph");
  loadGraphData();
}

function closeGraphView() {
  const target = state.graphReturnView === "app" && state.activeProject ? "app" : "home";
  showView(target);
  if (target === "home") $("#home-q")?.focus();
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

async function archiveDocPath(path) {
  if (!path) return;
  const ok = window.confirm(
    `Archive for me?\n\n${path}\n\nThis removes the document from your local STRATA and it will not be pulled again. The team's remote copy is kept.`
  );
  if (!ok) return;
  try {
    const result = await api("/api/sync/archive", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paths: [path] }),
    });
    if (!result.count) {
      showToast(result.error ? `Archive failed: ${result.error}` : "Archive failed: not indexed.");
      return;
    }
    showToast("Archived — removed locally; won't re-sync from remote.");
    if (state.activeDocPath === path) {
      $("#doc-modal")?.close();
    }
    if (state.homeTab === "recent") await loadRecentLocal({ resetPage: false });
    else if (state.homeTab === "received") await loadSharedFromTeam({ resetPage: false });
    if (state.view === "app" && state.activeProject) {
      await refreshActiveProjectResults();
    }
  } catch (err) {
    showToast(`Archive failed: ${err.message}`);
  }
}

function bindArchiveButtons(container) {
  container.querySelectorAll(".result-archive-btn, .archive-one").forEach((btn) => {
    btn.addEventListener("click", (event) => {
      event.stopPropagation();
      archiveDocPath(btn.dataset.path);
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

function hasNonLocalAuthors() {
  const actor = (state.localActorName || "").trim().toLowerCase();
  const others = state.authors.filter(
    (name) => (name || "").trim().toLowerCase() !== actor
  );
  if (!actor) return state.authors.length > 1;
  return others.length > 0;
}

function updateAuthorFilterVisibility() {
  const visible = hasNonLocalAuthors();
  $("#files-filter-author")?.classList.toggle("hidden", !visible);
  $("#scoped-filter-author")?.classList.toggle("hidden", !visible);
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
    const el = $(`#${id}`);
    if (!el) continue;
    const prev = el.value;
    el.innerHTML = options;
    if (prev && state.authors.includes(prev)) el.value = prev;
  }
  updateAuthorFilterVisibility();
}

function selectedKinds(containerSel) {
  const container = $(containerSel);
  if (!container) return [];
  return [...container.querySelectorAll("input[type=checkbox]:checked")].map(
    (input) => input.value
  );
}

function filesFilterParams() {
  const params = new URLSearchParams({ hours: "168", limit: "500" });
  const kinds = selectedKinds("#files-filter-kinds");
  const author = ($("#files-filter-author") || {}).value || "";
  if (kinds.length) params.set("kinds", kinds.join(","));
  if (author) params.set("author", author);
  return params;
}

function scopedAuthorFilter() {
  return ($("#scoped-filter-author") || {}).value || "";
}

function scopedKindsFilter() {
  return selectedKinds("#scoped-filter-kinds");
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
  const kinds = scopedKindsFilter();
  const data = await api("/api/query", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      q: trimmed,
      limit: 80,
      project: state.activeProject,
      source,
      author: author || undefined,
      kinds: kinds.length ? kinds.join(",") : undefined,
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
  const kinds = scopedKindsFilter();
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
      kinds: kinds.length ? kinds.join(",") : undefined,
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
        ${esc(statusLabel(item.local_status))} · ${esc(statusLabel(item.share_status))}
        ${item.author_name ? ` · ${esc(item.author_name)}` : ""}
        · ${esc(fmtDate(item.published_at || item.updated_at))}
      </div>
      ${item.excerpt ? `<p class="card-excerpt">${esc(item.excerpt)}</p>` : ""}
      <div class="sync-actions">
        ${actions.join('<span class="action-sep" aria-hidden="true">|</span>')}
      </div>
    </article>`;
}

function recentRowHtml(item) {
  const title = item.title || titleFromPath(item.path);
  const localStatus = statusLabel(item.local_status || "indexed");
  const shareStatus = statusLabel(
    item.share_status || (item.sync_status === "shared" ? "shared" : "not shared")
  );
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
        ${item.project ? `${esc(item.project)} · ` : ""}${esc(localStatus)} · ${esc(shareStatus)}${item.author_name ? ` · ${esc(item.author_name)}` : ""} · ${esc(fmtDate(item.published_at || item.created_at || item.updated_at))}
      </div>
      <div class="sync-path">${esc(item.path)}</div>
      ${item.excerpt ? `<p class="card-excerpt">${esc(item.excerpt)}</p>` : ""}
      ${actionButtons}
    </article>`;
}

function sharedFromRowHtml(item) {
  const title = item.title || titleFromPath(item.path);
  const author = item.author_name || "";
  const archive = canArchiveItem(item) ? archiveButtonHtml(item.path, "archive-one") : "";
  return `
    <article class="sync-row recent-row" data-path="${esc(item.path)}" data-project="${esc(item.project || "")}" role="button" tabindex="0">
      <div class="sync-row-head">
        <span class="badge badge-${esc(item.kind)}">${esc(item.kind)}</span>
        <span class="recent-title">${esc(title)}</span>
      </div>
      <div class="sync-meta">
        ${item.project ? `${esc(item.project)} · ` : ""}${author ? `${esc(author)} · ` : ""}received · ${esc(fmtDate(item.published_at || item.created_at || item.updated_at || item.synced_at))}
      </div>
      <div class="sync-path">${esc(item.path)}</div>
      ${item.excerpt ? `<p class="card-excerpt">${esc(item.excerpt)}</p>` : ""}
      ${archive ? `<div class="sync-actions">${archive}</div>` : ""}
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
  bindArchiveButtons(container);
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
        if (event.target.closest(".result-share-btn, .result-index-btn, .result-sync-btn, .result-lock-btn, .result-delete-strata-btn, .result-archive-btn, .sync-one, .index-one, .delete-strata-one, .archive-one")) {
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
  const receivedTable = $("#received-from-team-table");
  if (receivedTable) bindArchiveButtons(receivedTable);
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
  if (!paths.length) {
    showToast("Nothing to share — reload the Share tab or unlock files.");
    setToolStatus("Nothing to share.");
    return;
  }
  showToast("redacting secrets from sync...", { timeout: 1800 });
  setToolStatus("redacting secrets from sync...");
  const result = await api("/api/sync/upload", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ paths, allow_locked: false }),
  });
  const syncedCount = result.synced?.length || 0;
  if (result.skipped?.length) {
    const lockedCount = result.skipped.filter((row) => row.reason === "sync_locked").length;
    if (lockedCount) {
      showToast(`${lockedCount} locked file${lockedCount === 1 ? "" : "s"} skipped from batch sync.`);
    }
  }
  if (result.failed?.length) {
    showToast("Some files could not be shared. Check sync details.");
    setToolStatus("Some files could not be shared. Check sync details.");
  } else if (syncedCount === 0) {
    showToast("Nothing was shared. Check API connection.");
    setToolStatus("Nothing was shared.");
  } else {
    showToast(`Shared ${syncedCount} file${syncedCount === 1 ? "" : "s"}.`);
    setToolStatus(`Shared ${syncedCount} file${syncedCount === 1 ? "" : "s"}.`);
  }
  await loadSyncLocal();
  await loadRecentLocal({ resetPage: false });
  await loadPotentialSecrets({ resetPage: false });
  await refreshActiveProjectResults();
  await refreshRemotePending();
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

function accentThemeById(id) {
  return ACCENT_THEMES.find((theme) => theme.id === id) || ACCENT_THEMES[0];
}

function applyAccentTheme(themeId) {
  const theme = accentThemeById(themeId);
  const root = document.documentElement;
  root.style.setProperty("--accent", theme.accent);
  root.style.setProperty("--accent-dim", theme.dim);
  root.style.setProperty("--accent-soft", theme.soft);
  root.style.setProperty("--accent-text", theme.text);
  root.dataset.accentTheme = theme.id;
  state.accentTheme = theme.id;
  document.querySelectorAll("[data-accent-option]").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.accentOption === theme.id);
  });
}

function closeAccentMenus(except) {
  document.querySelectorAll("[data-accent-picker]").forEach((picker) => {
    if (except && picker === except) return;
    const menu = picker.querySelector("[data-accent-menu]");
    const toggle = picker.querySelector("[data-accent-toggle]");
    if (menu) menu.hidden = true;
    if (toggle) toggle.setAttribute("aria-expanded", "false");
  });
}

function renderAccentMenus() {
  document.querySelectorAll("[data-accent-grid]").forEach((grid) => {
    grid.innerHTML = ACCENT_THEMES.map(
      (theme) => `
      <button
        type="button"
        class="accent-theme-option${theme.id === state.accentTheme ? " active" : ""}"
        data-accent-option="${esc(theme.id)}"
        title="${esc(theme.label)}"
      >
        <span class="accent-theme-swatch" style="background:${esc(theme.accent)}"></span>
        ${esc(theme.label)}
      </button>`
    ).join("");
  });
}

function initAccentThemePicker() {
  let saved = "blue";
  try {
    saved = localStorage.getItem(ACCENT_STORAGE_KEY) || "blue";
  } catch (_) {
    saved = "blue";
  }
  state.accentTheme = accentThemeById(saved).id;
  applyAccentTheme(state.accentTheme);
  renderAccentMenus();

  document.querySelectorAll("[data-accent-picker]").forEach((picker) => {
    const toggle = picker.querySelector("[data-accent-toggle]");
    const menu = picker.querySelector("[data-accent-menu]");
    if (!toggle || !menu) return;

    toggle.addEventListener("click", (event) => {
      event.stopPropagation();
      const willOpen = menu.hidden;
      closeAccentMenus(picker);
      menu.hidden = !willOpen;
      toggle.setAttribute("aria-expanded", willOpen ? "true" : "false");
    });

    menu.addEventListener("click", (event) => {
      const btn = event.target.closest("[data-accent-option]");
      if (!btn) return;
      const themeId = btn.dataset.accentOption;
      applyAccentTheme(themeId);
      try {
        localStorage.setItem(ACCENT_STORAGE_KEY, themeId);
      } catch (_) {
        /* private mode */
      }
      closeAccentMenus();
    });
  });

  document.addEventListener("mousedown", (event) => {
    if (event.target.closest("[data-accent-picker]")) return;
    closeAccentMenus();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeAccentMenus();
  });
}

function renderUpdateCta(status) {
  const btn = $("#client-update-btn");
  if (!btn) return;
  const available = Boolean(status?.update_available);
  state.updateAvailable = available;
  state.localVersion = status?.local_version || "";
  state.remoteVersion = status?.remote_version || "";
  btn.hidden = !available;
  if (available) {
    const local = state.localVersion || "?";
    const remote = state.remoteVersion || "?";
    btn.title = `Update STRATA client ${local} → ${remote}`;
  }
}

async function refreshUpdateStatus() {
  try {
    const status = await api("/api/update/status");
    renderUpdateCta(status);
  } catch (_) {
    renderUpdateCta({ update_available: false });
  }
}

async function runClientUpdate() {
  const btn = $("#client-update-btn");
  if (!btn || btn.disabled || btn.hidden) return;
  if (
    !window.confirm(
      `Update STRATA client from ${state.localVersion || "current"} to ${state.remoteVersion || "latest"}?\n\nThis runs the remote install script and restarts the local app.`
    )
  ) {
    return;
  }
  btn.disabled = true;
  btn.textContent = "updating…";
  showToast("Updating STRATA client…", { timeout: 8000 });
  try {
    const res = await fetch("/api/update/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    const raw = await res.text();
    let result = {};
    try {
      result = raw ? JSON.parse(raw) : {};
    } catch (_) {
      result = { error: raw || "Update failed" };
    }
    if (!res.ok || !result.ok) {
      throw new Error(result.error || raw || "Update failed");
    }
    showToast("Update complete — restarting app…", { timeout: 10000 });
    btn.textContent = "restarting…";
    // Server schedules a restart; poll until the new process answers.
    for (let i = 0; i < 40; i += 1) {
      await new Promise((r) => setTimeout(r, 1500));
      try {
        const probe = await fetch("/api/update/status", { cache: "no-store" });
        if (probe.ok) {
          window.location.reload();
          return;
        }
      } catch (_) {
        /* still restarting */
      }
    }
    showToast("Update finished — reload the page if the app does not reopen.");
    btn.hidden = true;
  } catch (err) {
    showToast(`Update failed: ${err.message}`, { timeout: 6000 });
    btn.disabled = false;
    btn.textContent = "[ update ]";
    await refreshUpdateStatus();
  }
}

function renderStatsLine(stats) {
  const el = $("#stats-line");
  if (!el) return;
  const kinds =
    stats.by_kind?.map((k) => `${kindLabel(k.kind, k.n)}: ${k.n}`).join(" · ") || "";
  el.innerHTML = esc(kinds);
}

async function refreshRemotePending() {
  if (!state.apiOnline) return;
  try {
    const remotePending = await api("/api/sync/remote-pending");
    state.remotePending = remotePending.pending || 0;
    const stats = await api("/api/stats");
    renderStatsLine(stats);
    await refreshToolCounts();
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
  renderStatsLine(stats);
  renderProjectPanels(summary);
  await loadAuthors();
  await Promise.allSettled([
    loadRecentLocal(),
    loadSyncLocal(),
    loadSharedFromTeam(),
    loadPotentialSecrets(),
  ]);
  await refreshToolCounts();
}

function handleHomeSearch(rawQ) {
  const q = rawQ.trim();
  if (!q) return;

  syncHomeAuthorToScoped();
  const source = ($("#home-source") || {}).value || "local";
  const scopedSource = $("#scoped-source");
  if (scopedSource) scopedSource.value = source;

  const detected = detectProjectFromQuery(q);
  if (detected) {
    const stripped = q.replace(new RegExp(detected, "i"), "").trim();
    enterProject(detected, stripped || q);
    return;
  }

  // Keyword searches with no project mentioned go cross-project, grouped by project.
  enterAllProjects(q);
}

function bindHomeTabControls() {
  if (bindHomeTabControls.bound) return;
  bindHomeTabControls.bound = true;

  $("#tab-recent")?.addEventListener("click", () => switchHomeTab("recent"));
  $("#tab-share")?.addEventListener("click", () => switchHomeTab("share"));
  $("#tab-received")?.addEventListener("click", () => switchHomeTab("received"));
  $("#tab-secrets")?.addEventListener("click", () => switchHomeTab("secrets"));

  $("#files-filter-kinds")?.addEventListener("change", () => reloadHomeFileTabs());
  $("#files-filter-author")?.addEventListener("change", () => {
    syncHomeAuthorToScoped();
    reloadHomeFileTabs();
  });

  $("#sync-refresh-btn")?.addEventListener("click", () => loadSyncLocal({ resetPage: false }));
  $("#received-refresh-btn")?.addEventListener("click", () => loadSharedFromTeam({ resetPage: false }));
  $("#secrets-refresh-btn")?.addEventListener("click", () => loadPotentialSecrets({ resetPage: false }));
  $("#sync-all-btn")?.addEventListener("click", async () => {
    if (!state.syncItems.length) await loadSyncLocal({ resetPage: false });
    const paths = batchSyncPaths(state.syncItems);
    if (!confirmLargeSync(paths.length)) return;
    await syncPaths(paths);
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
  if (state.apiOnline) {
    const remotePending = await api("/api/sync/remote-pending").catch(() => ({
      online: false,
      pending: 0,
    }));
    state.remotePending = remotePending.pending || 0;
  }
  if (stats) renderStatsLine(stats);
  await refreshToolCounts();
  await refreshUpdateStatus();
}

async function init() {
  initAccentThemePicker();
  bindHomeTabControls();
  switchHomeTab("recent");

  const [stats, summary, projects] = await Promise.all([
    api("/api/stats"),
    api("/api/projects/summary"),
    api("/api/projects"),
  ]);

  state.allProjects = projects;
  state.remotePending = 0;
  renderStatsLine(stats);
  renderProjectPanels(summary);
  renderSidebar();
  renderHomeSidebar();
  await loadAuthors();
  await Promise.allSettled([
    loadRecentLocal(),
    loadSyncLocal(),
    loadSharedFromTeam(),
    loadPotentialSecrets(),
  ]);
  await refreshToolCounts();

  void loadRemoteConfig(stats);

  const rerunScoped = () => {
    if (state.view !== "app") return;
    const q = $("#scoped-q").value.trim();
    if (q) runScopedSearch(q);
    else if (state.activeProject) browseProject(state.activeProject);
  };
  $("#scoped-filter-author")?.addEventListener("change", rerunScoped);
  $("#scoped-filter-kinds")?.addEventListener("change", rerunScoped);

  $("#doc-comment-form")?.addEventListener("submit", submitDocComment);

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
  $("#doc-archive-btn")?.addEventListener("click", () => archiveDocPath(state.activeDocPath));
  $("#doc-modal").addEventListener("click", (e) => {
    if (e.target === $("#doc-modal")) $("#doc-modal").close();
  });

  $("#home-menu-btn")?.addEventListener("click", () => {
    setHomeSidebarOpen(!$("#home-sidebar")?.classList.contains("open"));
  });
  $("#home-sidebar-close")?.addEventListener("click", () => setHomeSidebarOpen(false));
  $("#home-sidebar-backdrop")?.addEventListener("click", () => setHomeSidebarOpen(false));
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && $("#home-sidebar")?.classList.contains("open")) {
      setHomeSidebarOpen(false);
    }
  });

  $("#client-update-btn")?.addEventListener("click", () => runClientUpdate());
  $("#home-graph-btn")?.addEventListener("click", () => openGraphView(null));
  $("#scoped-graph-btn")?.addEventListener("click", () => openGraphView(state.activeProject));
  $("#graph-back-btn")?.addEventListener("click", closeGraphView);
  $("#graph-filter-kinds")?.addEventListener("change", () => loadGraphData());
  $("#graph-threshold")?.addEventListener("input", () => {
    const value = parseFloat($("#graph-threshold").value || "0");
    const out = $("#graph-threshold-value");
    if (out) out.textContent = value.toFixed(2);
    scheduleGraphReload();
  });
  $("#graph-highlight")?.addEventListener("input", () => {
    applyGraphHighlight($("#graph-highlight").value);
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
