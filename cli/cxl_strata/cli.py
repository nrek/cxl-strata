"""STRATA CLI - local capture and central sync."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import typer
from rich import print as rprint
from rich.prompt import Prompt

from . import api_client, local_store
from .content_safety import find_secret_markers
from .workspace_cmds import register as register_workspace_cmds

app = typer.Typer(
    name="strata",
    help="STRATA - shared project memory (local capture + central API sync)",
    no_args_is_help=True,
)


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
    rprint("[green]Initialized[/green] .strata/config.json")
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
