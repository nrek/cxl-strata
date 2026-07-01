from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from cxl_strata.app.server import bootstrap_workspace_index, is_strata_app_healthy
from cxl_strata.workspace_index import paths
from cxl_strata.workspace_index.paths import set_workspace_root


class HealthyHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        return

    def do_GET(self) -> None:
        if self.path != "/api/stats":
            self.send_response(404)
            self.end_headers()
            return
        body = json.dumps({"by_kind": []}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class BrokenHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        return

    def do_GET(self) -> None:
        self.close_connection = True


def _serve_once(handler: type[BaseHTTPRequestHandler]) -> tuple[ThreadingHTTPServer, int]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, int(server.server_address[1])


def test_app_health_accepts_strata_stats_shape() -> None:
    server, port = _serve_once(HealthyHandler)
    try:
        assert is_strata_app_healthy("127.0.0.1", port)
    finally:
        server.shutdown()
        server.server_close()


def test_app_health_rejects_stale_broken_listener() -> None:
    server, port = _serve_once(BrokenHandler)
    try:
        assert not is_strata_app_healthy("127.0.0.1", port)
    finally:
        server.shutdown()
        server.server_close()


def test_bootstrap_workspace_index_creates_sqlite_for_fresh_agent_workspace(
    tmp_path: Path,
) -> None:
    (tmp_path / "CLAUDE.md").write_text("# Claude instructions\n", encoding="utf-8")
    set_workspace_root(tmp_path)
    db_path = paths.DB_PATH
    assert not db_path.exists()

    result = bootstrap_workspace_index()

    assert db_path.exists()
    assert result["db_path"] == str(db_path)
    assert result["index"]["indexed"] == 1
