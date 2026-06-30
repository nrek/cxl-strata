# Quick Start

This guide is for a developer whose workstation already has STRATA installed and a valid API key.

STRATA has three local surfaces:

- `.strata/` in each repo: repo config and JSONL sync queue.
- `.md/workspace_index.sqlite` at the workspace root: local searchable SQLite cache for handoffs, blueprints, plans, rules, and pulled shared docs.
- `strata app --open`: localhost UI for browsing the local SQLite cache.

The central API is separate. It stores team memory in PostgreSQL and serves search/MCP requests.

## 1. Verify The API And Identity

```bash
strata whoami
```

Expected output includes actor, organization, scopes, and API.

If `strata` is not found:

```bash
python -m cxl_strata.cli whoami
```

## 2. Initialize The Current Repo

From the repo root:

```bash
strata init \
  --api https://strata.example.com \
  --org example-org \
  --project my-project \
  --repo my-repo
```

This writes `.strata/config.json` and local queue files.

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

From the workspace root, index local artifacts:

```bash
strata index
```

Pull shared documents from the central API into the local SQLite cache:

```bash
strata pull --project my-project
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
$env:STRATA_WORKSPACE_ROOT = "D:\projects"
```

## 7. Open The Localhost App

```bash
strata app --open
```

Default URL:

```text
http://127.0.0.1:8765
```

The app browses the local SQLite cache, not the central PostgreSQL database directly. Use `strata index` for local files and `strata pull` for shared documents before expecting new material to appear.

Optional autostart:

```bash
strata app install-autostart
strata app status
strata app uninstall-autostart
```

## 8. Stash Local Docs To Shared STRATA

Push indexed workspace documents to the central API:

```bash
strata stash --project my-project
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
```

Claude or Codex:

```bash
strata add --type implementation_note --title "Useful context" --summary "A concise durable note."
strata summary --text "End-of-day project summary." --sync
```

MCP clients can retrieve context with:

- `strata_search`
- `strata_recent`
- `strata_get`
- `strata_context`

## 10. Smoke Test

Run this from any initialized repo:

```bash
strata add --type general_note --title "STRATA install check" --summary "Verified STRATA capture and sync."
strata sync
strata search "STRATA install check"
strata index
strata pull --project my-project
strata app --open
```

Success means:

- `strata sync` reports at least one synced event.
- `strata search` finds the test note.
- `.md/workspace_index.sqlite` exists at the workspace root.
- The localhost app opens on `127.0.0.1:8765`.
