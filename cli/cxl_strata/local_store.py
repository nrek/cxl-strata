"""Local .strata config and JSONL queue."""

from __future__ import annotations

import contextvars
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_active_org_alias: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "active_org_alias", default=None
)

STRATA_DIR = Path(".strata")
CONFIG_FILE = STRATA_DIR / "config.json"
SECRETS_FILE = STRATA_DIR / "secrets.json"
EVENTS_FILE = STRATA_DIR / "events.jsonl"
SYNCED_FILE = STRATA_DIR / "synced.jsonl"
FAILED_FILE = STRATA_DIR / "failed.jsonl"

USER_STRATA_DIR = Path.home() / ".strata"
USER_GLOBAL_FILE = USER_STRATA_DIR / "global.json"
USER_SECRETS_FILE = USER_STRATA_DIR / "secrets.json"


def _orgs_dir() -> Path:
    return USER_STRATA_DIR / "orgs"


def set_active_org(alias: str | None) -> None:
    """Select a named org profile for this CLI invocation (default has no alias)."""
    _active_org_alias.set(alias.strip() if alias else None)


def get_active_org() -> str | None:
    return _active_org_alias.get()


def org_profile_path(alias: str) -> Path:
    safe = alias.strip().replace("\\", "").replace("/", "")
    if not safe or safe != alias.strip():
        raise ValueError(f"Invalid org alias: {alias!r}")
    return _orgs_dir() / f"{safe}.json"


def save_org_profile(
    alias: str,
    *,
    api_key: str,
    org: str,
    api_base_url: str | None = None,
) -> Path:
    _orgs_dir().mkdir(parents=True, exist_ok=True)
    payload: dict[str, str] = {
        "api_key": api_key.strip(),
        "org": org.strip(),
    }
    if api_base_url:
        payload["api_base_url"] = api_base_url.rstrip("/")
    path = org_profile_path(alias)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def load_org_profile(alias: str) -> dict[str, Any]:
    path = org_profile_path(alias)
    if not path.is_file():
        raise FileNotFoundError(alias)
    return _read_json(path)


def list_org_profiles() -> list[str]:
    orgs_dir = _orgs_dir()
    if not orgs_dir.is_dir():
        return []
    return sorted(p.stem for p in orgs_dir.glob("*.json") if p.is_file())


def _profile_to_config(profile: dict[str, Any]) -> dict[str, Any]:
    base = load_global_config() if USER_GLOBAL_FILE.is_file() else {}
    org_slug = profile.get("org") or profile.get("organization_slug")
    merged: dict[str, Any] = {
        "organization_slug": org_slug,
        "org_profile": org_slug,
        "api_base_url": (
            profile.get("api_base_url")
            or base.get("api_base_url")
            or "http://127.0.0.1:8015"
        ),
    }
    for key in ("project_slug", "repo_name", "workspace_id", "actor_name", "actor_email"):
        if profile.get(key) is not None:
            merged[key] = profile[key]
    if CONFIG_FILE.is_file():
        repo_cfg = _read_json(CONFIG_FILE)
        merged.setdefault("project_slug", repo_cfg.get("project_slug"))
        merged.setdefault("repo_name", repo_cfg.get("repo_name"))
        merged.setdefault("workspace_id", repo_cfg.get("workspace_id"))
    return merged


def _read_json(path: Path) -> dict[str, Any]:
    """Load JSON written by editors or PowerShell (utf-8-sig strips optional BOM)."""
    return json.loads(path.read_text(encoding="utf-8-sig"))


def ensure_layout() -> None:
    STRATA_DIR.mkdir(exist_ok=True)
    for fp in (EVENTS_FILE, SYNCED_FILE, FAILED_FILE):
        fp.touch(exist_ok=True)


def load_global_config() -> dict[str, Any]:
    if USER_GLOBAL_FILE.is_file():
        return _read_json(USER_GLOBAL_FILE)
    return {}


def update_global_config(updates: dict[str, Any]) -> dict[str, Any]:
    """Merge keys into ~/.strata/global.json (nested dicts shallow-merged)."""
    USER_STRATA_DIR.mkdir(parents=True, exist_ok=True)
    data = load_global_config()
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(data.get(key), dict):
            data[key] = {**data[key], **value}
        else:
            data[key] = value
    USER_GLOBAL_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return data


def load_config() -> dict[str, Any]:
    alias = get_active_org()
    if alias:
        try:
            profile = load_org_profile(alias)
        except FileNotFoundError as exc:
            known = ", ".join(list_org_profiles()) or "(none)"
            raise RuntimeError(
                f"Unknown org alias '{alias}'. Known aliases: {known}. "
                f"Add one with: strata org add {alias} --key ... --org ORG_SLUG"
            ) from exc
        return _profile_to_config(profile)

    if CONFIG_FILE.is_file():
        return _read_json(CONFIG_FILE)
    global_cfg = load_global_config()
    if global_cfg:
        return global_cfg
    raise FileNotFoundError(
        "Missing .strata/config.json — run: strata init "
        "(or curl bootstrap: curl -fsSL YOUR_API/install.sh | bash -s -- --init)"
    )


def load_api_key() -> str:
    alias = get_active_org()
    if alias:
        try:
            profile = load_org_profile(alias)
        except FileNotFoundError as exc:
            known = ", ".join(list_org_profiles()) or "(none)"
            raise RuntimeError(
                f"Unknown org alias '{alias}'. Known aliases: {known}."
            ) from exc
        key = str(profile.get("api_key", "")).strip()
        if key and not key.startswith("REPLACE_WITH"):
            return key
        raise RuntimeError(
            f"Org alias '{alias}' is missing api_key in {org_profile_path(alias)}"
        )

    env = os.environ.get("STRATA_API_KEY", "").strip()
    if env:
        return env
    if SECRETS_FILE.is_file():
        data = _read_json(SECRETS_FILE)
        key = str(data.get("api_key", "")).strip()
        if key and not key.startswith("REPLACE_WITH"):
            return key
    if USER_SECRETS_FILE.is_file():
        data = _read_json(USER_SECRETS_FILE)
        key = str(data.get("api_key", "")).strip()
        if key and not key.startswith("REPLACE_WITH"):
            return key
    raise RuntimeError(
        "Set STRATA_API_KEY or create ~/.strata/secrets.json (or .strata/secrets.json) with api_key"
    )


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
