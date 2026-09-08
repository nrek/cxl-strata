"""Native STRATA bridge — stdio JSON-lines protocol for Scylla and other clients.

Protocol v1 (one JSON object per line):

  Request:  {"id":1,"method":"status"|"search"|"recent"|"get"|"pending_counts"|"capabilities",
             "params":{...}}
  Response: {"id":1,"ok":true,"result":{...}}
         or {"id":1,"ok":false,"error":"..."}

Scylla must not open workspace_index.sqlite directly — this bridge owns index access.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from .version import client_version
from .workspace_index import db, paths
from .workspace_index import nl_query, queries
from .workspace_index.paths import set_workspace_root

BRIDGE_VERSION = 1
METHODS = ("capabilities", "status", "search", "recent", "get", "pending_counts")


def _emit(obj: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False, default=str) + "\n")
    sys.stdout.flush()


def _ok(req_id: Any, result: Any) -> None:
    _emit({"id": req_id, "ok": True, "result": result})


def _err(req_id: Any, message: str) -> None:
    _emit({"id": req_id, "ok": False, "error": str(message)})


def _apply_workspace(params: dict[str, Any] | None) -> None:
    if not params:
        return
    root = params.get("workspace_root") or params.get("root")
    if root:
        set_workspace_root(Path(str(root)))


def handle_capabilities(_params: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "bridge_version": BRIDGE_VERSION,
        "strata_version": client_version(),
        "methods": list(METHODS),
        "transport": "stdio-jsonl",
    }


def handle_status(params: dict[str, Any] | None) -> dict[str, Any]:
    _apply_workspace(params)
    index_path = Path(paths.DB_PATH)
    exists = index_path.is_file()
    out: dict[str, Any] = {
        "index_exists": exists,
        "index_path": str(index_path),
        "workspace_root": str(paths.WORKSPACE_ROOT),
        "strata_version": client_version(),
        "bridge_version": BRIDGE_VERSION,
        "total": 0,
        "by_kind": [],
    }
    if not exists:
        return out
    with db.connect(index_path) as conn:
        stats = nl_query.stats(conn)
        by_kind = stats.get("by_kind") or []
        total = sum(int(row.get("n") or 0) for row in by_kind)
        out["by_kind"] = by_kind
        out["total"] = total
        # Prefer live paths module values (set_workspace_root may have changed them).
        out["workspace_root"] = str(paths.WORKSPACE_ROOT)
        out["index_path"] = str(paths.DB_PATH)
    return out


def handle_search(params: dict[str, Any] | None) -> dict[str, Any]:
    params = params or {}
    _apply_workspace(params)
    query = str(params.get("query") or params.get("q") or "").strip()
    if not query:
        raise ValueError("params.query is required")
    limit = int(params.get("limit") or 15)
    project = params.get("project")
    kind = params.get("kind")
    plan_status = params.get("plan_status")
    author = params.get("author")
    with db.connect() as conn:
        hits = queries.knowledge_search(
            conn,
            query=query,
            project=str(project) if project else None,
            kind=str(kind) if kind else None,
            plan_status=str(plan_status) if plan_status else None,
            author=str(author) if author else None,
            limit=limit,
        )
    # Slim payload for native clients — no raw SQL, no full bodies.
    slim = []
    for h in hits:
        slim.append(
            {
                "path": h.get("path"),
                "kind": h.get("kind"),
                "project": h.get("project"),
                "title": h.get("title"),
                "snippet": h.get("snippet"),
                "updated_at": h.get("updated_at"),
                "origin": h.get("origin"),
                "sync_status": h.get("sync_status"),
                "plan_status": h.get("plan_status"),
            }
        )
    return {"query": query, "hits": slim, "count": len(slim)}


def handle_recent(params: dict[str, Any] | None) -> dict[str, Any]:
    params = params or {}
    _apply_workspace(params)
    hours = int(params.get("hours") or 48)
    limit = int(params.get("limit") or 10)
    project = params.get("project")
    kind = params.get("kind")
    with db.connect() as conn:
        result = queries.knowledge_recent(
            conn,
            project=str(project) if project else None,
            hours=hours,
            kind=str(kind) if kind else None,
            limit=limit,
            available_handoffs=True,
        )
    if isinstance(result, dict):
        return result
    return {"items": result, "count": len(result)}


def handle_get(params: dict[str, Any] | None) -> dict[str, Any]:
    params = params or {}
    _apply_workspace(params)
    path = str(params.get("path") or "").strip()
    if not path:
        raise ValueError("params.path is required")
    with db.connect() as conn:
        doc = queries.knowledge_get(conn, path)
    if doc is None:
        raise FileNotFoundError(f"document not found: {path}")
    # Cap body size for bridge consumers; full body still available via STRATA app.
    body = doc.get("body")
    if isinstance(body, str) and len(body) > 200_000:
        doc = dict(doc)
        doc["body"] = body[:200_000]
        doc["body_truncated"] = True
    return {"document": doc}


def handle_pending_counts(params: dict[str, Any] | None) -> dict[str, Any]:
    """Local-only pending counts for a native status indicator.

    ``index_pending`` is disk-ahead-of-SQLite (Files to Strata); ``sync_pending``
    is indexed revisions awaiting an outbound transfer. No remote call is made —
    a status segment must never block on the network.
    """
    params = params or {}
    _apply_workspace(params)
    project = params.get("project")
    project = str(project) if project else None
    out: dict[str, Any] = {
        "available": False,
        "index_pending": 0,
        "sync_pending": 0,
        "total": 0,
        "project": project,
    }
    if not Path(paths.DB_PATH).is_file():
        return out

    # Pending scanning walks the workspace, so a partial answer beats an error:
    # this feeds a status line, not a sync decision.
    index_pending = 0
    sync_pending = 0
    available = False
    try:
        from .workspace_index import indexer

        with db.connect() as conn:
            db.init_db(conn)
            index_pending = len(indexer.pending_paths(conn, project=project))
        available = True
    except Exception:  # noqa: BLE001 — keep the bridge alive, report zeros
        pass
    try:
        from .workspace_index import sync_review

        rows = sync_review.scan_pending(project=project)
        sync_pending = sum(1 for r in rows if not r.get("sync_locked"))
        available = True
    except Exception:  # noqa: BLE001
        pass

    out["available"] = available
    out["index_pending"] = index_pending
    out["sync_pending"] = sync_pending
    out["total"] = index_pending + sync_pending
    return out


HANDLERS = {
    "capabilities": handle_capabilities,
    "status": handle_status,
    "search": handle_search,
    "recent": handle_recent,
    "get": handle_get,
    "pending_counts": handle_pending_counts,
}


def handle_request(msg: dict[str, Any]) -> None:
    req_id = msg.get("id")
    method = str(msg.get("method") or "").strip()
    params = msg.get("params")
    if params is not None and not isinstance(params, dict):
        _err(req_id, "params must be an object")
        return
    handler = HANDLERS.get(method)
    if not handler:
        _err(req_id, f"unknown method: {method or '(empty)'}")
        return
    try:
        result = handler(params)
        _ok(req_id, result)
    except Exception as exc:  # noqa: BLE001 — surface to client, keep bridge alive
        _err(req_id, str(exc))


def run_bridge() -> None:
    """Blocking stdio loop. One JSON request per line; one JSON response per line."""
    # Unbuffered line protocol; binary-safe text IO.
    if hasattr(sys.stdin, "reconfigure"):
        try:
            sys.stdin.reconfigure(encoding="utf-8")
            sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
        except Exception:  # noqa: BLE001
            pass

    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError as exc:
            _err(None, f"invalid json: {exc}")
            continue
        if not isinstance(msg, dict):
            _err(None, "request must be a JSON object")
            continue
        handle_request(msg)


def main() -> None:
    run_bridge()


if __name__ == "__main__":
    main()
