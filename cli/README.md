# STRATA CLI

Local capture, workspace knowledge indexing, and central sync for STRATA project memory.

## Install

```bash
pip install -e .
strata init --api https://strata.example.com --org example-org
export STRATA_API_KEY=strata_live_...
python -m cxl_strata.cli --init
strata whoami
```

`strata init` and `python -m cxl_strata.cli --init` scaffold the workspace knowledge layout (`.md/handoff/`, `.md/blueprints/`, `.md/reports/`), create `.md/workspace_index.sqlite`, and install Cursor skill, orchestration rules, and hooks. Claude Code and Codex users can use the same CLI commands directly from their agent shells.

## Workspace knowledge (hybrid local + shared)

Local SQLite (`.md/workspace_index.sqlite`) is the fast offline cache. Shared full artifacts live in the central API.

```bash
# Scaffold / fill missing .md folders + Cursor rules/hooks (non-destructive)
strata refresh

# Create/refresh .md/workspace_index.sqlite from workspace root
# Includes handoffs, blueprints, plans, Cursor skills/rules, CLAUDE.md, and AGENTS.md
strata index

# Archive old handoffs into SQLite (dry-run by default)
strata prune --archive-handoffs
strata prune my-project --archive-handoffs
strata prune --archive-handoffs --execute
strata prune my-project --archive-handoffs --execute

# Push indexed docs to central API (author from API token)
strata stash
strata stash --project my-project
strata stash --path .md/handoff/my-project/2026-06-30T12-00-00Z.md

# Pull shared docs into local SQLite for offline search
# (kind=rule docs under .cursor/rules/ are also written to disk)
strata pull
strata pull --project my-project

# Local UI on http://127.0.0.1:8765 — bootstraps SQLite + refreshes assets if missing
strata app --open

# Opt-in autostart (never installed by one-line installer)
strata app install-autostart
strata app status
strata app uninstall-autostart
```

Set `STRATA_WORKSPACE_ROOT` to override workspace discovery (defaults: walk up from cwd for `.md/`, `.cursor/`, or `.strata/`).

## Memory events

```bash
strata add --type implementation_note --title "Useful context" --summary "A concise durable note."
strata summary --text "End-of-day project summary."
strata sync
strata search "deploy apache"
```

Store access tokens in `STRATA_API_KEY` or `~/.strata/secrets.json`; never commit secrets.

### Named org profiles (multi-installation)

Your **default** STRATA install uses `~/.strata/global.json` + `~/.strata/secrets.json` with no alias.

To talk to a **separate** STRATA org/installation with its own API key (without mixing knowledge libraries):

```bash
# One-time: save a named profile
strata org add team-a --key strata_live_... --org example-org

# Use it for any command
strata -org team-a whoami
strata -org team-a search "deploy apache"
strata -org team-a stash --project example-project

strata org list
```

Profile files live at `~/.strata/orgs/{alias}.json`:

```json
{
  "api_key": "strata_live_...",
  "org": "example-org",
  "api_base_url": "https://strata.example.com"
}
```

`api_base_url` is optional; when omitted, the default from `~/.strata/global.json` is used.
