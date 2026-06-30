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
  "plans in progress",
  "recent handoffs",
];

const $ = (sel) => document.querySelector(sel);

marked.setOptions({ gfm: true, breaks: true });

const state = {
  view: "home",
  activeProject: null,
  allProjects: [],
  latestProjects: [],
  apiOnline: false,
  syncItems: [],
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
    btn.addEventListener("click", () => enterProject(btn.dataset.project));
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

function enterProject(project, initialQuery = "") {
  state.activeProject = project;
  $("#active-project").textContent = project;
  showView("app");
  renderSidebar();
  highlightActiveProject();

  const q = initialQuery.trim();
  $("#scoped-q").value = q;
  $("#scoped-q").placeholder = `Search within ${project}…`;

  runScopedSearch(q);
  $("#scoped-q").focus();
}

function selectProject(project) {
  state.activeProject = project;
  $("#active-project").textContent = project;
  highlightActiveProject();
  $("#scoped-q").placeholder = `Search within ${project}…`;
  runScopedSearch($("#scoped-q").value.trim() || "");
}

function goHome() {
  state.activeProject = null;
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

function cardHtml(item) {
  const type = item.type || item.kind || "search";
  const path = item.path || "";
  const title = friendlyCardTitle(item);
  const at = normalizeEventAt(item.at || item.updated_at || item.created_at, path);
  const project = item.project || item.project_slug || "";
  const excerpt = stripMarkdown(item.excerpt || item.snippet || item.overview || item.body || "");
  const source = item.source || item.origin || "local";
  const author = item.author_name || "";

  return `
    <article class="card" data-path="${esc(path)}">
      <div class="card-head">
        <span class="badge badge-${esc(type)}">${esc(type)}</span>
        <span class="badge badge-source">${esc(source)}</span>
        <span class="card-title">${esc(title)}</span>
      </div>
      <div class="card-meta">${esc(project)} · ${esc(fmtDate(at))}${author ? ` · ${esc(author)}` : ""}</div>
      ${excerpt ? `<p class="card-excerpt">${esc(excerpt)}</p>` : ""}
    </article>`;
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
    el.addEventListener("click", () => openDoc(el.dataset.path));
  });
}

async function openDoc(path) {
  if (!path) return;
  const doc = await api(`/api/doc?path=${encodeURIComponent(path)}`);
  $("#doc-title").textContent = displayDocTitle(doc, path);
  $("#doc-subtitle").textContent = path.replace(/^\.md\//, "");
  $("#doc-body").innerHTML = renderMarkdown(prepareBodyForDisplay(doc.body));
  $("#doc-modal").showModal();
}

async function runScopedSearch(q) {
  $("#output").innerHTML = '<p class="empty loading">Searching…</p>';
  const source = ($("#scoped-source") || {}).value || "local";
  const data = await api("/api/query", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      q,
      limit: 80,
      project: state.activeProject,
      source,
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
        <button type="button" class="ghost-btn sync-one" data-path="${esc(item.path)}">Sync</button>
        <button type="button" class="ghost-btn index-one" data-path="${esc(item.path)}">Index Only</button>
      </div>
    </article>`;
}

async function loadSyncLocal() {
  const kind = ($("#sync-filter-kind") || {}).value || "";
  const params = new URLSearchParams();
  if (kind) params.set("kind", kind);
  const data = await api(`/api/sync/local?${params.toString()}`);
  state.syncItems = data.items || [];
  const el = $("#sync-local-table");
  if (!state.syncItems.length) {
    el.innerHTML = '<p class="empty">All local artifacts are indexed and shared.</p>';
    return;
  }
  el.innerHTML = state.syncItems.map(syncRowHtml).join("");
  el.querySelectorAll(".sync-one").forEach((btn) => {
    btn.addEventListener("click", () => syncPaths([btn.dataset.path]));
  });
  el.querySelectorAll(".index-one").forEach((btn) => {
    btn.addEventListener("click", () => indexPaths([btn.dataset.path]));
  });
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
}

async function indexPaths(paths) {
  await api("/api/sync/index", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ paths }),
  });
  await loadSyncLocal();
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
  const kinds =
    stats.by_kind?.map((k) => `${kindLabel(k.kind, k.n)}: ${k.n}`).join(" · ") || "";
  $("#stats-line").textContent = `${kinds}`;

  renderProjectPanels(summary);
  renderSidebar();
  await loadSyncLocal();

  $("#sync-refresh-btn")?.addEventListener("click", () => loadSyncLocal());
  $("#sync-filter-kind")?.addEventListener("change", () => loadSyncLocal());
  $("#sync-all-btn")?.addEventListener("click", () => {
    syncPaths(state.syncItems.map((i) => i.path));
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
