---
name: strata
description: Use STRATA project memory commands. Use when the user invokes /strata, /strata add, /strata summary, /strata prune, or asks to capture, sync, summarize, stash, or prune STRATA workspace knowledge.
---

# STRATA

Use this skill for prompt-facing STRATA memory workflows.

## Commands

### `/strata add`

Capture durable project memory, not raw chat logs.

1. Identify the project from the current repo, handoff path, blueprint, or explicit user scope.
2. Reject secrets, raw `.env` values, API keys, private keys, passwords, and tokens.
3. Queue a concise memory note:

```bash
strata add \
  --project "<project_slug>" \
  --type "<event_type>" \
  --title "<short title>" \
  --summary "<1-2 sentence durable summary>" \
  --details "<optional supporting detail>" \
  --environment "<local|staging|production|none>" \
  --tags "<comma,separated,tags>" \
  --visibility internal \
  --confidence observed
```

Use `--repo "<repo_name>"` only when the user intentionally scopes the note to one repo.

### `/strata summary`

Capture an end-of-flow summary for a specific project.

```bash
strata summary \
  --project "<project_slug>" \
  --text "<concise summary of work done>" \
  --sync
```

### `/strata prune`

Report or execute archival cleanup while preserving searchable local content.

Supported forms:

```text
/strata prune
/strata prune <project name>
/strata prune --execute
/strata prune <project name> --execute
```

Behavior:

1. Parse optional project scope and `--execute`.
2. If no project is provided, operate across all local projects.
3. Before pruning, stash/index matching documents:

```bash
strata stash
strata stash --project "<project name>"
```

4. Dry run by default:

```bash
strata prune --archive-handoffs
strata prune "<project name>" --archive-handoffs
```

5. Only delete after explicit `--execute`:

```bash
strata prune --archive-handoffs --execute
strata prune "<project name>" --archive-handoffs --execute
```

Report `would_prune` for dry runs or `pruned` for execute runs, plus skipped/errors.
