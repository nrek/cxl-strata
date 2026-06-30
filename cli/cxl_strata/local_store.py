"""Local .strata config and JSONL queue."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STRATA_DIR = Path(".strata")
CONFIG_FILE = STRATA_DIR / "config.json"
SECRETS_FILE = STRATA_DIR / "secrets.json"
EVENTS_FILE = STRATA_DIR / "events.jsonl"
SYNCED_FILE = STRATA_DIR / "synced.jsonl"
FAILED_FILE = STRATA_DIR / "failed.jsonl"


def ensure_layout() -> None:
    STRATA_DIR.mkdir(exist_ok=True)
    for fp in (EVENTS_FILE, SYNCED_FILE, FAILED_FILE):
        fp.touch(exist_ok=True)


def load_config() -> dict[str, Any]:
    if not CONFIG_FILE.is_file():
        raise FileNotFoundError("Missing .strata/config.json - run: strata init")
    return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))


def load_api_key() -> str:
    import os

    env = os.environ.get("STRATA_API_KEY", "").strip()
    if env:
        return env
    if SECRETS_FILE.is_file():
        data = json.loads(SECRETS_FILE.read_text(encoding="utf-8"))
        key = str(data.get("api_key", "")).strip()
        if key:
            return key
    raise RuntimeError("Set STRATA_API_KEY or create .strata/secrets.json with api_key")


def append_event(event: dict[str, Any]) -> str:
    ensure_layout()
    local_id = event.get("local_id") or _new_local_id()
    event = {**event, "local_id": local_id, "queued_at": _now_iso()}
    with EVENTS_FILE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")
    return local_id


def read_pending_events() -> list[dict[str, Any]]:
    if not EVENTS_FILE.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in EVENTS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def write_pending_events(events: list[dict[str, Any]]) -> None:
    ensure_layout()
    with EVENTS_FILE.open("w", encoding="utf-8") as fh:
        for event in events:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")


def mark_synced(local_id: str, remote_id: str, event: dict[str, Any]) -> None:
    ensure_layout()
    with SYNCED_FILE.open("a", encoding="utf-8") as fh:
        fh.write(
            json.dumps(
                {"local_id": local_id, "remote_id": remote_id, **event},
                ensure_ascii=False,
            )
            + "\n"
        )


def mark_failed(local_id: str, error: str, event: dict[str, Any]) -> None:
    ensure_layout()
    with FAILED_FILE.open("a", encoding="utf-8") as fh:
        fh.write(
            json.dumps(
                {"local_id": local_id, "error": error, **event},
                ensure_ascii=False,
            )
            + "\n"
        )


def _new_local_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"evt_{ts}_{uuid.uuid4().hex[:8]}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
