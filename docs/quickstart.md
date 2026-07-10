# Quick Start

This guide is for a developer whose workstation already has STRATA installed and a valid API key.

STRATA has these local surfaces:

- `.strata/` in the workspace or a repo: STRATA config and JSONL sync queue.
- `.md/handoff/`, `.md/blueprints/`, `.md/reports/`: workspace knowledge folders (uniform home for markdown artifacts).
- `.md/workspace_index.sqlite` at the workspace root: local searchable SQLite cache for handoffs, blueprints, plans, rules, and pulled shared docs.
- `strata app --open`: localhost UI for browsing the local SQLite cache.

The central API is separate. It stores team memory in PostgreSQL and serves search/MCP requests.

Fresh installs scaffold the `.md/` layout and create the SQLite cache during bootstrap (`--init`). App startup does the same if anything is missing. Init also installs the Cursor STRATA skill, orchestration rules, and hooks so agents know where to write handoffs, blueprints, and reports.

After installing and setting your API key, run the post-key bootstrap from the workspace root:

```bash
python -m cxl_strata.cli --init
```

This hardens PATH, creates the `.md/` knowledge folders and `.md/workspace_index.sqlite`, installs Cursor skill/rules/hooks, and opens `http://127.0.0.1:8765`.

If this returns `No such option: --init`, refresh through the installer bootstrap instead:

```powershell
& ([scriptblock]::Create((irm https://strata.example.com/install.ps1))) -Org example-org -Init
```

## 1. Verify The API And Identity

Open a new terminal after installing STRATA so your shell reloads PATH. Then run:

```bash
strata whoami
```

Expected output includes actor, organization, scopes, and API.

If `strata` is not found:

```bash
python -m cxl_strata.cli whoami
```

On macOS/Linux systems where Python is named `python3`:

```bash
python3 -m cxl_strata.cli whoami
```

The module command proves STRATA is installed even if your shell has not picked up Python's user scripts directory yet. The installer writes managed PATH blocks for future shells, but existing terminals may need to be reopened. See [Client Installation](client-installation.md#about-path) for PATH details.

## 2. Initialize The Workspace

From the workspace root, for example the folder where your agent/editor is opened:

```bash
strata init \
  --api https://strata.example.com \
  --org example-org
```

This writes `.strata/config.json` and local queue files without narrowing STRATA to one project or repo. It also scaffolds:

```text
.md/handoff/
.md/blueprints/
.md/reports/
.md/.gitignore
.cursor/skills/strata/SKILL.md
.cursor/rules/          (memory-capture + orchestration rules)
.cursor/hooks.json
.cursor/hooks/
```

Existing files are never overwritten. Use `--project` only when you intentionally want capture commands to default to one project, and `--repo` only when you intentionally want notes scoped to one repo.

Create or refresh the local SQLite index:

```bash
strata index
```

This creates `.md/workspace_index.sqlite` if it does not exist.

After a client package update, fill in any newly packaged folders/rules/hooks without re-running full init:

```bash
strata refresh
```

## 3. Capture A Memory Note

Use STRATA for durable context, not every edit.

Good examples:

- Bug root cause
- Deployment gotcha
- Architecture decision
- Client assumption
- QA regression pattern
- Environment-specific behavior

Command:

```bash
strata add \
  --type debug_discovery \
  --title "OAuth redirect used stale domain" \
  --summary "The redirect issue was caused by stale runtime environment configuration." \
  --environment staging \
  --tags oauth,env,redirect
```

This queues the note locally in `.strata/events.jsonl`.

## 4. Sync To The Central API

```bash
strata sync
```

Successful rows move to `.strata/synced.jsonl`. Failed rows are preserved in `.strata/failed.jsonl`.

## 5. Search Team Memory

```bash
strata search "oauth redirect"
strata recent --days 7
```

These commands query the central API.

## 6. Build The Local SQLite Cache

From the workspace root, index local artifacts. This includes `.cursor/rules/*.mdc`, `CLAUDE.md`, `.claude/**/*.md`, `AGENTS.md`, and `.codex/**/*.md` when those files exist:

```bash
strata index
```

Pull shared documents from the central API into the local SQLite cache:

```bash
strata pull
```

Confirm the SQLite cache exists:

```bash
ls .md/workspace_index.sqlite
```

PowerShell:

```powershell
Test-Path .md\workspace_index.sqlite
```

If your shell is inside a nested repo and STRATA cannot find the workspace root, set:

```bash
export STRATA_WORKSPACE_ROOT=/path/to/workspace
```

PowerShell:

```powershell
$env:STRATA_WORKSPACE_ROOT = "C:\path\to\workspace"
```

## 7. Open The Localhost App

```bash
strata app --open
```

Default URL:

```text
http://127.0.0.1:8765
```

The app browses the local SQLite cache, not the central PostgreSQL database directly. On startup it also refreshes missing workspace assets (`.md/` folders, Cursor rules/hooks) and indexes local files. Use `strata index` for local files and `strata pull` for shared documents before expecting new material to appear.

Optional autostart:

```bash
strata app install-autostart
strata app status
strata app uninstall-autostart
```

## 8. Stash Local Docs To Shared STRATA

Push indexed workspace documents to the central API:

```bash
strata stash
```

Push one file:

```bash
strata stash --path .md/handoff/my-project/2026-06-30T12-00-00Z.md
```

## 9. Agent Workflows

Cursor:

```text
/strata add - capture a durable note
/strata summary - capture an end-of-flow summary
/strata prune - report archival local markdown files that can be stashed and pruned
/strata prune my-project --execute - stash then remove archival local files for one project
```

Claude or Codex:

```bash
strata add --type implementation_note --title "Useful context" --summary "A concise durable note."
strata summary --text "End-of-day project summary." --sync
strata stash
strata prune --archive-handoffs
strata prune my-project --archive-handoffs --execute
```

MCP clients can retrieve context with:

- `strata_search`
- `strata_recent`
- `strata_get`
- `strata_context`

## 10. Smoke Test

Run this from the initialized workspace:

```bash
strata index
strata pull
strata stash
strata app --open
```

Success means:

- `strata stash` shares pending indexed workspace docs or reports nothing pending.
- `.md/handoff/`, `.md/blueprints/`, and `.md/reports/` exist at the workspace root.
- `.md/workspace_index.sqlite` exists at the workspace root.
- The localhost app opens on `127.0.0.1:8765`.
