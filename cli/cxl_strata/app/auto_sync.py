"""Background auto-reconcile for the localhost STRATA app.

Runs index → (optional stash/pull) on an interval while the app process is up.
Remote stash/pull only run when an API key is configured and whoami succeeds.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any

from .. import local_store
from ..documents import stash_paths
from ..workspace_index import indexer, sync_review

DEFAULT_ENABLED = True
DEFAULT_INTERVAL_SECONDS = 15 * 60  # 15 minutes
AUTO_SYNC_KEY = "auto_sync"


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def remote_configured() -> bool:
    """True when a usable API key is available (env, secrets, or org profile)."""
    try:
        local_store.load_api_key()
        return True
    except Exception:  # noqa: BLE001 - preference / status only
        return False


def _api_online() -> dict[str, Any]:
    try:
        from .. import api_client

        who = api_client.whoami(timeout=3.0)
        return {
            "online": True,
            "actor": who.get("actor"),
            "organization": who.get("organization"),
        }
    except Exception as exc:  # noqa: BLE001 - UI / reconcile status only
        return {"online": False, "error": str(exc)}


def load_preferences() -> dict[str, Any]:
    raw = local_store.load_global_config().get(AUTO_SYNC_KEY) or {}
    if not isinstance(raw, dict):
        raw = {}
    enabled = raw.get("enabled")
    if enabled is None:
        enabled = DEFAULT_ENABLED
    try:
        interval = int(raw.get("interval_seconds") or DEFAULT_INTERVAL_SECONDS)
    except (TypeError, ValueError):
        interval = DEFAULT_INTERVAL_SECONDS
    interval = max(60, interval)
    return {
        "enabled": bool(enabled),
        "interval_seconds": interval,
    }


def save_preferences(*, enabled: bool | None = None, interval_seconds: int | None = None) -> dict[str, Any]:
    current = load_preferences()
    patch: dict[str, Any] = {}
    if enabled is not None:
        patch["enabled"] = bool(enabled)
    if interval_seconds is not None:
        patch["interval_seconds"] = max(60, int(interval_seconds))
    if patch:
        local_store.update_global_config({AUTO_SYNC_KEY: {**current, **patch}})
    return load_preferences()


def reconcile() -> dict[str, Any]:
    """Index local files; stash + pull only when remote is configured and online."""
    result: dict[str, Any] = {
        "ok": True,
        "started_at": _now_iso(),
        "finished_at": None,
        "index": None,
        "stash": None,
        "pull": None,
        "remote": {
            "configured": False,
            "online": False,
            "skipped": None,
        },
        "error": None,
    }
    try:
        result["index"] = indexer.index_all(prune=False)

        configured = remote_configured()
        result["remote"]["configured"] = configured
        if not configured:
            result["remote"]["skipped"] = "not_configured"
            result["finished_at"] = _now_iso()
            return result

        online = _api_online()
        result["remote"]["online"] = bool(online.get("online"))
        if not online.get("online"):
            result["remote"]["skipped"] = "offline"
            result["remote"]["error"] = online.get("error")
            result["finished_at"] = _now_iso()
            return result

        sync_items = sync_review.scan_pending()
        upload_paths = [
            item["path"]
            for item in sync_items
            if item.get("syncable") and not item.get("sync_locked")
        ]
        if upload_paths:
            result["stash"] = stash_paths(upload_paths)
        else:
            result["stash"] = {"synced": [], "failed": [], "skipped": [], "count": 0}

        from ..pull import pull_documents

        result["pull"] = pull_documents()
        result["finished_at"] = _now_iso()
        return result
    except Exception as exc:  # noqa: BLE001 - surface in status API
        result["ok"] = False
        result["error"] = str(exc)
        result["finished_at"] = _now_iso()
        return result


class AutoSyncController:
    """Daemon thread that runs reconcile() on an interval when enabled."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._run_lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._running = False
        self._last_result: dict[str, Any] | None = None
        self._last_started_at: str | None = None
        self._next_run_at: float | None = None

    def status(self) -> dict[str, Any]:
        prefs = load_preferences()
        with self._lock:
            next_in = None
            if self._next_run_at is not None and prefs["enabled"]:
                next_in = max(0, int(self._next_run_at - time.time()))
            return {
                "enabled": prefs["enabled"],
                "interval_seconds": prefs["interval_seconds"],
                "running": self._running,
                "thread_alive": bool(self._thread and self._thread.is_alive()),
                "remote_configured": remote_configured(),
                "last_started_at": self._last_started_at,
                "last_result": self._last_result,
                "next_run_in_seconds": next_in,
            }

    def start(self) -> None:
        prefs = load_preferences()
        with self._lock:
            if self._thread and self._thread.is_alive():
                if prefs["enabled"]:
                    self._wake.set()
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._loop,
                name="strata-auto-sync",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def set_enabled(self, enabled: bool, *, run_now: bool = True) -> dict[str, Any]:
        save_preferences(enabled=enabled)
        self.start()
        if enabled and run_now:
            self._wake.set()
        return self.status()

    def run_once(self) -> dict[str, Any]:
        if not self._run_lock.acquire(blocking=False):
            with self._lock:
                return {
                    "ok": False,
                    "skipped": "already_running",
                    "last_result": self._last_result,
                }
        try:
            with self._lock:
                self._running = True
                self._last_started_at = _now_iso()
            result = reconcile()
            with self._lock:
                self._last_result = result
                self._running = False
            return result
        finally:
            self._run_lock.release()

    def _loop(self) -> None:
        while not self._stop.is_set():
            prefs = load_preferences()
            if not prefs["enabled"]:
                with self._lock:
                    self._next_run_at = None
                self._wake.wait(timeout=30)
                self._wake.clear()
                continue

            self.run_once()
            if self._stop.is_set():
                break

            prefs = load_preferences()
            interval = prefs["interval_seconds"]
            with self._lock:
                self._next_run_at = time.time() + interval
            self._wake.wait(timeout=interval)
            self._wake.clear()


_controller: AutoSyncController | None = None
_controller_lock = threading.Lock()


def get_controller() -> AutoSyncController:
    global _controller
    with _controller_lock:
        if _controller is None:
            _controller = AutoSyncController()
        return _controller
