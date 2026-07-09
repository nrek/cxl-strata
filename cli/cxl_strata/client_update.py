"""Compare local client version to remote manifest and run the install script."""

from __future__ import annotations

import os
import platform
import subprocess
import sys
import threading
import time
from typing import Any
from urllib.parse import urlparse

import httpx

from .local_store import load_config
from .version import client_version


def _version_tuple(value: str) -> tuple[int, ...]:
    parts: list[int] = []
    for chunk in str(value or "").strip().split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts) if parts else (0,)


def is_remote_newer(local: str, remote: str) -> bool:
    """True when remote version is strictly newer than local (semver-ish)."""
    if not remote or not local:
        return False
    if remote == local:
        return False
    return _version_tuple(remote) > _version_tuple(local)


def _api_base() -> str:
    try:
        cfg = load_config()
    except FileNotFoundError:
        return ""
    return str(cfg.get("api_base_url") or "").rstrip("/")


def _org_slug() -> str:
    try:
        cfg = load_config()
    except FileNotFoundError:
        return ""
    return str(cfg.get("organization_slug") or "").strip()


def fetch_remote_manifest(*, timeout: float = 5.0) -> dict[str, Any] | None:
    base = _api_base()
    if not base:
        return None
    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.get(f"{base}/v1/client/manifest")
            r.raise_for_status()
            data = r.json()
            return data if isinstance(data, dict) else None
    except Exception:  # noqa: BLE001 - offline / unreachable is a normal state
        return None


def update_status(*, timeout: float = 5.0) -> dict[str, Any]:
    """Return local/remote versions and whether an update CTA should show."""
    local = client_version()
    base = _api_base()
    out: dict[str, Any] = {
        "local_version": local,
        "remote_version": None,
        "update_available": False,
        "online": False,
        "api_base_url": base or None,
        "platform": "windows" if platform.system().lower().startswith("win") else "unix",
    }
    if not base:
        return out

    manifest = fetch_remote_manifest(timeout=timeout)
    if not manifest:
        return out

    remote = str(manifest.get("version") or "").strip()
    out["online"] = True
    out["remote_version"] = remote or None
    out["update_available"] = is_remote_newer(local, remote)
    install = manifest.get("install") if isinstance(manifest.get("install"), dict) else {}
    out["install"] = {
        "unix_update": install.get("unix_update") or install.get("unix_one_liner"),
        "windows_update": install.get("windows_update") or install.get("windows_one_liner"),
    }
    return out


def _is_safe_api_base(base: str) -> bool:
    try:
        parsed = urlparse(base)
    except Exception:  # noqa: BLE001
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    if not parsed.netloc:
        return False
    return True


def run_client_update(*, timeout: float = 600.0) -> dict[str, Any]:
    """Download and execute the remote install script (package upgrade only)."""
    status = update_status()
    base = status.get("api_base_url") or ""
    if not base or not _is_safe_api_base(base):
        return {
            "ok": False,
            "error": "API base URL is not configured or invalid.",
            **status,
        }
    if not status.get("online"):
        return {
            "ok": False,
            "error": "Remote API is offline; cannot fetch the update script.",
            **status,
        }

    org = _org_slug()
    is_windows = platform.system().lower().startswith("win")

    if is_windows:
        # Re-run the same installer the team already uses; omit -Init so we
        # only upgrade packages and keep existing ~/.strata config.
        org_arg = f" -Org {org}" if org else ""
        command = (
            f'& ([scriptblock]::Create((irm {base}/install.ps1))){org_arg}'
        )
        argv = [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            command,
        ]
    else:
        org_flag = f" -s -- --org {org}" if org else ""
        command = f'curl -fsSL {base}/install.sh | bash{org_flag}'
        argv = ["bash", "-lc", command]

    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "error": f"Update timed out after {int(timeout)}s.",
            "command": " ".join(argv),
            **status,
        }
    except FileNotFoundError as exc:
        return {
            "ok": False,
            "error": f"Required shell not found: {exc}",
            "command": " ".join(argv),
            **status,
        }

    stdout = (completed.stdout or "")[-8000:]
    stderr = (completed.stderr or "")[-4000:]
    ok = completed.returncode == 0
    if ok:
        schedule_app_restart()
    return {
        "ok": ok,
        "returncode": completed.returncode,
        "command": " ".join(argv),
        "stdout": stdout,
        "stderr": stderr,
        "error": None if ok else (stderr.strip() or f"Update exited with code {completed.returncode}"),
        "python": sys.executable,
        "local_version_before": status.get("local_version"),
        "remote_version": status.get("remote_version"),
        "restart_required": ok,
    }


def schedule_app_restart(*, delay_s: float = 1.25) -> None:
    """Spawn a fresh `strata app` and exit this process after the HTTP response."""
    try:
        from .workspace_index.paths import WORKSPACE_ROOT

        root = str(WORKSPACE_ROOT)
    except Exception:  # noqa: BLE001
        root = os.environ.get("STRATA_WORKSPACE_ROOT") or os.getcwd()

    def _restart() -> None:
        time.sleep(delay_s)
        try:
            subprocess.Popen(  # noqa: S603 - intentional self-relaunch
                [
                    sys.executable,
                    "-m",
                    "cxl_strata.cli",
                    "app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "8765",
                    "--root",
                    root,
                    "--open",
                ],
                cwd=root,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except Exception:  # noqa: BLE001 - best-effort relaunch
            pass
        # Hard-exit so the old listener releases port 8765.
        os._exit(0)

    threading.Thread(target=_restart, daemon=True).start()
