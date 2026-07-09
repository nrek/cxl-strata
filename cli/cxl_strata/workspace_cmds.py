"""Extended STRATA CLI commands for workspace knowledge."""

from __future__ import annotations

import json
import subprocess
import sys
import webbrowser
from pathlib import Path
from typing import Optional

import typer
from rich import print as rprint

from . import documents, pull
from .app import (
    DEFAULT_PORT,
    autostart_status,
    bootstrap_workspace_index,
    install_autostart,
    is_port_open,
    is_strata_app_healthy,
    run_app,
    uninstall_autostart,
)
from .workspace_index import indexer, paths, prune
from .workspace_index.paths import set_workspace_root

app_typer = typer.Typer(help="Local workspace UI on port 8765")


@app_typer.callback(invoke_without_command=True)
def app_main(
    ctx: typer.Context,
    port: int = typer.Option(DEFAULT_PORT, "--port"),
    host: str = typer.Option("127.0.0.1", "--host"),
    open_browser: bool = typer.Option(False, "--open"),
    daemon: bool = typer.Option(False, "--daemon"),
    root: Optional[Path] = typer.Option(None, "--root", help="Workspace root override"),
    project: Optional[str] = typer.Option(None, "--project"),
    path: Optional[str] = typer.Option(None, "--path", help="Stash artifact then open app"),
) -> None:
    """Run STRATA localhost app."""
    if ctx.invoked_subcommand is not None:
        return
    if root:
        set_workspace_root(root)
    if path:
        documents.stash_paths([path])
    bootstrap_workspace_index(project=project, pull_shared=bool(project))
    url = f"http://{host}:{port}"
    if is_port_open(host, port):
        if is_strata_app_healthy(host, port):
            rprint(f"[green]STRATA app already listening[/green] on {url}")
            if open_browser:
                webbrowser.open(url)
            return
        rprint(
            f"[red]Port {port} is in use, but it is not a healthy STRATA app.[/red]\n"
            "Stop the stale process using that port or run with --port <other-port>."
        )
        raise typer.Exit(1)
    if daemon:
        cmd = [sys.executable, "-m", "cxl_strata.cli", "app", "--host", host, "--port", str(port)]
        if project:
            cmd.extend(["--project", project])
        if open_browser:
            cmd.append("--open")
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        rprint(f"[green]Started STRATA app daemon[/green] on {url}")
        return
    if project:
        rprint(f"[dim]Filtering initial view to project {project}[/dim]")
    run_app(host=host, port=port, open_browser=open_browser, project=project)


@app_typer.command("status")
def app_status() -> None:
    """Show autostart installation status."""
    status = autostart_status()
    rprint(json.dumps(status, indent=2))


@app_typer.command("install-autostart")
def app_install_autostart(
    background: bool = typer.Option(False, "--background"),
    open_browser: bool = typer.Option(False, "--open"),
) -> None:
    """Opt-in OS startup entry for STRATA app."""
    target = install_autostart(background=background, open_browser=open_browser)
    rprint(f"[green]Installed autostart[/green] at {target}")


@app_typer.command("uninstall-autostart")
def app_uninstall_autostart() -> None:
    """Remove STRATA app autostart entry."""
    removed = uninstall_autostart()
    if removed:
        rprint(f"[green]Removed[/green] {', '.join(str(p) for p in removed)}")
    else:
        rprint("[yellow]No autostart entry found.[/yellow]")


def register(app: typer.Typer) -> None:
    @app.command("index")
    def index_cmd(
        root: Optional[Path] = typer.Option(None, "--root"),
        full: bool = typer.Option(False, "--full", help="Re-index entire workspace"),
        path: Optional[Path] = typer.Option(None, "--path"),
    ) -> None:
        """Refresh local workspace_index.sqlite from markdown artifacts."""
        if root:
            set_workspace_root(root)
        if path:
            stats = indexer.index_paths([path.resolve()])
        else:
            stats = indexer.index_all(prune=full)
        rprint(json.dumps(stats, indent=2))

    @app.command("prune")
    def prune_cmd(
        project: Optional[str] = typer.Argument(None, help="Optional project slug to prune"),
        kinds: str = typer.Option("handoff", "--kinds"),
        plan_status: Optional[str] = typer.Option(None, "--plan-status"),
        execute: bool = typer.Option(False, "--execute"),
        older_than_hours: Optional[int] = typer.Option(None, "--older-than-hours"),
        archive_handoffs: bool = typer.Option(False, "--archive-handoffs"),
        root: Optional[Path] = typer.Option(None, "--root"),
    ) -> None:
        """Archive file-backed docs into SQLite (dry-run by default)."""
        if root:
            set_workspace_root(root)
        result = prune.run_prune(
            kinds=[k.strip() for k in kinds.split(",") if k.strip()],
            project=project,
            execute=execute,
            plan_status=plan_status,
            older_than_hours=older_than_hours,
            archive_handoffs=archive_handoffs,
        )
        rprint(json.dumps(result, indent=2))
        if not execute:
            rprint("[yellow]Dry run. Re-run with --execute to delete files.[/yellow]")

    @app.command("stash")
    def stash_cmd(
        kind: Optional[str] = typer.Option(None, "--kind"),
        project: Optional[str] = typer.Option(None, "--project"),
        since: Optional[str] = typer.Option(None, "--since"),
        path: Optional[str] = typer.Option(None, "--path"),
        all_docs: bool = typer.Option(False, "--all"),
        author_name: Optional[str] = typer.Option(None, "--author-name"),
    ) -> None:
        """Push local indexed docs to central STRATA API."""
        if path:
            result = documents.stash_paths([path], author_name=author_name)
        else:
            result = documents.stash_filtered(
                kind=kind, project=project, since=since, all_docs=all_docs
            )
        rprint(json.dumps(result, indent=2))

    @app.command("archive")
    def archive_cmd(
        prefix: Optional[str] = typer.Option(
            None, "--prefix", help="Archive all docs whose path starts with this prefix"
        ),
        path: Optional[str] = typer.Option(None, "--path", help="Archive a single doc path"),
        execute: bool = typer.Option(False, "--execute"),
        root: Optional[Path] = typer.Option(None, "--root"),
    ) -> None:
        """Archive docs locally: tombstone + never re-pull (remote copies kept)."""
        if root:
            set_workspace_root(root)
        if not prefix and not path:
            rprint("[red]Provide --prefix or --path.[/red]")
            raise typer.Exit(1)
        if path:
            if execute:
                result = documents.archive_paths([path])
            else:
                result = {"would_archive": [path], "count": 1, "executed": False}
        else:
            result = documents.archive_prefix(prefix, execute=execute)
        rprint(json.dumps(result, indent=2))
        if not execute:
            rprint("[yellow]Dry run. Re-run with --execute to archive.[/yellow]")

    @app.command("pull")
    def pull_cmd(
        project: Optional[str] = typer.Option(None, "--project"),
        kind: Optional[str] = typer.Option(None, "--kind"),
        since: Optional[str] = typer.Option(None, "--since"),
        limit: int = typer.Option(200, "--limit"),
    ) -> None:
        """Download shared documents from central API into local SQLite."""
        result = pull.pull_documents(project=project, kind=kind, since=since, limit=limit)
        rprint(json.dumps(result, indent=2))

    app.add_typer(app_typer, name="app")
