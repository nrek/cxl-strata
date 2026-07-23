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

from .. import client_update, cursor_rule, local_store, workspace_scaffold
from ..documents import archive_paths, archive_prefix, delete_remote_path, stash_paths
from ..local_store import load_config
from ..version import client_version
from ..workspace_index import db, graph, indexer, nl_query, paths, queries, sync_review
from ..workspace_index.text_cleanup import fix_mojibake
from . import auto_sync

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
DEFAULT_PORT = 8765


def bootstrap_workspace_index(
    *,
    project: str | None = None,
    pull_shared: bool = False,
) -> dict:
    """Create and warm the local SQLite index before the UI opens.

    Also refreshes workspace assets (scaffold + Cursor rules/hooks) so clients
    pick up new packaged assets after a client update: run_client_update()
    relaunches `strata app`, which lands here with the upgraded package.
    """
    stats: dict = {
        "db_path": str(paths.DB_PATH),
        "workspace_root": str(paths.WORKSPACE_ROOT),
        "scaffold": workspace_scaffold.ensure_workspace_layout(
            paths.WORKSPACE_ROOT, project=project
        ),
        # Detection-gated (no force): only refreshes existing Cursor workspaces,
        # and install_* never overwrite files that already exist on disk.
        "integrations": cursor_rule.install_supported_agent_integrations(
            paths.WORKSPACE_ROOT
        ),
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


def _csv_list(raw: object) -> list[str] | None:
    """Parse a CSV query/body value ('handoff,plan') into a clean list."""
    if raw is None:
        return None
    if isinstance(raw, list):
        values = [str(v).strip() for v in raw]
    else:
        values = str(raw).split(",")
    cleaned = [v.strip() for v in values if v and v.strip()]
    return cleaned or None


def _api_online() -> dict:
    try:
        from .. import api_client

        who = api_client.whoami(timeout=3.0)
        return {"online": True, "actor": who.get("actor"), "organization": who.get("organization")}
    except Exception as exc:  # noqa: BLE001 - UI status only
        return {"online": False, "error": str(exc)}


def _cursor_skill_ok(path: Path) -> bool:
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8")
    return "name: strata" in text and all(marker in text for marker in cursor_rule.REQUIRED_MARKERS)


def setup_status() -> dict:
    config_path = local_store.CONFIG_FILE
    global_config_path = local_store.USER_GLOBAL_FILE
    active_config_path = config_path if config_path.is_file() else global_config_path
    sqlite_path = paths.DB_PATH
    skill_path = paths.WORKSPACE_ROOT / cursor_rule.SKILL_DEST
    is_cursor_workspace = cursor_rule.cursor_workspace_detected(paths.WORKSPACE_ROOT)
    checks = [
        {
            "id": "config",
            "label": "STRATA config",
            "ok": config_path.is_file() or global_config_path.is_file(),
            "path": str(active_config_path),
            "fix": "strata init --api <api-url> --org <org>",
        },
        {
            "id": "api_key",
            "label": "API key",
            "ok": _api_key_available(),
            "path": "STRATA_API_KEY or .strata/secrets.json",
            "fix": "Set STRATA_API_KEY or create .strata/secrets.json with api_key.",
        },
        {
            "id": "sqlite",
            "label": "Local SQLite index",
            "ok": sqlite_path.is_file(),
            "path": str(sqlite_path),
            "fix": "strata index",
        },
    ]
    md_root = paths.WORKSPACE_ROOT / ".md"
    for sub in ("handoff", "blueprints", "reports"):
        checks.append({
            "id": f"md_{sub}",
            "label": f".md/{sub} directory",
            "ok": (md_root / sub).is_dir(),
            "path": str(md_root / sub),
            "fix": "python -m cxl_strata.cli --init",
        })
    if is_cursor_workspace:
        checks.append({
            "id": "cursor_skill",
            "label": "Cursor STRATA skill",
            "ok": _cursor_skill_ok(skill_path),
            "path": str(skill_path),
            "fix": "python -m cxl_strata.cli --init",
        })
        rules_dir = paths.WORKSPACE_ROOT / cursor_rule.RULES_DIR_DEST
        missing_rules = [
            name for name in cursor_rule.ORCHESTRATION_RULES
            if not (rules_dir / name).is_file()
        ]
        checks.append({
            "id": "orchestration_rules",
            "label": "Cursor orchestration rules",
            "ok": not missing_rules,
            "path": str(rules_dir) + (f" (missing: {', '.join(missing_rules)})" if missing_rules else ""),
            "fix": "python -m cxl_strata.cli --init",
        })
        checks.append({
            "id": "cursor_hooks",
            "label": "Cursor hooks",
            "ok": (paths.WORKSPACE_ROOT / cursor_rule.HOOKS_JSON_DEST).is_file(),
            "path": str(paths.WORKSPACE_ROOT / cursor_rule.HOOKS_JSON_DEST),
            "fix": "python -m cxl_strata.cli --init",
        })
    return {
        "ok": all(item["ok"] for item in checks),
        "workspace_root": str(paths.WORKSPACE_ROOT),
        "checks": checks,
    }


def _api_key_available() -> bool:
    try:
        local_store.load_api_key()
        return True
    except Exception:  # noqa: BLE001 - setup status only
        return False


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
                "actor_name": cfg.get("actor_name"),
                "client_version": client_version(),
                **_api_online(),
            }
            _json_response(self, payload)
            return

        if path == "/api/update/status":
            _json_response(self, client_update.update_status())
            return

        if path == "/api/setup/status":
            _json_response(self, setup_status())
            return

        if path == "/api/auto-sync":
            _json_response(self, auto_sync.get_controller().status())
            return

        if path == "/api/authors":
            with db.connect() as conn:
                db.init_db(conn)
                _json_response(
                    self,
                    {
                        "authors": queries.list_authors(conn),
                        "local_actor": queries.local_default_author(),
                    },
                )
            return

        if path == "/api/sync/local":
            qs = parse_qs(parsed.query)
            project = (qs.get("project") or [None])[0]
            kind = (qs.get("kind") or [None])[0]
            kinds = _csv_list((qs.get("kinds") or [None])[0])
            author = (qs.get("author") or [None])[0]
            show_all = (qs.get("all") or ["0"])[0] in ("1", "true", "yes")
            rows = sync_review.scan_pending(
                project=project, kind=kind, kinds=kinds, author=author, show_all=show_all
            )
            _json_response(self, {"items": rows})
            return

        if path == "/api/sync/potential-secrets":
            qs = parse_qs(parsed.query)
            kind = (qs.get("kind") or [None])[0]
            kinds = _csv_list((qs.get("kinds") or [None])[0])
            author = (qs.get("author") or [None])[0]
            try:
                limit = int((qs.get("limit") or ["500"])[0])
            except ValueError:
                limit = 500
            rows = sync_review.scan_potential_secret_files(
                kind=kind,
                kinds=kinds,
                author=author,
                limit=max(1, min(limit, 2000)),
            )
            _json_response(self, {"items": rows})
            return

        if path == "/api/index/pending":
            qs = parse_qs(parsed.query)
            project = (qs.get("project") or [None])[0]
            with db.connect() as conn:
                db.init_db(conn)
                pending = indexer.pending_paths(conn, project=project)
            _json_response(self, {"count": len(pending), "paths": pending[:100]})
            return

        if path == "/api/sync/status":
            qs = parse_qs(parsed.query)
            project = (qs.get("project") or [None])[0]
            with db.connect() as conn:
                db.init_db(conn)
                index_pending = indexer.pending_paths(conn, project=project)
            sync_items = sync_review.scan_pending(project=project)
            sync_paths = [
                item["path"] for item in sync_items if not item.get("sync_locked")
            ]
            remote: dict[str, object] = {
                "available": False,
                "count": None,
                "conflicts": 0,
            }
            try:
                from ..pull import count_remote_pending

                remote_pending = count_remote_pending(project=project)
                # Divergent local/remote revisions are auto-catalogued on pull
                # (stem_N siblings); outbound sync is no longer blocked.
                remote = {
                    "available": True,
                    "count": remote_pending["pending"],
                    "conflicts": 0,
                    "conflict_paths": [],
                    "total_remote": remote_pending["total_remote"],
                }
            except Exception as exc:  # noqa: BLE001
                remote["error"] = str(exc)
            _json_response(
                self,
                {
                    "project": project,
                    "index": {
                        "available": True,
                        "count": len(index_pending),
                        "paths": index_pending,
                    },
                    "sync": {
                        "available": True,
                        "count": len(sync_paths),
                        "paths": sync_paths,
                    },
                    "pull": remote,
                },
            )
            return

        if path == "/api/sync/remote-pending":
            qs = parse_qs(parsed.query)
            project = (qs.get("project") or [None])[0]
            try:
                from ..pull import count_remote_pending

                _json_response(
                    self,
                    {"online": True, **count_remote_pending(project=project)},
                )
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
                limit = int((qs.get("limit") or ["500"])[0])
            except ValueError:
                limit = 500
            try:
                hours = int((qs.get("hours") or ["168"])[0])
            except ValueError:
                hours = 168
            kind = (qs.get("kind") or [None])[0]
            kinds = _csv_list((qs.get("kinds") or [None])[0])
            author = (qs.get("author") or [None])[0]
            project = (qs.get("project") or [None])[0]
            limit = max(1, min(limit, 2000))
            hours = max(1, min(hours, 24 * 30))
            with db.connect() as conn:
                db.init_db(conn)
                items = queries.list_recent_local_documents(
                    conn,
                    hours=hours,
                    limit=limit,
                    kind=kind,
                    kinds=kinds,
                    author=author,
                    project=project,
                )
            _json_response(self, {"items": items, "hours": hours})
            return

        if path == "/api/documents/shared-from-team":
            qs = parse_qs(parsed.query)
            try:
                limit = int((qs.get("limit") or ["500"])[0])
            except ValueError:
                limit = 500
            kind = (qs.get("kind") or [None])[0]
            kinds = _csv_list((qs.get("kinds") or [None])[0])
            author = (qs.get("author") or [None])[0]
            project = (qs.get("project") or [None])[0]
            limit = max(1, min(limit, 2000))
            local_actor = queries.resolve_local_actor()
            if not local_actor:
                api_status = _api_online()
                if api_status.get("online"):
                    local_actor = api_status.get("actor")
            with db.connect() as conn:
                db.init_db(conn)
                items = queries.list_shared_from_team_documents(
                    conn,
                    limit=limit,
                    kind=kind,
                    kinds=kinds,
                    author=author,
                    local_actor=local_actor,
                    project=project,
                )
            _json_response(self, {"items": items})
            return

        if path == "/api/documents/comments":
            qs = parse_qs(parsed.query)
            doc_path = (qs.get("path") or [None])[0]
            if not doc_path:
                _json_response(self, {"error": "path required"}, HTTPStatus.BAD_REQUEST)
                return
            with db.connect() as conn:
                db.init_db(conn)
                comments = db.list_comments(conn, doc_path)
            _json_response(self, {"items": comments})
            return

        if path == "/api/graph":
            qs = parse_qs(parsed.query)
            project = (qs.get("project") or [None])[0]
            kinds = _csv_list((qs.get("kinds") or [None])[0])
            authors = _csv_list((qs.get("authors") or [None])[0])
            hours_raw = (qs.get("hours") or [None])[0]
            hours: int | None = None
            if hours_raw:
                try:
                    hours = max(0, min(int(hours_raw), 24 * 365))
                except ValueError:
                    hours = None
            min_weight_raw = (qs.get("min_weight") or [None])[0]
            min_weight: float | None = None
            if min_weight_raw:
                try:
                    min_weight = max(0.0, float(min_weight_raw))
                except ValueError:
                    min_weight = None
            with db.connect() as conn:
                db.init_db(conn)
                payload = graph.build_graph(
                    conn,
                    project=project or None,
                    kinds=kinds,
                    hours=hours,
                    authors=authors,
                    min_weight=min_weight,
                )
            _json_response(self, payload)
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
                doc["comments"] = db.list_comments(conn, doc_path)
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

        if parsed.path == "/api/auto-sync":
            try:
                body = _read_json(self)
            except json.JSONDecodeError:
                _json_response(self, {"error": "invalid json"}, HTTPStatus.BAD_REQUEST)
                return
            enabled = body.get("enabled")
            if enabled is None:
                _json_response(self, {"error": "enabled required"}, HTTPStatus.BAD_REQUEST)
                return
            run_now = body.get("run_now")
            if run_now is None:
                run_now = True
            status = auto_sync.get_controller().set_enabled(
                bool(enabled), run_now=bool(run_now)
            )
            _json_response(self, status)
            return

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
            kinds = _csv_list(body.get("kinds"))
            all_time = bool(body.get("all_time"))
            hours_raw = body.get("hours")
            hours: int | None
            if all_time or hours_raw == 0:
                hours = 0
            elif hours_raw is None:
                hours = None
            else:
                try:
                    hours = int(hours_raw)
                except (TypeError, ValueError):
                    hours = None
            source = str(body.get("source", "local")).lower()
            if project is not None:
                project = str(project).strip() or None
            if author is not None:
                author = str(author).strip() or None

            # Project library browse can return many rows; cap to protect the UI.
            if not q and project:
                limit = max(1, min(limit, 2000))
            else:
                limit = max(1, min(limit, 500))

            local_result: dict = {"results": []}
            if source in ("local", "both"):
                with db.connect() as conn:
                    db.init_db(conn)
                    local_result = nl_query.parse_and_run(
                        conn,
                        q,
                        limit=limit,
                        project=project,
                        author=author,
                        hours=hours,
                        all_time=all_time or (not q and bool(project)),
                        kinds=kinds,
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
                    if kinds:
                        remote_results = [
                            row for row in remote_results if row.get("kind") in kinds
                        ]
                    if source == "both" and local_result.get("results"):
                        merged = list(local_result["results"]) + remote_results
                        local_result["results"] = merged[:limit]
                    elif source == "shared":
                        local_result = {"intent": "search", "results": remote_results}
                except Exception:
                    local_result["remote_error"] = "offline"

            _json_response(self, local_result)
            return

        if parsed.path == "/api/index/run":
            body = _read_json(self)
            project = body.get("project")
            with db.connect() as conn:
                db.init_db(conn)
                pending = indexer.pending_paths(conn, project=project)
            stats = indexer.index_paths(
                [(paths.WORKSPACE_ROOT / rel).resolve() for rel in pending]
            )
            stats["pending_before"] = len(pending)
            _json_response(self, stats)
            return

        if parsed.path == "/api/update/run":
            result = client_update.run_client_update()
            status = (
                HTTPStatus.OK
                if result.get("ok")
                else HTTPStatus.BAD_GATEWAY
            )
            _json_response(self, result, status)
            return

        if parsed.path == "/api/sync/index":
            body = _read_json(self)
            index_paths = body.get("paths") or []
            stats = sync_review.index_paths([str(p) for p in index_paths])
            _json_response(self, stats)
            return

        if parsed.path == "/api/sync/upload":
            body = _read_json(self)
            upload_paths = [str(p) for p in (body.get("paths") or [])]
            allow_locked = bool(body.get("allow_locked"))
            result = stash_paths(upload_paths, allow_locked=allow_locked)
            _json_response(self, result)
            return

        if parsed.path == "/api/sync/lock":
            try:
                body = _read_json(self)
            except json.JSONDecodeError:
                _json_response(self, {"error": "invalid json"}, HTTPStatus.BAD_REQUEST)
                return
            doc_path = str(body.get("path") or "").strip().replace("\\", "/")
            if not doc_path:
                _json_response(self, {"error": "path required"}, HTTPStatus.BAD_REQUEST)
                return
            locked = bool(body.get("locked"))
            with db.connect() as conn:
                db.init_db(conn)
                doc = queries.knowledge_get(conn, doc_path)
                if not doc:
                    fp = paths.WORKSPACE_ROOT / doc_path
                    if fp.is_file():
                        from ..workspace_index.indexer import index_file

                        index_file(conn, fp.resolve())
                        doc = queries.knowledge_get(conn, doc_path)
                if not doc:
                    _json_response(self, {"error": "not found"}, HTTPStatus.NOT_FOUND)
                    return
                db.set_sync_locked(conn, path=doc_path, locked=locked)
            _json_response(self, {"path": doc_path, "sync_locked": locked})
            return

        if parsed.path == "/api/sync/delete-remote":
            body = _read_json(self)
            path = str(body.get("path") or "").strip()
            if not path:
                _json_response(self, {"error": "path required"}, HTTPStatus.BAD_REQUEST)
                return
            actor_name = str(body.get("actor_name") or "").strip() or None
            try:
                result = delete_remote_path(path, actor_name=actor_name)
                status = HTTPStatus.OK if result.get("deleted") else HTTPStatus.BAD_REQUEST
                _json_response(self, result, status)
            except Exception as exc:  # noqa: BLE001
                _json_response(self, {"error": str(exc)}, HTTPStatus.BAD_GATEWAY)
            return

        if parsed.path == "/api/sync/archive":
            try:
                body = _read_json(self)
            except json.JSONDecodeError:
                _json_response(self, {"error": "invalid json"}, HTTPStatus.BAD_REQUEST)
                return
            archive_paths_in = [
                str(p).strip() for p in (body.get("paths") or []) if str(p).strip()
            ]
            prefix = str(body.get("prefix") or "").strip()
            if not archive_paths_in and not prefix:
                _json_response(
                    self, {"error": "paths or prefix required"}, HTTPStatus.BAD_REQUEST
                )
                return
            try:
                if prefix:
                    result = archive_prefix(prefix, execute=bool(body.get("execute")))
                else:
                    result = archive_paths(archive_paths_in)
                _json_response(self, result)
            except Exception as exc:  # noqa: BLE001
                _json_response(self, {"error": str(exc)}, HTTPStatus.BAD_GATEWAY)
            return

        if parsed.path == "/api/pull":
            try:
                from ..pull import pull_documents

                body = _read_json(self)
                result = pull_documents(
                    project=body.get("project"),
                    repo=body.get("repo"),
                    kind=body.get("kind"),
                    since=body.get("since"),
                    limit=(
                        int(body["limit"])
                        if body.get("limit") is not None
                        else None
                    ),
                )
                _json_response(self, result)
            except Exception as exc:  # noqa: BLE001
                _json_response(self, {"error": str(exc)}, HTTPStatus.BAD_GATEWAY)
            return

        if parsed.path == "/api/documents/comment":
            try:
                body = _read_json(self)
            except json.JSONDecodeError:
                _json_response(self, {"error": "invalid json"}, HTTPStatus.BAD_REQUEST)
                return
            doc_path = str(body.get("path") or "").strip().replace("\\", "/")
            comment_body = str(body.get("body") or "").strip()
            if not doc_path or not comment_body:
                _json_response(
                    self, {"error": "path and body required"}, HTTPStatus.BAD_REQUEST
                )
                return

            cfg = {}
            try:
                cfg = load_config()
            except FileNotFoundError:
                pass
            author_name = (
                str(body.get("author_name") or "").strip()
                or queries.resolve_local_actor()
                or None
            )
            if not author_name:
                api_status = _api_online()
                if api_status.get("online"):
                    author_name = api_status.get("actor")
            author_email = cfg.get("actor_email")

            import uuid as _uuid

            with db.connect() as conn:
                db.init_db(conn)
                doc = queries.knowledge_get(conn, doc_path)
                if not doc:
                    _json_response(self, {"error": "not found"}, HTTPStatus.NOT_FOUND)
                    return
                comment = db.add_comment(
                    conn,
                    comment_id=str(_uuid.uuid4()),
                    document_path=doc_path,
                    body=comment_body,
                    author_name=author_name,
                    author_email=author_email,
                )
                remote_id = doc.get("remote_id")
                synced = False
                if remote_id:
                    try:
                        from ..documents import push_unsynced_comments

                        errors = push_unsynced_comments(
                            conn, path=doc_path, remote_id=str(remote_id)
                        )
                        synced = not errors
                    except Exception:  # noqa: BLE001 - comment stays local when API offline
                        synced = False
                comments = db.list_comments(conn, doc_path)
            _json_response(
                self,
                {"comment": comment, "synced": synced, "items": comments},
            )
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

    auto_sync.get_controller().start()

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
        auto_sync.get_controller().stop()
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
