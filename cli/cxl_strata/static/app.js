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
const RECENT_PAGE_SIZE = 6;

const ACTION = {
  shareLabel: "Share to Team",
  shareBusy: "Sharing…",
  shareTooltip:
    "Upload this file to the STRATA API so teammates can search and read it centrally.",
  indexLabel: "Re-index Locally",
  indexBusy: "Indexing…",
  indexTooltip:
    "Re-read this file from disk and refresh your local SQLite index without uploading.",
};

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
  recentItems: [],
  recentPage: 0,
  homeTab: "recent",
  activeDocPath: null,
  authors: [],
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
    data.hours ? `${data.hours}h window` : null,
  ].filter(Boolean);
  el.innerHTML = parts.join(" · ");
  el.classList.toggle("hidden", !parts.length);
}

function isLocalItem(item) {
  return (item.source || item.origin || "local") === "local";
}

function canShareItem(item) {
  return (
    Boolean(item?.path) &&
    isLocalItem(item) &&
    (item.syncable === true ||
      item.sync_status === "not_shared" ||
      item.sync_status === "changed")
  );
}

function shareButtonHtml(path, className = "result-share-btn") {
  return `<button type="button" class="cta-btn cta-share ${className}" data-path="${esc(path)}" title="${esc(ACTION.shareTooltip)}">${ACTION.shareLabel}</button>`;
}

function indexButtonHtml(path, className = "result-index-btn") {
  return `<button type="button" class="cta-btn cta-index ${className}" data-path="${esc(path)}" title="${esc(ACTION.indexTooltip)}">${ACTION.indexLabel}</button>`;
}

function localActionButtonsHtml(item, { shareClass = "result-share-btn", indexClass = "result-index-btn" } = {}) {
  const path = item.path;
  if (!path || !isLocalItem(item)) return "";

  const share = canShareItem(item) ? shareButtonHtml(path, shareClass) : "";
  const index = indexButtonHtml(path, indexClass);
  const sep = share ? `<span class="action-sep" aria-hidden="true">|</span>` : "";
  return `<div class="card-actions">${share}${sep}${index}</div>`;
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
  const sep = actions?.querySelector(".action-sep");
  if (!actions || !shareBtn || !indexBtn) return;

  state.activeDocPath = path;
  const local = isLocalItem(doc);
  const showShare = local && canShareItem(doc);

  actions.classList.toggle("hidden", !local);
  shareBtn.classList.toggle("hidden", !showShare);
  sep?.classList.toggle("hidden", !showShare);
  indexBtn.classList.toggle("hidden", !local);

  shareBtn.title = ACTION.shareTooltip;
  indexBtn.title = ACTION.indexTooltip;
  setActionIdle(shareBtn, ACTION.shareLabel);
  setActionIdle(indexBtn, ACTION.indexLabel);
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

function renderTimeline(events) {
  if (!events?.length) {
    return '<p class="empty">No activity in this window. Try a broader search or longer range.</p>';
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

  if (data.intent === "timeline" && data.events) {
    out.innerHTML = renderTimeline(data.events);
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
      if (event.target.closest(".result-share-btn, .result-index-btn, .result-sync-btn")) return;
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

  const result = await api("/api/sync/upload", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ paths: [path] }),
  });
  if (result.failed?.length) {
    alert(result.failed.map((f) => `${f.path}: ${f.error}`).join("\n"));
    if (btn) setActionIdle(btn, ACTION.shareLabel);
    return;
  }

  await refreshActiveProjectResults();
  await loadSyncLocal();
  await loadRecentLocal({ resetPage: false });
  await refreshRemotePending();

  if (state.activeDocPath === path && $("#doc-modal")?.open) {
    const doc = await api(`/api/doc?path=${encodeURIComponent(path)}`);
    updateDocModalActions(doc, path);
  }
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

async function indexDocFromModal() {
  const path = state.activeDocPath;
  if (!path) return;
  const btn = $("#doc-index-btn");
  setActionBusy(btn, ACTION.indexBusy);
  try {
    await indexPaths([path]);
    await loadRecentLocal({ resetPage: false });
  } finally {
    setActionIdle(btn, ACTION.indexLabel);
  }
}

async function loadAuthors() {
  const data = await api("/api/authors").catch(() => ({ authors: [] }));
  state.authors = data.authors || [];
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
  const params = new URLSearchParams();
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
      limit: 80,
      project,
      source,
      author: author || undefined,
    }),
  });
  renderResults(data);
}

function syncRowHtml(item) {
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
        ${shareButtonHtml(item.path, "sync-one")}
        <span class="action-sep" aria-hidden="true">|</span>
        ${indexButtonHtml(item.path, "index-one")}
      </div>
    </article>`;
}

function recentRowHtml(item) {
  const title = item.title || titleFromPath(item.path);
  const localStatus = item.local_status || "indexed";
  const shareStatus = item.share_status || (item.sync_status === "shared" ? "shared" : "not shared");
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
    </article>`;
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
      row.addEventListener("click", activate);
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
    emptyMessage: "No local edits or shares in the last 7 days.",
    onPageChange: (page) => {
      state.recentPage = page;
    },
    onRowActivate: (dataset) => openRecentFile(dataset.path, dataset.project),
  });
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
  $("#tab-recent")?.classList.toggle("active", isRecent);
  $("#tab-share")?.classList.toggle("active", !isRecent);
  $("#tab-recent")?.setAttribute("aria-selected", isRecent ? "true" : "false");
  $("#tab-share")?.setAttribute("aria-selected", isRecent ? "false" : "true");
  $("#panel-recent")?.classList.toggle("hidden", !isRecent);
  $("#panel-share")?.classList.toggle("hidden", isRecent);
  if (isRecent) loadRecentLocal({ resetPage: false });
}

async function loadRecentLocal({ resetPage = true } = {}) {
  const params = filesFilterParams();
  const data = await api(`/api/documents/recent-local?${params.toString()}`);
  state.recentItems = data.items || [];
  if (resetPage) state.recentPage = 0;
  renderRecentPage();
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
}

async function loadSyncLocal({ resetPage = true } = {}) {
  const params = filesFilterParams();
  const data = await api(`/api/sync/local?${params.toString()}`);
  state.syncItems = data.items || [];
  if (resetPage) state.syncPage = 0;
  renderSyncPage();
}

async function syncPaths(paths) {
  const result = await api("/api/sync/upload", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ paths }),
  });
  if (result.failed?.length) {
    alert(result.failed.map((f) => `${f.path}: ${f.error}`).join("\n"));
  }
  await loadSyncLocal();
  await loadRecentLocal({ resetPage: false });
}

async function indexPaths(paths) {
  await api("/api/sync/index", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ paths }),
  });
  await loadSyncLocal();
  await loadRecentLocal({ resetPage: false });
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
  await Promise.all([loadRecentLocal(), loadSyncLocal()]);
}

function handleHomeSearch(rawQ) {
  const q = rawQ.trim();
  if (!q) return;

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

async function init() {
  const [stats, summary, projects, cfg] = await Promise.all([
    api("/api/stats"),
    api("/api/projects/summary"),
    api("/api/projects"),
    api("/api/config").catch(() => ({ online: false })),
  ]);

  renderApiStatus(cfg);
  state.allProjects = projects;

  let remotePending = { online: false, pending: 0 };
  if (state.apiOnline) {
    remotePending = await api("/api/sync/remote-pending").catch(() => ({
      online: false,
      pending: 0,
    }));
  }
  state.remotePending = remotePending.pending || 0;
  renderStatsLine(stats, remotePending);

  renderProjectPanels(summary);
  renderSidebar();
  await loadAuthors();
  await Promise.all([loadRecentLocal(), loadSyncLocal()]);

  $("#tab-recent")?.addEventListener("click", () => switchHomeTab("recent"));
  $("#tab-share")?.addEventListener("click", () => switchHomeTab("share"));

  $("#files-filter-kind")?.addEventListener("change", () => reloadHomeFileTabs());
  $("#files-filter-author")?.addEventListener("change", () => reloadHomeFileTabs());
  $("#scoped-filter-author")?.addEventListener("change", () => {
    if (state.view === "app" && state.activeProject) {
      const q = $("#scoped-q").value.trim();
      if (q) runScopedSearch(q);
      else browseProject(state.activeProject);
    }
  });

  $("#sync-refresh-btn")?.addEventListener("click", () => loadSyncLocal({ resetPage: false }));
  $("#sync-all-btn")?.addEventListener("click", () => {
    syncPaths(state.syncItems.map((i) => i.path));
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

  switchHomeTab("recent");

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
  $("#doc-modal").addEventListener("click", (e) => {
    if (e.target === $("#doc-modal")) $("#doc-modal").close();
  });

  showView("home");
}

init().catch((err) => {
  const el = $("#output") || $("#view-home");
  if (el) {
    el.innerHTML = `<p class="empty">Failed to load: ${esc(err.message)}</p>`;
  }
});
