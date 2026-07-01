# STRATA CLI

Local capture, workspace knowledge indexing, and central sync for STRATA project memory.

## Install

```bash
pip install -e .
strata init --api https://strata.craftxlogic.com --org craftxlogic --project example --repo example-repo
export STRATA_API_KEY=strata_live_...
python -m cxl_strata.cli --init
strata whoami
```

## Workspace knowledge (hybrid local + shared)

Local SQLite (`.md/workspace_index.sqlite`) is the fast offline cache. Shared full artifacts live in the central API.

```bash
# Create/refresh .md/workspace_index.sqlite from workspace root
# Includes handoffs, blueprints, plans, Cursor rules, CLAUDE.md, and AGENTS.md
strata index

# Archive old handoffs into SQLite (dry-run by default)
strata prune --archive-handoffs
strata prune --archive-handoffs --execute

# Push indexed docs to central API (author from API token)
strata stash --project synq-phalanx
strata stash --path .md/handoff/synq-phalanx/2026-06-30T12-00-00Z.md

# Pull shared docs into local SQLite for offline search
strata pull --project synq-phalanx

# Local UI on http://127.0.0.1:8765 — bootstraps SQLite if missing
strata app --open

# Opt-in autostart (never installed by one-line installer)
strata app install-autostart
strata app status
strata app uninstall-autostart
```

Set `STRATA_WORKSPACE_ROOT` to override workspace discovery (defaults: walk up from cwd for `.md/handoff`).

Legacy scripts (`python scripts/index_workspace.py`, `workspace_explorer.py`) remain as thin wrappers calling `strata`.

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
strata org add commonspace --key strata_live_... --org commonspace

# Use it for any command
strata -org commonspace whoami
strata -org commonspace search "deploy apache"
strata -org commonspace stash --project commonspace-app

strata org list
```

Profile files live at `~/.strata/orgs/{alias}.json`:

```json
{
  "api_key": "strata_live_...",
  "org": "commonspace",
  "api_base_url": "https://strata.craftxlogic.com"
}
```

`api_base_url` is optional; when omitted, the default from `~/.strata/global.json` is used.
