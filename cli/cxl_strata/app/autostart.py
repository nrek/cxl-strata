"""Opt-in OS autostart for STRATA localhost app."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


def _strata_executable() -> str:
    exe = shutil.which("strata")
    if exe:
        return exe
    return f"{sys.executable} -m cxl_strata.cli"


def _launch_command(*, background: bool) -> str:
    base = _strata_executable()
    if " " in base and not base.startswith('"'):
        base = f'"{base}"'
    flags = " app --daemon"
    if not background:
        flags += " --open"
    if base.endswith("cxl_strata.cli"):
        return f"{base}{flags.replace(' app', ' app')}"
    return f"{base} app --daemon" + ("" if background else " --open")


def install_autostart(*, background: bool = False, open_browser: bool = False) -> Path:
    bg = background and not open_browser
    system = platform.system().lower()
    cmd = _launch_command(background=bg)

    if system == "windows":
        startup = (
            Path(os.environ.get("APPDATA", ""))
            / "Microsoft"
            / "Windows"
            / "Start Menu"
            / "Programs"
            / "Startup"
        )
        startup.mkdir(parents=True, exist_ok=True)
        shortcut = startup / "STRATA App.bat"
        shortcut.write_text(f"@echo off\r\n{cmd}\r\n", encoding="utf-8")
        return shortcut

    if system == "darwin":
        agents = Path.home() / "Library" / "LaunchAgents"
        agents.mkdir(parents=True, exist_ok=True)
        plist = agents / "com.craftxlogic.strata-app.plist"
        parts = cmd.split()
        plist.write_text(
            f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.craftxlogic.strata-app</string>
  <key>ProgramArguments</key>
  <array>{''.join(f'<string>{p}</string>' for p in parts)}</array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><false/>
</dict>
</plist>
""",
            encoding="utf-8",
        )
        subprocess.run(["launchctl", "load", str(plist)], check=False)
        return plist

    # Linux — systemd user service
    unit_dir = Path.home() / ".config" / "systemd" / "user"
    unit_dir.mkdir(parents=True, exist_ok=True)
    unit = unit_dir / "strata-app.service"
    unit.write_text(
        f"""[Unit]
Description=STRATA workspace app (localhost)
After=network.target

[Service]
Type=simple
ExecStart={cmd.replace(' app --daemon', ' app --daemon')}
Restart=on-failure

[Install]
WantedBy=default.target
""",
        encoding="utf-8",
    )
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
    subprocess.run(["systemctl", "--user", "enable", "strata-app.service"], check=False)
    return unit


def uninstall_autostart() -> list[Path]:
    removed: list[Path] = []
    system = platform.system().lower()

    if system == "windows":
        shortcut = (
            Path(os.environ.get("APPDATA", ""))
            / "Microsoft"
            / "Windows"
            / "Start Menu"
            / "Programs"
            / "Startup"
            / "STRATA App.bat"
        )
        if shortcut.is_file():
            shortcut.unlink()
            removed.append(shortcut)
        return removed

    if system == "darwin":
        plist = Path.home() / "Library" / "LaunchAgents" / "com.craftxlogic.strata-app.plist"
        if plist.is_file():
            subprocess.run(["launchctl", "unload", str(plist)], check=False)
            plist.unlink()
            removed.append(plist)
        return removed

    unit = Path.home() / ".config" / "systemd" / "user" / "strata-app.service"
    if unit.is_file():
        subprocess.run(["systemctl", "--user", "disable", "strata-app.service"], check=False)
        unit.unlink()
        removed.append(unit)
    return removed


def autostart_status() -> dict:
    system = platform.system().lower()
    if system == "windows":
        shortcut = (
            Path(os.environ.get("APPDATA", ""))
            / "Microsoft"
            / "Windows"
            / "Start Menu"
            / "Programs"
            / "Startup"
            / "STRATA App.bat"
        )
        return {"installed": shortcut.is_file(), "path": str(shortcut), "platform": system}
    if system == "darwin":
        plist = Path.home() / "Library" / "LaunchAgents" / "com.craftxlogic.strata-app.plist"
        return {"installed": plist.is_file(), "path": str(plist), "platform": system}
    unit = Path.home() / ".config" / "systemd" / "user" / "strata-app.service"
    return {"installed": unit.is_file(), "path": str(unit), "platform": system}
