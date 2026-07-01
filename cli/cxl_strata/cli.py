"""STRATA CLI - local capture and central sync."""

from __future__ import annotations

import json
import os
import sysconfig
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import typer
from rich import print as rprint
from rich.prompt import Prompt

from . import api_client, cursor_rule, local_store
from .content_safety import find_secret_markers
from .workspace_cmds import register as register_workspace_cmds

app = typer.Typer(
    name="strata",
    help="STRATA - shared project memory (local capture + central API sync)",
    no_args_is_help=True,
)

org_app = typer.Typer(help="Manage named org profiles (separate API keys / installations)")
app.add_typer(org_app, name="org")


def _user_scripts_dir() -> Path:
    scripts = sysconfig.get_path("scripts", f"{os.name}_user")
    if scripts:
        return Path(scripts).expanduser()
    return Path.home() / (".local/bin" if os.name != "nt" else "AppData/Roaming/Python/Scripts")


def _prepend_current_path(path: Path) -> None:
    raw = str(path)
    parts = [p for p in os.environ.get("PATH", "").split(os.pathsep) if p]
    if raw not in parts:
        os.environ["PATH"] = raw + os.pathsep + os.environ.get("PATH", "")


def _append_managed_block(path: Path, block: str) -> bool:
    marker = "STRATA_PATH_BLOCK_BEGIN"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = path.read_text(encoding="utf-8") if path.is_file() else ""
        if marker in existing:
            return False
        with path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write("\n" + block.strip() + "\n")
        return True
    except OSError:
        return False


def _persist_path_unix(scripts_dir: Path) -> list[str]:
    block = f"""
# STRATA_PATH_BLOCK_BEGIN
# STRATA pip user bin
export PATH="{scripts_dir}:$PATH"
# STRATA_PATH_BLOCK_END
"""
    changed: list[str] = []
    for profile in (Path.home() / ".profile", Path.home() / ".bashrc", Path.home() / ".zshrc"):
        if _append_managed_block(profile, block):
            changed.append(str(profile))
    return changed


def _persist_path_windows(scripts_dir: Path) -> list[str]:
    changed: list[str] = []
    raw = str(scripts_dir)
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            "Environment",
            0,
            winreg.KEY_READ | winreg.KEY_SET_VALUE,
        ) as key:
            try:
                value, value_type = winreg.QueryValueEx(key, "Path")
            except FileNotFoundError:
                value, value_type = "", winreg.REG_EXPAND_SZ
            parts = [p for p in str(value).split(os.pathsep) if p]
            if raw not in parts:
                new_value = raw + (os.pathsep + str(value) if value else "")
                winreg.SetValueEx(key, "Path", 0, value_type, new_value)
                changed.append("HKCU\\Environment\\Path")
    except OSError:
        pass

    block = r"""
# STRATA_PATH_BLOCK_BEGIN
# STRATA pip user Scripts
$__strataScripts = python -c "import os, sysconfig; print(sysconfig.get_path('scripts', f'{os.name}_user') or '')" 2>$null
if ($__strataScripts -and (Test-Path $__strataScripts)) { $env:Path = "$__strataScripts;" + $env:Path }
# STRATA_PATH_BLOCK_END
"""
    docs = Path.home() / "Documents"
    for profile in (
        docs / "PowerShell" / "Microsoft.PowerShell_profile.ps1",
        docs / "WindowsPowerShell" / "Microsoft.PowerShell_profile.ps1",
    ):
        if _append_managed_block(profile, block):
            changed.append(str(profile))
    return changed


def harden_user_path() -> dict[str, object]:
    scripts_dir = _user_scripts_dir()
    _prepend_current_path(scripts_dir)
    changed = _persist_path_windows(scripts_dir) if os.name == "nt" else _persist_path_unix(scripts_dir)
    return {"scripts_dir": str(scripts_dir), "changed": changed}


def bootstrap_client_environment() -> None:
    """Post-install bootstrap: PATH, SQLite cache, and localhost UI."""
    path_result = harden_user_path()
    rprint(f"[green]PATH includes[/green] {path_result['scripts_dir']}")
    rule_result = cursor_rule.install_cursor_rule()
    rprint(f"[green]Cursor rule {rule_result['status']}[/green] {rule_result['path']}")

    project: str | None = None
    try:
        cfg = local_store.load_config()
        project = cfg.get("project_slug")
    except Exception:
        project = None

    from .app.server import bootstrap_workspace_index, run_app

    stats = bootstrap_workspace_index(project=project, pull_shared=True)
    rprint(f"[green]SQLite ready[/green] {stats['db_path']}")
    rprint("[green]Opening STRATA UI[/green] http://127.0.0.1:8765")
    run_app(open_browser=True, project=project, pull_shared=False)


@app.callback(invoke_without_command=True)
def main_callback(
    ctx: typer.Context,
    org: Optional[str] = typer.Option(
        None,
        "--org",
        "-org",
        help="Use a named org profile from ~/.strata/orgs/{alias}.json (default has no alias)",
    ),
    client_init: bool = typer.Option(
        False,
        "--init",
        help="Post-install bootstrap: harden PATH, initialize local SQLite, and open UI",
    ),
) -> None:
    """Global options for STRATA CLI."""
    local_store.set_active_org(org)
    if client_init:
        bootstrap_client_environment()
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        return


@org_app.command("add")
def org_add_cmd(
    alias: str = typer.Argument(..., help="Profile alias, e.g. commonspace"),
    key: str = typer.Option(..., "--key", help="API key for this org/installation"),
    org_slug: str = typer.Option(..., "--org", help="Organization slug on the target API"),
    api: Optional[str] = typer.Option(
        None,
        "--api",
        help="API base URL (defaults to ~/.strata/global.json api_base_url)",
    ),
) -> None:
    """Save a named org profile with its own API key."""
    path = local_store.save_org_profile(alias, api_key=key, org=org_slug, api_base_url=api)
    rprint(f"[green]Saved org profile[/green] {alias} -> {path}")


@org_app.command("list")
def org_list_cmd() -> None:
    """List saved org profile aliases."""
    aliases = local_store.list_org_profiles()
    if not aliases:
        rprint("[yellow]No org profiles.[/yellow] Default install uses ~/.strata/secrets.json")
        return
    for alias in aliases:
        profile = local_store.load_org_profile(alias)
        org_name = profile.get("org") or profile.get("organization_slug")
        api = profile.get("api_base_url") or "(default API)"
        rprint(f"[bold]{alias}[/bold]  org={org_name}  api={api}")


@org_app.command("remove")
def org_remove_cmd(alias: str = typer.Argument(..., help="Profile alias to delete")) -> None:
    """Remove a named org profile."""
    path = local_store.org_profile_path(alias)
    if not path.is_file():
        raise typer.BadParameter(f"Unknown org alias: {alias}")
    path.unlink()
    rprint(f"[green]Removed[/green] org profile {alias}")


@app.command("init")
def init_cmd(
    api: str = typer.Option("http://127.0.0.1:8015", "--api", help="Central API base URL"),
    org: str = typer.Option(..., "--org", help="Organization slug"),
    project: str = typer.Option(..., "--project", help="Default project slug"),
    repo: str = typer.Option(..., "--repo", help="Repo name"),
    workspace_id: Optional[str] = typer.Option(None, "--workspace-id"),
    actor_name: Optional[str] = typer.Option(None, "--actor-name"),
    actor_email: Optional[str] = typer.Option(None, "--actor-email"),
) -> None:
    """Create .strata/ config and JSONL queue files."""
    local_store.ensure_layout()
    cfg = {
        "api_base_url": api.rstrip("/"),
        "organization_slug": org,
        "project_slug": project,
        "repo_name": repo,
        "workspace_id": workspace_id or f"{org}-{repo}",
        "actor_name": actor_name,
        "actor_email": actor_email,
    }
    local_store.CONFIG_FILE.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    rule_result = cursor_rule.install_cursor_rule()
    rprint("[green]Initialized[/green] .strata/config.json")
    rprint(f"[green]Cursor rule {rule_result['status']}[/green] {rule_result['path']}")
    rprint("Set access token: export STRATA_API_KEY=strata_dev_...  or  .strata/secrets.json")


@app.command("add")
def add_cmd(
    type: str = typer.Option("general_note", "--type", "-t"),
    title: Optional[str] = typer.Option(None, "--title"),
    summary: Optional[str] = typer.Option(None, "--summary"),
    details: Optional[str] = typer.Option(None, "--details"),
    project: Optional[str] = typer.Option(None, "--project"),
    repo: Optional[str] = typer.Option(None, "--repo"),
    environment: Optional[str] = typer.Option(None, "--environment"),
    tags: Optional[str] = typer.Option(None, "--tags", help="Comma-separated"),
    visibility: str = typer.Option("internal", "--visibility"),
    confidence: str = typer.Option("observed", "--confidence"),
    handoff_path: Optional[Path] = typer.Option(
        None,
        "--handoff-path",
        help="Upload an existing handoff markdown file",
    ),
) -> None:
    """Capture a memory note or handoff locally (queue for sync)."""
    cfg = local_store.load_config()
    proj = project or cfg["project_slug"]
    rep = repo or cfg.get("repo_name")

    if handoff_path:
        text = handoff_path.read_text(encoding="utf-8")
        _reject_secrets(text)
        title = title or handoff_path.stem
        summary = summary or _first_paragraph(text)
        details = details or text[:8000]
        type = "handoff_upload"
    else:
        title = title or Prompt.ask("Title")
        summary = summary or Prompt.ask("Summary")
        if details is None:
            details = Prompt.ask("Details (optional)", default="") or None

    tag_list = [t.strip() for t in (tags or "").split(",") if t.strip()]
    event = {
        "project_slug": proj,
        "repo_name": rep,
        "event_type": type,
        "title": title,
        "summary": summary,
        "details": details,
        "environment": environment,
        "visibility": visibility,
        "confidence": confidence,
        "tags": tag_list,
        "source": "local_capture",
    }
    if handoff_path:
        event["source_ref"] = str(handoff_path)
        event["related_files"] = [str(handoff_path)]

    _reject_secrets(event)
    local_id = local_store.append_event(event)
    rprint(f"[green]Queued[/green] {local_id} - run [bold]strata sync[/bold] to push to central API")


@app.command("summary")
def summary_cmd(
    text: Optional[str] = typer.Option(None, "--text", help="Summary body (or prompt)"),
    project: Optional[str] = typer.Option(None, "--project"),
    repo: Optional[str] = typer.Option(None, "--repo"),
    title: Optional[str] = typer.Option(None, "--title"),
    sync_now: bool = typer.Option(False, "--sync", help="Sync immediately after queue"),
) -> None:
    """Upload an end-of-day or end-of-flow summary for the current project."""
    cfg = local_store.load_config()
    proj = project or cfg["project_slug"]
    rep = repo or cfg.get("repo_name")
    body = text or Prompt.ask("What did you accomplish today for this project?")
    heading = title or f"Daily summary - {proj}"

    event = {
        "project_slug": proj,
        "repo_name": rep,
        "event_type": "daily_summary",
        "title": heading,
        "summary": body.strip()[:2000],
        "details": body.strip(),
        "visibility": "internal",
        "confidence": "observed",
        "tags": ["daily-summary", proj],
        "source": "local_capture",
    }
    _reject_secrets(event)
    local_id = local_store.append_event(event)
    rprint(f"[green]Queued summary[/green] {local_id}")
    if sync_now:
        sync_cmd()


@app.command("sync")
def sync_cmd() -> None:
    """Push pending local events to the central API."""
    pending = local_store.read_pending_events()
    if not pending:
        rprint("[yellow]Nothing to sync.[/yellow]")
        return
    result = api_client.sync_batch(pending)
    synced = result.get("synced", [])
    failed = result.get("failed", [])
    pending_by_id = {event.get("local_id"): event for event in pending}
    synced_ids = {row.get("local_id") for row in synced}
    failed_ids = {row.get("local_id") for row in failed}

    for row in synced:
        event = pending_by_id.get(row.get("local_id"), {})
        local_store.mark_synced(row["local_id"], row["remote_id"], event)

    for row in failed:
        event = pending_by_id.get(row.get("local_id"), {})
        local_store.mark_failed(row.get("local_id", ""), row.get("error", "unknown error"), event)

    retry_events = [
        event
        for event in pending
        if event.get("local_id") not in synced_ids and event.get("local_id") not in failed_ids
    ]
    retry_events.extend(pending_by_id[local_id] for local_id in failed_ids if local_id in pending_by_id)
    local_store.write_pending_events(retry_events)

    rprint(f"[green]Synced {len(synced)}[/green] memory events. {len(failed)} failed.")
    if failed:
        rprint(failed)


@app.command("search")
def search_cmd(
    query: str = typer.Argument(..., help="Search query"),
    project: Optional[str] = typer.Option(None, "--project"),
) -> None:
    """Search central project memory."""
    cfg = local_store.load_config()
    proj = project or cfg.get("project_slug")
    data = api_client.search(query, project=proj)
    for row in data.get("results", []):
        rprint(f"[bold]{row.get('title')}[/bold] ({row.get('event_type')})")
        rprint(f"  {row.get('summary', '')[:200]}")


@app.command("recent")
def recent_cmd(days: int = typer.Option(7, "--days")) -> None:
    """Show recent memory for the current project (local API list)."""
    cfg = local_store.load_config()
    with api_client._client() as client:  # noqa: SLF001 - v0 helper
        r = client.get("/v1/memory-events", params={"project": cfg["project_slug"]})
        r.raise_for_status()
        data = r.json()
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = [row for row in data.get("results", []) if _created_after(row, cutoff)]
    for row in rows[:20]:
        rprint(f"[bold]{row.get('title')}[/bold] - {row.get('created_at', '')}")


@app.command("whoami")
def whoami_cmd() -> None:
    """Verify access token and actor identity."""
    data = api_client.whoami()
    cfg = local_store.load_config()
    alias = local_store.get_active_org()
    if alias:
        rprint(f"Org profile: {alias}")
    rprint(f"Actor: {cfg.get('actor_name') or data.get('actor')}")
    rprint(f"Organization: {cfg.get('organization_slug') or data.get('organization')}")
    rprint(f"Scopes: {', '.join(data.get('scopes', []))}")
    rprint(f"API: {cfg.get('api_base_url')}")


def _first_paragraph(text: str) -> str:
    for block in text.split("\n\n"):
        line = block.strip().lstrip("#").strip()
        if line and not line.startswith("---"):
            return line[:500]
    return text.strip()[:500]


def _reject_secrets(value: object) -> None:
    if find_secret_markers(value):
        raise typer.BadParameter(
            "Content appears to contain secrets. Redact credentials before queuing STRATA memory."
        )


def _created_after(row: dict, cutoff: datetime) -> bool:
    raw = str(row.get("created_at") or "")
    if not raw:
        return True
    try:
        created = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return True
    return created >= cutoff


register_workspace_cmds(app)


if __name__ == "__main__":
    app()
