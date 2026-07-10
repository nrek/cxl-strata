from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from cxl_strata import cursor_rule, local_store, workspace_scaffold
from cxl_strata.app.server import (
    StrataAppHandler,
    bootstrap_workspace_index,
    is_strata_app_healthy,
    setup_status,
)
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


def test_setup_status_reports_local_requirements(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("STRATA_API_KEY", "strata_live_test")
    set_workspace_root(tmp_path)
    local_store.ensure_layout()
    local_store.CONFIG_FILE.write_text(
        json.dumps(
            {
                "api_base_url": "http://127.0.0.1:8015",
                "organization_slug": "example",
                "project_slug": "example-project",
                "repo_name": "example-repo",
            }
        ),
        encoding="utf-8",
    )
    paths.DB_PATH.parent.mkdir(parents=True)
    paths.DB_PATH.write_text("", encoding="utf-8")
    workspace_scaffold.ensure_workspace_layout(tmp_path)
    cursor_rule.install_cursor_integration()

    result = setup_status()
    checks = {item["id"]: item for item in result["checks"]}

    assert result["ok"] is True
    assert checks["config"]["ok"] is True
    assert checks["api_key"]["ok"] is True
    assert checks["sqlite"]["ok"] is True
    assert checks["md_handoff"]["ok"] is True
    assert checks["md_blueprints"]["ok"] is True
    assert checks["md_reports"]["ok"] is True
    assert checks["cursor_skill"]["ok"] is True
    assert checks["orchestration_rules"]["ok"] is True
    assert checks["cursor_hooks"]["ok"] is True


def test_setup_status_accepts_user_level_workspace_config(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("STRATA_API_KEY", "strata_live_test")
    monkeypatch.setattr(local_store, "USER_GLOBAL_FILE", tmp_path / "global.json")
    set_workspace_root(tmp_path)
    local_store.USER_GLOBAL_FILE.write_text(
        json.dumps(
            {
                "api_base_url": "https://strata.example.com",
                "organization_slug": "example-org",
            }
        ),
        encoding="utf-8",
    )
    paths.DB_PATH.parent.mkdir(parents=True)
    paths.DB_PATH.write_text("", encoding="utf-8")
    workspace_scaffold.ensure_workspace_layout(tmp_path)
    cursor_rule.install_cursor_integration()

    result = setup_status()
    checks = {item["id"]: item for item in result["checks"]}

    assert result["ok"] is True
    assert checks["config"]["ok"] is True
    assert checks["config"]["label"] == "STRATA config"
    assert checks["config"]["path"] == str(local_store.USER_GLOBAL_FILE)


def test_setup_status_checks_cursor_skill_at_workspace_root(tmp_path: Path, monkeypatch) -> None:
    app_cwd = tmp_path / "cxl-strata" / "cli"
    app_cwd.mkdir(parents=True)
    monkeypatch.chdir(app_cwd)
    monkeypatch.setenv("STRATA_API_KEY", "strata_live_test")
    monkeypatch.setattr(local_store, "USER_GLOBAL_FILE", tmp_path / "global.json")
    set_workspace_root(tmp_path)
    local_store.USER_GLOBAL_FILE.write_text(
        json.dumps(
            {
                "api_base_url": "https://strata.example.com",
                "organization_slug": "example-org",
            }
        ),
        encoding="utf-8",
    )
    paths.DB_PATH.parent.mkdir(parents=True)
    paths.DB_PATH.write_text("", encoding="utf-8")
    workspace_scaffold.ensure_workspace_layout(tmp_path)
    cursor_rule.install_cursor_integration(root=tmp_path)

    result = setup_status()
    checks = {item["id"]: item for item in result["checks"]}

    assert result["ok"] is True
    assert checks["cursor_skill"]["ok"] is True
    assert checks["cursor_skill"]["path"] == str(tmp_path / cursor_rule.SKILL_DEST)


def test_setup_status_does_not_require_cursor_skill_for_non_cursor_workspace(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("STRATA_API_KEY", "strata_live_test")
    monkeypatch.setattr(local_store, "USER_GLOBAL_FILE", tmp_path / "global.json")
    set_workspace_root(tmp_path)
    local_store.USER_GLOBAL_FILE.write_text(
        json.dumps(
            {
                "api_base_url": "https://strata.example.com",
                "organization_slug": "example-org",
            }
        ),
        encoding="utf-8",
    )
    paths.DB_PATH.parent.mkdir(parents=True)
    paths.DB_PATH.write_text("", encoding="utf-8")
    workspace_scaffold.ensure_workspace_layout(tmp_path)

    result = setup_status()
    checks = {item["id"]: item for item in result["checks"]}

    assert result["ok"] is True
    assert "cursor_skill" not in checks
    assert "orchestration_rules" not in checks
    assert "cursor_hooks" not in checks


def test_setup_status_reports_missing_items(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("STRATA_API_KEY", raising=False)
    monkeypatch.setattr(local_store, "USER_GLOBAL_FILE", tmp_path / "missing-global.json")
    monkeypatch.setattr(local_store, "USER_SECRETS_FILE", tmp_path / "missing-secrets.json")
    set_workspace_root(tmp_path)

    result = setup_status()
    checks = {item["id"]: item for item in result["checks"]}

    assert result["ok"] is False
    assert checks["config"]["ok"] is False
    assert "strata init" in checks["config"]["fix"]
    assert "--project" not in checks["config"]["fix"]
    assert "--repo" not in checks["config"]["fix"]
    assert checks["api_key"]["ok"] is False
    assert "STRATA_API_KEY" in checks["api_key"]["fix"]
    assert checks["sqlite"]["ok"] is False
    assert "strata index" in checks["sqlite"]["fix"]
    assert checks["md_handoff"]["ok"] is False
    assert checks["md_blueprints"]["ok"] is False
    assert checks["md_reports"]["ok"] is False
    assert "cursor_skill" not in checks


def test_setup_status_reports_missing_orchestration_rules(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("STRATA_API_KEY", "strata_live_test")
    monkeypatch.setattr(local_store, "USER_GLOBAL_FILE", tmp_path / "global.json")
    set_workspace_root(tmp_path)
    local_store.USER_GLOBAL_FILE.write_text(
        json.dumps({"api_base_url": "https://strata.example.com", "organization_slug": "org"}),
        encoding="utf-8",
    )
    paths.DB_PATH.parent.mkdir(parents=True)
    paths.DB_PATH.write_text("", encoding="utf-8")
    workspace_scaffold.ensure_workspace_layout(tmp_path)
    (tmp_path / ".cursor").mkdir()

    result = setup_status()
    checks = {item["id"]: item for item in result["checks"]}

    assert result["ok"] is False
    assert checks["orchestration_rules"]["ok"] is False
    assert "blueprints.mdc" in checks["orchestration_rules"]["path"]
    assert checks["cursor_hooks"]["ok"] is False


def test_potential_secrets_endpoint_returns_redacted_rows(tmp_path: Path) -> None:
    (tmp_path / ".cursor" / "plans" / "draft").mkdir(parents=True)
    (tmp_path / ".cursor" / "plans" / "draft" / "secret-plan.md").write_text(
        "# Plan\n\npassword=supersecret123\n",
        encoding="utf-8",
    )
    set_workspace_root(tmp_path)
    bootstrap_workspace_index()
    server, port = _serve_once(StrataAppHandler)
    try:
        import urllib.request

        with urllib.request.urlopen(  # noqa: S310 - local test server
            f"http://127.0.0.1:{port}/api/sync/potential-secrets",
            timeout=3,
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()

    assert len(payload["items"]) == 1
    assert payload["items"][0]["path"] == ".cursor/plans/draft/secret-plan.md"
    assert "supersecret123" not in payload["items"][0]["excerpt"]
