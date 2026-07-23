from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from cxl_strata.app import auto_sync
from cxl_strata.app.server import StrataAppHandler
from cxl_strata import local_store
from cxl_strata.workspace_index.paths import set_workspace_root


def _serve_once(handler: type[BaseHTTPRequestHandler]) -> tuple[ThreadingHTTPServer, int]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, int(server.server_address[1])


def test_auto_sync_preferences_default_enabled(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(local_store, "USER_GLOBAL_FILE", tmp_path / "global.json")
    monkeypatch.setattr(local_store, "USER_STRATA_DIR", tmp_path)
    prefs = auto_sync.load_preferences()
    assert prefs["enabled"] is True
    assert prefs["interval_seconds"] == 15 * 60


def test_auto_sync_preferences_persist(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(local_store, "USER_GLOBAL_FILE", tmp_path / "global.json")
    monkeypatch.setattr(local_store, "USER_STRATA_DIR", tmp_path)
    local_store.USER_GLOBAL_FILE.write_text(
        json.dumps({"api_base_url": "https://strata.example.com"}),
        encoding="utf-8",
    )
    saved = auto_sync.save_preferences(enabled=False, interval_seconds=120)
    assert saved["enabled"] is False
    assert saved["interval_seconds"] == 120
    data = json.loads(local_store.USER_GLOBAL_FILE.read_text(encoding="utf-8"))
    assert data["api_base_url"] == "https://strata.example.com"
    assert data["auto_sync"]["enabled"] is False


def test_reconcile_skips_remote_when_not_configured(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("STRATA_API_KEY", raising=False)
    monkeypatch.setattr(local_store, "USER_SECRETS_FILE", tmp_path / "missing-secrets.json")
    monkeypatch.setattr(local_store, "USER_GLOBAL_FILE", tmp_path / "missing-global.json")
    set_workspace_root(tmp_path)
    (tmp_path / ".md" / "handoff" / "demo").mkdir(parents=True)
    (tmp_path / ".md" / "handoff" / "demo" / "2026-07-23T12-00-00Z.md").write_text(
        "# Handoff\n", encoding="utf-8"
    )

    result = auto_sync.reconcile()

    assert result["ok"] is True
    assert result["index"]["indexed"] >= 1
    assert result["remote"]["configured"] is False
    assert result["remote"]["skipped"] == "not_configured"
    assert result["stash"] is None
    assert result["pull"] is None


def test_auto_sync_api_get_and_post(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(local_store, "USER_GLOBAL_FILE", tmp_path / "global.json")
    monkeypatch.setattr(local_store, "USER_STRATA_DIR", tmp_path)
    set_workspace_root(tmp_path)
    # Reset singleton between tests
    auto_sync._controller = None  # noqa: SLF001

    server, port = _serve_once(StrataAppHandler)
    try:
        import urllib.request

        with urllib.request.urlopen(  # noqa: S310
            f"http://127.0.0.1:{port}/api/auto-sync", timeout=3
        ) as response:
            status = json.loads(response.read().decode("utf-8"))
        assert status["enabled"] is True
        assert status["interval_seconds"] == 900

        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/auto-sync",
            data=json.dumps({"enabled": False, "run_now": False}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=3) as response:  # noqa: S310
            updated = json.loads(response.read().decode("utf-8"))
        assert updated["enabled"] is False
    finally:
        auto_sync.get_controller().stop()
        auto_sync._controller = None  # noqa: SLF001
        server.shutdown()
        server.server_close()
