"""Localhost STRATA workspace UI (port 8765)."""

from __future__ import annotations

import json
import mimetypes
import sys
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib import request
from urllib.parse import parse_qs, urlparse

from ..content_safety import find_secret_markers
from ..documents import stash_paths
from ..local_store import load_config
from ..workspace_index import db, indexer, nl_query, paths, queries, sync_review
from ..workspace_index.text_cleanup import fix_mojibake

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
DEFAULT_PORT = 8765


def bootstrap_workspace_index(
    *,
    project: str | None = None,
    pull_shared: bool = False,
) -> dict:
    """Create and warm the local SQLite index before the UI opens."""
    stats: dict = {
        "db_path": str(paths.DB_PATH),
        "workspace_root": str(paths.WORKSPACE_ROOT),
        "index": indexer.index_all(prune=False),
    }
    if pull_shared:
        try:
            from ..pull import pull_documents

            stats["pull"] = pull_documents(project=project)
        except Exception as exc:  # noqa: BLE001 - app must open even when API is offline
            stats["pull_error"] = str(exc)
    return stats


def _json_response(handler: BaseHTTPRequestHandler, payload: object, status: int = 200) -> None:
    body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _read_json(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length", 0))
    raw = handler.rfile.read(length) if length else b"{}"
    return json.loads(raw.decode("utf-8"))


def _api_online() -> dict:
    try:
        from .. import api_client

        who = api_client.whoami()
        return {"online": True, "actor": who.get("actor"), "organization": who.get("organization")}
    except Exception as exc:  # noqa: BLE001 - UI status only
        return {"online": False, "error": str(exc)}


class StrataAppHandler(BaseHTTPRequestHandler):
    server_version = "StrataApp/1.0"

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write(
            "%s - [%s] %s\n" % (self.address_string(), self.log_date_time_string(), fmt % args)
        )

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        if path == "/api/stats":
            with db.connect() as conn:
                db.init_db(conn)
                _json_response(self, nl_query.stats(conn))
            return

        if path == "/api/projects":
            with db.connect() as conn:
                db.init_db(conn)
                _json_response(self, nl_query.list_projects(conn))
            return

        if path == "/api/projects/summary":
            with db.connect() as conn:
                db.init_db(conn)
                _json_response(self, nl_query.project_summary(conn))
            return

        if path == "/api/config":
            cfg = {}
            try:
                cfg = load_config()
            except FileNotFoundError:
                pass
            payload = {
                "api_base_url": cfg.get("api_base_url"),
                "organization": cfg.get("organization_slug"),
                **_api_online(),
            }
            _json_response(self, payload)
            return

        if path == "/api/authors":
            with db.connect() as conn:
                db.init_db(conn)
                _json_response(self, {"authors": queries.list_authors(conn)})
            return

        if path == "/api/sync/local":
            qs = parse_qs(parsed.query)
            project = (qs.get("project") or [None])[0]
            kind = (qs.get("kind") or [None])[0]
            author = (qs.get("author") or [None])[0]
            show_all = (qs.get("all") or ["0"])[0] in ("1", "true", "yes")
            rows = sync_review.scan_pending(
                project=project, kind=kind, author=author, show_all=show_all
            )
            _json_response(self, {"items": rows})
            return

        if path == "/api/sync/remote-pending":
            try:
                from ..pull import count_remote_pending

                _json_response(self, {"online": True, **count_remote_pending()})
            except FileNotFoundError as exc:
                _json_response(
                    self,
                    {"online": False, "pending": 0, "error": str(exc)},
                )
            except Exception as exc:  # noqa: BLE001
                _json_response(
                    self,
                    {"online": False, "pending": 0, "error": str(exc)},
                    HTTPStatus.BAD_GATEWAY,
                )
            return

        if path == "/api/documents/recent-local":
            qs = parse_qs(parsed.query)
            try:
                limit = int((qs.get("limit") or ["200"])[0])
            except ValueError:
                limit = 200
            try:
                hours = int((qs.get("hours") or ["168"])[0])
            except ValueError:
                hours = 168
            kind = (qs.get("kind") or [None])[0]
            author = (qs.get("author") or [None])[0]
            limit = max(1, min(limit, 500))
            hours = max(1, min(hours, 24 * 30))
            items = sync_review.scan_recent_locally_changed(
                hours=hours, limit=limit, kind=kind, author=author
            )
            _json_response(self, {"items": items, "hours": hours})
            return

        if path == "/api/doc":
            qs = parse_qs(parsed.query)
            doc_path = (qs.get("path") or [None])[0]
            if not doc_path:
                _json_response(self, {"error": "path required"}, HTTPStatus.BAD_REQUEST)
                return
            with db.connect() as conn:
                db.init_db(conn)
                doc = queries.knowledge_get(conn, doc_path)
                if not doc:
                    _json_response(self, {"error": "not found"}, HTTPStatus.NOT_FOUND)
                    return
                if doc.get("title"):
                    doc["title"] = fix_mojibake(doc["title"])
                if doc.get("body"):
                    doc["body"] = fix_mojibake(doc["body"])
                doc["source"] = doc.get("origin") or "local"
                _json_response(self, doc)
            return

        if path == "/api/documents/remote":
            qs = parse_qs(parsed.query)
            q = (qs.get("q") or [""])[0]
            project = (qs.get("project") or [None])[0]
            try:
                from .. import api_client

                if q.strip():
                    data = api_client.search_documents(q, project=project)
                else:
                    data = {"results": api_client.list_documents(project=project, limit=50)}
                _json_response(self, data)
            except Exception as exc:  # noqa: BLE001
                _json_response(self, {"error": str(exc), "results": []}, HTTPStatus.BAD_GATEWAY)
            return

        if path.startswith("/static/"):
            rel = path[len("/static/") :]
            fp = STATIC_DIR / rel
            if not fp.is_file() or STATIC_DIR not in fp.resolve().parents:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            content = fp.read_bytes()
            ctype = mimetypes.guess_type(str(fp))[0] or "application/octet-stream"
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return

        if path == "/favicon.ico":
            fp = STATIC_DIR / "icons" / "favicon.ico"
            if fp.is_file():
                content = fp.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "image/x-icon")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                return

        if path == "/manifest.json":
            fp = STATIC_DIR / "icons" / "manifest.json"
            if fp.is_file():
                content = fp.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/manifest+json; charset=utf-8")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                return

        if path == "/browserconfig.xml":
            fp = STATIC_DIR / "icons" / "browserconfig.xml"
            if fp.is_file():
                content = fp.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/xml; charset=utf-8")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                return

        if path in ("/", "/index.html"):
            index = STATIC_DIR / "index.html"
            if not index.is_file():
                self.send_error(HTTPStatus.NOT_FOUND, "Missing static/index.html")
                return
            content = index.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return

        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)

        if parsed.path == "/api/query":
            try:
                body = _read_json(self)
            except json.JSONDecodeError:
                _json_response(self, {"error": "invalid json"}, HTTPStatus.BAD_REQUEST)
                return

            q = str(body.get("q", "")).strip()
            limit = int(body.get("limit", 50))
            project = body.get("project")
            author = body.get("author")
            source = str(body.get("source", "local")).lower()
            if project is not None:
                project = str(project).strip() or None
            if author is not None:
                author = str(author).strip() or None

            local_result: dict = {"results": []}
            if source in ("local", "both"):
                with db.connect() as conn:
                    db.init_db(conn)
                    local_result = nl_query.parse_and_run(
                        conn, q, limit=limit, project=project, author=author
                    )
                for row in local_result.get("results") or []:
                    row["source"] = "local"

            if source in ("shared", "both") and q.strip():
                try:
                    from .. import api_client

                    remote = api_client.search_documents(
                        q, project=project, limit=limit, author=author
                    )
                    remote_results = remote.get("results", [])
                    for row in remote_results:
                        row["source"] = "shared"
                        row["kind"] = row.get("kind") or "document"
                    if source == "both" and local_result.get("results"):
                        merged = list(local_result["results"]) + remote_results
                        local_result["results"] = merged[:limit]
                    elif source == "shared":
                        local_result = {"intent": "search", "results": remote_results}
                except Exception:
                    local_result["remote_error"] = "offline"

            _json_response(self, local_result)
            return

        if parsed.path == "/api/sync/index":
            body = _read_json(self)
            paths = body.get("paths") or []
            stats = sync_review.index_paths([str(p) for p in paths])
            _json_response(self, stats)
            return

        if parsed.path == "/api/sync/upload":
            body = _read_json(self)
            paths = [str(p) for p in (body.get("paths") or [])]
            for rel in paths:
                with db.connect() as conn:
                    db.init_db(conn)
                    doc = queries.knowledge_get(conn, rel)
                    if doc and find_secret_markers(doc.get("body") or ""):
                        _json_response(
                            self,
                            {"error": f"secrets detected in {rel}"},
                            HTTPStatus.UNPROCESSABLE_ENTITY,
                        )
                        return
            result = stash_paths(paths)
            _json_response(self, result)
            return

        if parsed.path == "/api/pull":
            try:
                from ..pull import pull_documents

                body = _read_json(self)
                result = pull_documents(
                    project=body.get("project"),
                    kind=body.get("kind"),
                    since=body.get("since"),
                    limit=int(body.get("limit", 2000)),
                )
                _json_response(self, result)
            except Exception as exc:  # noqa: BLE001
                _json_response(self, {"error": str(exc)}, HTTPStatus.BAD_GATEWAY)
            return

        self.send_error(HTTPStatus.NOT_FOUND)


def run_app(
    *,
    host: str = "127.0.0.1",
    port: int = DEFAULT_PORT,
    open_browser: bool = False,
    project: str | None = None,
    pull_shared: bool = False,
) -> None:
    if not STATIC_DIR.is_dir():
        raise FileNotFoundError(f"Missing static dir: {STATIC_DIR}")

    bootstrap_workspace_index(project=project, pull_shared=pull_shared)

    server = ThreadingHTTPServer((host, port), StrataAppHandler)
    url = f"http://{host}:{port}"
    print(f"STRATA app listening on {url}", file=sys.stderr)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.", file=sys.stderr)
    finally:
        server.server_close()


def is_port_open(host: str, port: int) -> bool:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def is_strata_app_healthy(host: str, port: int) -> bool:
    """Return true only when the listener is the STRATA workspace app."""
    try:
        with request.urlopen(f"http://{host}:{port}/api/stats", timeout=2) as response:
            if response.status != HTTPStatus.OK:
                return False
            payload = json.loads(response.read().decode("utf-8"))
            return isinstance(payload.get("by_kind"), list)
    except Exception:  # noqa: BLE001 - health probe must be best-effort
        return False
