from __future__ import annotations

from pathlib import Path

import pytest

import cxl_strata
from cxl_strata.workspace_index import db, graph, indexer
from cxl_strata.workspace_index.paths import set_workspace_root


HANDOFF_BACKFILL_A = """# Handoff — 2026-07-01T10-00-00Z

- **Changed:** Rebuilt the keystones backfill pipeline for binance gap recovery.
  Regenerated fit metrics and infinity stones coordinates after the outage.
- **Verification:** backfill script reran cleanly against stones database.
- **Files changed:** scripts/backfill_stones.py
"""

HANDOFF_BACKFILL_B = """# Handoff — 2026-07-02T10-00-00Z

- **Changed:** Second pass on the keystones backfill for binance gap recovery.
  Fit metrics regenerated; infinity stones coordinates verified after outage.
- **Files changed:** scripts/backfill_stones.py
"""

HANDOFF_UNRELATED = """# Handoff — 2026-07-03T10-00-00Z

- **Changed:** Rewrote the checkout payment webhook for stripe subscriptions.
  Membership invoices render receipts and customer portals correctly.
"""

PLAN_TICKET = """---
name: Backfill plan
overview: Plan the binance keystones backfill recovery
linear_task_id: CXL-9999
status: in_progress
---

# Backfill plan

Recover keystones backfill gaps for binance fit metrics.
"""

HANDOFF_TICKET = """# Handoff — 2026-07-04T10-00-00Z

[CXL-9999] worked the backfill ticket.

- **Changed:** Executed the CXL-9999 recovery steps.
"""


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    handoffs = tmp_path / ".md" / "handoff"
    (handoffs / "synq-phalanx").mkdir(parents=True)
    (handoffs / "synq-forge").mkdir(parents=True)
    (handoffs / "commonspace-app").mkdir(parents=True)
    (tmp_path / ".md" / "blueprints").mkdir()
    plans = tmp_path / ".cursor" / "plans" / "in_progress"
    plans.mkdir(parents=True)

    (handoffs / "synq-phalanx" / "2026-07-01T10-00-00Z.md").write_text(
        HANDOFF_BACKFILL_A, encoding="utf-8"
    )
    (handoffs / "synq-forge" / "2026-07-02T10-00-00Z.md").write_text(
        HANDOFF_BACKFILL_B, encoding="utf-8"
    )
    (handoffs / "commonspace-app" / "2026-07-03T10-00-00Z.md").write_text(
        HANDOFF_UNRELATED, encoding="utf-8"
    )
    (handoffs / "synq-phalanx" / "2026-07-04T10-00-00Z.md").write_text(
        HANDOFF_TICKET, encoding="utf-8"
    )
    (plans / "backfill_plan.plan.md").write_text(PLAN_TICKET, encoding="utf-8")

    set_workspace_root(tmp_path)
    graph.invalidate_cache()
    indexer.index_all(prune=False)
    return tmp_path


def _link_between(links: list[dict], a: str, b: str) -> dict | None:
    for link in links:
        if {link["source"], link["target"]} == {a, b}:
            return link
    return None


PATH_A = ".md/handoff/synq-phalanx/2026-07-01T10-00-00Z.md"
PATH_B = ".md/handoff/synq-forge/2026-07-02T10-00-00Z.md"
PATH_UNRELATED = ".md/handoff/commonspace-app/2026-07-03T10-00-00Z.md"
PATH_TICKET = ".md/handoff/synq-phalanx/2026-07-04T10-00-00Z.md"
PATH_PLAN = ".cursor/plans/in_progress/backfill_plan.plan.md"


def test_build_graph_nodes_and_project_hubs(workspace: Path) -> None:
    with db.connect() as conn:
        db.init_db(conn)
        data = graph.build_graph(conn)

    ids = {n["id"] for n in data["nodes"]}
    assert PATH_A in ids
    assert PATH_B in ids
    assert "project:synq-phalanx" in ids
    assert "project:synq-forge" in ids

    hub_links = [l for l in data["links"] if l["type"] == "project"]
    assert any(
        l["source"] == "project:synq-phalanx" and l["target"] == PATH_A
        for l in hub_links
    )


def test_similar_documents_get_cross_project_edge(workspace: Path) -> None:
    with db.connect() as conn:
        db.init_db(conn)
        data = graph.build_graph(conn)

    link = _link_between(data["links"], PATH_A, PATH_B)
    assert link is not None, "near-duplicate backfill handoffs should be linked"
    assert "similar terms" in link["reason"] or "touches" in link["reason"]

    unrelated = _link_between(data["links"], PATH_B, PATH_UNRELATED)
    assert unrelated is None, "payment webhook doc must not link to backfill docs"


def test_shared_files_changed_creates_explicit_edge(workspace: Path) -> None:
    with db.connect() as conn:
        db.init_db(conn)
        data = graph.build_graph(conn)

    link = _link_between(data["links"], PATH_A, PATH_B)
    assert link is not None
    assert link["type"] == "explicit"
    assert "touches backfill_stones.py" in link["reason"]


def test_shared_linear_ticket_creates_explicit_edge(workspace: Path) -> None:
    with db.connect() as conn:
        db.init_db(conn)
        data = graph.build_graph(conn)

    link = _link_between(data["links"], PATH_TICKET, PATH_PLAN)
    assert link is not None
    assert link["type"] == "explicit"
    assert "shares ticket CXL-9999" in link["reason"]


def test_kind_filter_limits_nodes(workspace: Path) -> None:
    with db.connect() as conn:
        db.init_db(conn)
        data = graph.build_graph(conn, kinds=["plan"])

    doc_nodes = [n for n in data["nodes"] if n["type"] == "document"]
    assert doc_nodes
    assert all(n["kind"] == "plan" for n in doc_nodes)


def test_authors_filter_limits_nodes(workspace: Path) -> None:
    with db.connect() as conn:
        db.init_db(conn)
        conn.execute(
            "UPDATE documents SET author_name = ? WHERE path = ?",
            ("Alice", PATH_A),
        )
        conn.execute(
            "UPDATE documents SET author_name = ? WHERE path = ?",
            ("Bob", PATH_B),
        )
        conn.execute(
            "UPDATE documents SET author_name = ? WHERE path = ?",
            ("Alice", PATH_TICKET),
        )
        conn.commit()
        graph.invalidate_cache()
        data = graph.build_graph(conn, authors=["Alice"])

    doc_nodes = [n for n in data["nodes"] if n["type"] == "document"]
    ids = {n["id"] for n in doc_nodes}
    assert PATH_A in ids
    assert PATH_TICKET in ids
    assert PATH_B not in ids
    assert data["meta"]["authors"] == ["alice"]


def test_hours_filter_and_meta_max_days(workspace: Path) -> None:
    old = "2026-01-01T00:00:00Z"
    recent = "2026-07-20T12:00:00Z"
    with db.connect() as conn:
        db.init_db(conn)
        # activity_at = max(published, updated, created); pin times so the
        # hours window is deterministic (file mtime from fixtures is "now").
        conn.execute(
            """
            UPDATE documents
            SET published_at = ?, updated_at = ?, created_at = ?
            WHERE path = ?
            """,
            (old, old, old, PATH_A),
        )
        conn.execute(
            """
            UPDATE documents
            SET published_at = ?, updated_at = ?, created_at = ?
            WHERE path = ?
            """,
            (recent, recent, recent, PATH_B),
        )
        conn.commit()
        graph.invalidate_cache()
        full = graph.build_graph(conn)
        narrow = graph.build_graph(conn, hours=24)
        wide = graph.build_graph(conn, hours=24 * 365)

    assert full["meta"]["max_days"] >= 1
    assert full["meta"]["hours"] is None
    assert narrow["meta"]["hours"] == 24
    assert wide["meta"]["hours"] == 24 * 365

    full_docs = {n["id"] for n in full["nodes"] if n["type"] == "document"}
    narrow_docs = {n["id"] for n in narrow["nodes"] if n["type"] == "document"}
    wide_docs = {n["id"] for n in wide["nodes"] if n["type"] == "document"}
    assert PATH_A in full_docs
    assert PATH_A not in narrow_docs
    assert PATH_B in narrow_docs
    assert full_docs == wide_docs


def test_project_scope_includes_cross_project_neighbors(workspace: Path) -> None:
    with db.connect() as conn:
        db.init_db(conn)
        data = graph.build_graph(conn, project="synq-phalanx")

    ids = {n["id"] for n in data["nodes"] if n["type"] == "document"}
    assert PATH_A in ids
    assert PATH_TICKET in ids
    # The forge handoff is a direct neighbor of the phalanx backfill doc.
    assert PATH_B in ids
    # Unrelated commonspace doc has no edge into phalanx and must be excluded.
    assert PATH_UNRELATED not in ids


def test_min_weight_prunes_similarity_edges_only(workspace: Path) -> None:
    with db.connect() as conn:
        db.init_db(conn)
        loose = graph.build_graph(conn)
        strict = graph.build_graph(conn, min_weight=99.0)

    loose_similar = [l for l in loose["links"] if l["type"] == "similar"]
    strict_similar = [l for l in strict["links"] if l["type"] == "similar"]
    strict_explicit = [l for l in strict["links"] if l["type"] == "explicit"]

    assert len(strict_similar) <= len(loose_similar)
    assert not strict_similar
    assert strict_explicit, "explicit edges must survive min_weight"


def test_cache_invalidated_after_reindex(workspace: Path) -> None:
    with db.connect() as conn:
        db.init_db(conn)
        before = graph.build_graph(conn)

    new_doc = workspace / ".md" / "handoff" / "synq-forge" / "2026-07-05T10-00-00Z.md"
    new_doc.write_text(
        "# Handoff — 2026-07-05T10-00-00Z\n\n- **Changed:** entirely new entry\n",
        encoding="utf-8",
    )
    indexer.index_all(prune=False)

    with db.connect() as conn:
        db.init_db(conn)
        after = graph.build_graph(conn)

    before_ids = {n["id"] for n in before["nodes"]}
    after_ids = {n["id"] for n in after["nodes"]}
    assert ".md/handoff/synq-forge/2026-07-05T10-00-00Z.md" not in before_ids
    assert ".md/handoff/synq-forge/2026-07-05T10-00-00Z.md" in after_ids


def test_neighbors_by_path_ranks_explicit_first(workspace: Path) -> None:
    with db.connect() as conn:
        db.init_db(conn)
        result = graph.neighbors(conn, PATH_A, limit=5)

    assert result["mode"] == "path"
    related_paths = [r["path"] for r in result["related"]]
    assert PATH_B in related_paths
    top = result["related"][0]
    assert top["link_type"] == "explicit"


def test_neighbors_by_query_finds_prior_work(workspace: Path) -> None:
    with db.connect() as conn:
        db.init_db(conn)
        result = graph.neighbors(
            conn, "binance keystones backfill gap recovery", limit=3
        )

    assert result["mode"] == "query"
    related_paths = [r["path"] for r in result["related"]]
    assert PATH_A in related_paths or PATH_B in related_paths
    assert all("matched terms" in r["reason"] for r in result["related"])


def test_graph_static_assets_wired() -> None:
    root = Path(cxl_strata.__file__).resolve().parent
    index = (root / "static" / "index.html").read_text(encoding="utf-8")
    app_js = (root / "static" / "app.js").read_text(encoding="utf-8")
    style = (root / "static" / "style.css").read_text(encoding="utf-8")

    assert (root / "static" / "force-graph.min.js").is_file()
    assert "/static/force-graph.min.js" in index
    assert 'id="view-graph"' in index
    assert 'id="graph-canvas"' in index
    assert 'id="home-graph-btn"' in index
    assert 'id="scoped-graph-btn"' in index
    assert 'id="graph-filter-kinds"' in index
    assert 'id="graph-filter-authors"' in index
    assert 'id="graph-timeframe"' in index
    assert 'id="graph-threshold"' in index
    assert 'id="graph-highlight"' in index

    assert "async function openGraphView(project)" in app_js
    assert "async function loadGraphData()" in app_js
    assert "graphAuthorsFilter" in app_js
    assert "applyGraphTimeframeMeta" in app_js
    assert "authors" in app_js
    assert "/api/graph" in app_js
    assert "onNodeClick" in app_js
    assert "openDoc(node.id)" in app_js

    assert "#view-graph" in style
    assert ".graph-canvas" in style
    assert ".graph-legend" in style
    assert ".graph-author-dropdown" in style
