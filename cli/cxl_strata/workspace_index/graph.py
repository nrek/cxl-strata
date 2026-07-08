"""Knowledge graph builder over the local workspace index.

Builds a force-directed graph payload from the ``documents`` table:

- Nodes: one per document, plus one hub node per project.
- Explicit edges: doc->project membership; doc<->doc for shared Linear
  tickets, overlapping ``files_changed`` entries, and shared tags.
- Similarity edges: stdlib TF-IDF over title+body tokens, cosine
  similarity, thresholded and capped per node so the graph stays legible.

Pure stdlib; the full graph is cached in-process keyed on the index
signature (doc count + max updated_at) and rebuilt only after reindex.
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

MAX_TERMS_PER_DOC = 40
DEFAULT_SIMILARITY_THRESHOLD = 0.2
MAX_SIMILAR_EDGES_PER_NODE = 5
# Terms appearing in more documents than this are too common to signal a
# meaningful pairwise link (and would make edge building quadratic).
MAX_TERM_POSTINGS = 150
# Shared files/tags/tickets touching more docs than this create hairballs.
MAX_GROUP_SIZE = 30

FENCED_CODE_RE = re.compile(r"```.*?```", re.DOTALL)
TOKEN_RE = re.compile(r"[a-z][a-z0-9_\-.]{2,}")

# English stopwords plus handoff/plan boilerplate that appears in nearly
# every indexed document and would otherwise dominate similarity.
STOPWORDS = frozenset(
    """
    the and for are with that this from was were has have had not you your
    can could should would will just like when what which where while then
    than them they their there these those been being both because before
    after above below into over under again further once here all any each
    few more most other some such only own same too very but its it's about
    against between through during out off down does doing did don doesn
    isn wasn weren won student etc via per may might must shall

    changed decisions decision verification follow followup follow-up
    deployment deploy deployed files file changed handoff handoffs plan
    plans blueprint blueprints rule rules project projects workspace repo
    repos update updated updates add added adds new fix fixed fixes bug
    note notes todo todos task tasks step steps run running runs use used
    using user users set sets code line lines section sections also now
    still already need needs needed work works working done complete
    completed change changes make makes made making keep keeps kept
    first second next last latest current existing local remote server
    value values name names key keys type types data list lists item items
    check checks checked test tests tested testing text path paths
    """.split()
)

_cache: dict[str, Any] = {"signature": None, "graph": None}


# ---------------------------------------------------------------------------
# Tokenization / TF-IDF


def tokenize(text: str) -> list[str]:
    """Lowercased informative tokens with fenced code blocks stripped."""
    if not text:
        return []
    cleaned = FENCED_CODE_RE.sub(" ", text.lower())
    out: list[str] = []
    for tok in TOKEN_RE.findall(cleaned):
        tok = tok.strip(".-_")
        if len(tok) < 3 or tok in STOPWORDS:
            continue
        out.append(tok)
    return out


def _top_terms_vector(
    tokens: list[str], idf: dict[str, float], k: int = MAX_TERMS_PER_DOC
) -> dict[str, float]:
    """L2-normalized TF-IDF vector restricted to the doc's top-k terms."""
    if not tokens:
        return {}
    counts: dict[str, int] = defaultdict(int)
    for tok in tokens:
        counts[tok] += 1
    total = len(tokens)
    weights = {
        term: (n / total) * idf.get(term, 0.0)
        for term, n in counts.items()
        if idf.get(term, 0.0) > 0.0
    }
    top = sorted(weights.items(), key=lambda kv: kv[1], reverse=True)[:k]
    norm = math.sqrt(sum(w * w for _, w in top))
    if norm <= 0:
        return {}
    return {term: w / norm for term, w in top}


# ---------------------------------------------------------------------------
# Full-graph construction (cached)


def _index_signature(conn: sqlite3.Connection) -> tuple[int, str | None]:
    row = conn.execute(
        "SELECT COUNT(*) AS n, MAX(updated_at) AS m FROM documents"
    ).fetchone()
    return (int(row["n"]), row["m"])


def _load_json_list(raw: Any) -> list[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    return [str(x).strip() for x in data if str(x).strip()]


def _activity_at(row: dict[str, Any]) -> str:
    values = [
        str(v)
        for v in (row.get("published_at"), row.get("updated_at"), row.get("created_at"))
        if v
    ]
    return max(values) if values else ""


def _merge_reason(reasons: list[str], reason: str) -> None:
    if reason not in reasons:
        reasons.append(reason)


def _explicit_links(docs: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    """Pairwise doc links from shared tickets, files, and tags."""
    by_ticket: dict[str, list[str]] = defaultdict(list)
    by_file: dict[str, list[str]] = defaultdict(list)
    by_tag: dict[str, list[str]] = defaultdict(list)

    for doc in docs:
        path = doc["path"]
        ticket = (doc.get("linear_task_id") or "").strip().upper()
        if ticket:
            by_ticket[ticket].append(path)
        for f in doc["_files"]:
            by_file[f.replace("\\", "/").lower()].append(path)
        for t in doc["_tags"]:
            by_tag[t.lower()].append(path)

    pairs: dict[tuple[str, str], dict[str, Any]] = {}

    def add(paths: list[str], reason: str, weight: float) -> None:
        if len(paths) < 2 or len(paths) > MAX_GROUP_SIZE:
            return
        unique = sorted(set(paths))
        for i, a in enumerate(unique):
            for b in unique[i + 1 :]:
                link = pairs.setdefault(
                    (a, b),
                    {"type": "explicit", "weight": 0.0, "reasons": []},
                )
                link["weight"] += weight
                _merge_reason(link["reasons"], reason)

    for ticket, paths in by_ticket.items():
        add(paths, f"shares ticket {ticket}", 2.0)
    for fname, paths in by_file.items():
        add(paths, f"touches {fname.split('/')[-1]}", 1.0)
    for tag, paths in by_tag.items():
        add(paths, f"shares tag {tag}", 1.0)

    return pairs


def _similarity_links(
    docs: list[dict[str, Any]],
    *,
    threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    max_per_node: int = MAX_SIMILAR_EDGES_PER_NODE,
) -> dict[tuple[str, str], dict[str, Any]]:
    """Pairwise cosine-similarity links via an inverted term index."""
    postings: dict[str, list[tuple[int, float]]] = defaultdict(list)
    for i, doc in enumerate(docs):
        for term, w in doc["_vector"].items():
            postings[term].append((i, w))

    scores: dict[tuple[int, int], float] = defaultdict(float)
    shared_terms: dict[tuple[int, int], list[str]] = defaultdict(list)
    for term, posting in postings.items():
        if len(posting) < 2 or len(posting) > MAX_TERM_POSTINGS:
            continue
        for x in range(len(posting)):
            i, wi = posting[x]
            for y in range(x + 1, len(posting)):
                j, wj = posting[y]
                key = (i, j)
                scores[key] += wi * wj
                if len(shared_terms[key]) < 6:
                    shared_terms[key].append(term)

    # Keep each node's strongest neighbors; an edge survives if either
    # endpoint ranks it in its own top-k (union keeps hubs connected).
    per_node: dict[int, list[tuple[float, tuple[int, int]]]] = defaultdict(list)
    for key, score in scores.items():
        if score < threshold:
            continue
        per_node[key[0]].append((score, key))
        per_node[key[1]].append((score, key))

    kept: set[tuple[int, int]] = set()
    for _, edges in per_node.items():
        edges.sort(key=lambda kv: kv[0], reverse=True)
        for score, key in edges[:max_per_node]:
            kept.add(key)

    links: dict[tuple[str, str], dict[str, Any]] = {}
    for i, j in kept:
        a, b = docs[i]["path"], docs[j]["path"]
        if a > b:
            a, b = b, a
        terms = shared_terms[(i, j)][:4]
        links[(a, b)] = {
            "type": "similar",
            "weight": round(scores[(i, j)], 4),
            "reasons": [f"similar terms: {', '.join(terms)}"] if terms else [],
        }
    return links


def _build_full_graph(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT path, kind, project, title, published_at, created_at,
               updated_at, plan_status, linear_task_id, files_changed,
               tags, author_name, body
        FROM documents
        """
    ).fetchall()

    docs: list[dict[str, Any]] = []
    token_lists: list[list[str]] = []
    for row in rows:
        doc = dict(row)
        doc["_files"] = _load_json_list(doc.pop("files_changed", None))
        doc["_tags"] = _load_json_list(doc.pop("tags", None))
        tokens = tokenize(f"{doc.get('title') or ''}\n{doc.pop('body', '') or ''}")
        token_lists.append(tokens)
        docs.append(doc)

    n_docs = len(docs)
    df: dict[str, int] = defaultdict(int)
    for tokens in token_lists:
        for term in set(tokens):
            df[term] += 1
    idf = {term: math.log(n_docs / (1 + count)) + 1.0 for term, count in df.items()}

    for doc, tokens in zip(docs, token_lists):
        doc["_vector"] = _top_terms_vector(tokens, idf)

    doc_links = _explicit_links(docs)
    for key, link in _similarity_links(docs).items():
        if key in doc_links:
            doc_links[key]["weight"] += link["weight"]
            for reason in link["reasons"]:
                _merge_reason(doc_links[key]["reasons"], reason)
            doc_links[key]["similarity"] = link["weight"]
        else:
            link["similarity"] = link["weight"]
            doc_links[key] = link

    nodes: dict[str, dict[str, Any]] = {}
    for doc in docs:
        nodes[doc["path"]] = {
            "id": doc["path"],
            "type": "document",
            "kind": doc.get("kind"),
            "project": doc.get("project"),
            "title": doc.get("title"),
            "published_at": doc.get("published_at"),
            "plan_status": doc.get("plan_status"),
            "author_name": doc.get("author_name"),
            "activity_at": _activity_at(doc),
        }

    vectors = {doc["path"]: doc["_vector"] for doc in docs}
    return {"nodes": nodes, "doc_links": doc_links, "idf": idf, "vectors": vectors}


def _full_graph(conn: sqlite3.Connection) -> dict[str, Any]:
    signature = _index_signature(conn)
    if _cache["signature"] != signature or _cache["graph"] is None:
        _cache["graph"] = _build_full_graph(conn)
        _cache["signature"] = signature
    return _cache["graph"]


def invalidate_cache() -> None:
    _cache["signature"] = None
    _cache["graph"] = None


# ---------------------------------------------------------------------------
# Public API


def build_graph(
    conn: sqlite3.Connection,
    *,
    project: str | None = None,
    kinds: list[str] | None = None,
    hours: int | None = None,
    min_weight: float | None = None,
) -> dict[str, Any]:
    """Filtered ``{nodes, links}`` payload for the graph explorer UI.

    ``project`` keeps that project's documents plus their direct
    cross-project neighbors. ``min_weight`` applies to similarity edges
    only (explicit metadata links always survive).
    """
    full = _full_graph(conn)
    nodes: dict[str, dict[str, Any]] = full["nodes"]
    doc_links: dict[tuple[str, str], dict[str, Any]] = full["doc_links"]

    kind_set = {k.strip() for k in kinds if k and k.strip()} if kinds else None
    since = ""
    if hours and hours > 0:
        since = (
            (datetime.now(timezone.utc) - timedelta(hours=hours))
            .isoformat()
            .replace("+00:00", "Z")
        )

    def base_keep(node: dict[str, Any]) -> bool:
        if kind_set and node.get("kind") not in kind_set:
            return False
        if since and (node.get("activity_at") or "") < since:
            return False
        return True

    eligible = {path for path, node in nodes.items() if base_keep(node)}

    if project:
        seed = {p for p in eligible if nodes[p].get("project") == project}
        keep = set(seed)
        for (a, b), _link in doc_links.items():
            if a in seed and b in eligible:
                keep.add(b)
            elif b in seed and a in eligible:
                keep.add(a)
    else:
        keep = eligible

    out_links: list[dict[str, Any]] = []
    degree: dict[str, int] = defaultdict(int)
    for (a, b), link in doc_links.items():
        if a not in keep or b not in keep:
            continue
        if (
            min_weight is not None
            and link["type"] == "similar"
            and link["weight"] < min_weight
        ):
            continue
        out_links.append(
            {
                "source": a,
                "target": b,
                "type": link["type"],
                "weight": round(float(link["weight"]), 4),
                "reason": "; ".join(link["reasons"]),
            }
        )
        degree[a] += 1
        degree[b] += 1

    out_nodes: list[dict[str, Any]] = []
    hub_members: dict[str, int] = defaultdict(int)
    for path in keep:
        node = dict(nodes[path])
        node["degree"] = degree[path]
        out_nodes.append(node)
        if node.get("project"):
            hub_members[node["project"]] += 1

    for slug, count in sorted(hub_members.items()):
        hub_id = f"project:{slug}"
        out_nodes.append(
            {
                "id": hub_id,
                "type": "project",
                "project": slug,
                "title": slug,
                "degree": count,
            }
        )
        for path in keep:
            if nodes[path].get("project") == slug:
                out_links.append(
                    {
                        "source": hub_id,
                        "target": path,
                        "type": "project",
                        "weight": 1.0,
                        "reason": f"in project {slug}",
                    }
                )

    return {
        "nodes": out_nodes,
        "links": out_links,
        "stats": {
            "documents": len(keep),
            "projects": len(hub_members),
            "links": len(out_links),
            "project": project,
        },
    }


def _neighbor_item(
    node: dict[str, Any], weight: float, link_type: str, reason: str
) -> dict[str, Any]:
    return {
        "path": node["id"],
        "kind": node.get("kind"),
        "project": node.get("project"),
        "title": node.get("title"),
        "published_at": node.get("published_at"),
        "weight": round(float(weight), 4),
        "link_type": link_type,
        "reason": reason,
    }


def neighbors(
    conn: sqlite3.Connection,
    path_or_query: str,
    *,
    limit: int = 10,
) -> dict[str, Any]:
    """Ranked related documents for a document path or free-text query.

    Path mode walks the precomputed graph edges (explicit links rank above
    similarity). Query mode scores the query's TF-IDF vector against every
    document, so agents can ask "was this solved before?" without a path.
    """
    full = _full_graph(conn)
    nodes: dict[str, dict[str, Any]] = full["nodes"]
    key = (path_or_query or "").strip().replace("\\", "/")

    if key in nodes:
        items: list[dict[str, Any]] = []
        for (a, b), link in full["doc_links"].items():
            if key not in (a, b):
                continue
            other = b if a == key else a
            items.append(
                _neighbor_item(
                    nodes[other],
                    link["weight"],
                    link["type"],
                    "; ".join(link["reasons"]),
                )
            )
        items.sort(key=lambda it: (it["link_type"] == "similar", -it["weight"]))
        return {"mode": "path", "path": key, "related": items[:limit]}

    tokens = tokenize(path_or_query)
    vector = _top_terms_vector(tokens, full["idf"])
    scored: list[tuple[float, str, list[str]]] = []
    for path, doc_vector in full["vectors"].items():
        if not doc_vector:
            continue
        shared = [t for t in vector if t in doc_vector]
        if not shared:
            continue
        score = sum(vector[t] * doc_vector[t] for t in shared)
        if score > 0:
            scored.append((score, path, shared[:4]))
    scored.sort(key=lambda item: item[0], reverse=True)

    related = [
        _neighbor_item(
            nodes[path], score, "similar", f"matched terms: {', '.join(terms)}"
        )
        for score, path, terms in scored[:limit]
    ]
    return {"mode": "query", "query": path_or_query, "related": related}
