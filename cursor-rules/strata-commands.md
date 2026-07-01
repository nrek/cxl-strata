# STRATA Cursor commands

When the user types **`/strata add`**, **`/strata summary`**, or **`/strata prune`**, treat it as a STRATA project memory command.

## Prerequisites

- Repo has `.strata/config.json` (from `strata init`) or infer project from repo folder / blueprint
- Access token in `STRATA_API_KEY` or `.strata/secrets.json` (never commit)
- Central API URL in `.strata/config.json`

## `/strata add`

**Purpose:** Capture durable project knowledge or upload an existing handoff.

**Agent behavior:**

1. Identify `project_slug` and `repo_name` from `.strata/config.json` or repo folder name.
2. If the user points at a handoff file (e.g. `.md/handoff/<project>/*.md`), queue it:

```bash
strata add --handoff-path .md/handoff/<project>/<timestamp>.md
```

3. Otherwise, distill the session into a concise memory note - **no secrets, no raw chat dump**:

```bash
strata add \
  --type "<event_type>" \
  --title "<short title>" \
  --summary "<1-2 sentence durable summary>" \
  --details "<optional supporting detail>" \
  --environment "<local|staging|production|none>" \
  --tags "<comma,separated,tags>" \
  --visibility internal \
  --confidence observed
```

4. Offer to run `strata sync` or run it if the user confirms.

**Event types:** `debug_discovery`, `implementation_note`, `ops_change`, `deployment_note`, `architecture_decision`, `client_assumption`, `planning_warning`, `qa_finding`, `general_note`, `handoff_upload`.

## `/strata summary`

**Purpose:** End-of-day or end-of-flow summary for the current project.

**Agent behavior:**

1. Summarize what changed, was verified, and any follow-ups from the session (or day).
2. Queue via CLI:

```bash
strata summary \
  --project "<project_slug>" \
  --text "<concise summary of work done>" \
  --sync
```

3. Default `event_type` on server: `daily_summary`. Title pattern: `Daily summary - <project>`.

## `/strata prune`

**Purpose:** Offload archival local markdown files from the user's filesystem while keeping the content searchable in STRATA's local SQLite datastore and available for sync to STRATA.

**Supported forms:**

```text
/strata prune
/strata prune <project name>
/strata prune --execute
/strata prune <project name> --execute
```

**Agent behavior:**

1. Parse optional project scope and `--execute`.
2. If no project is provided, operate across all local projects. If a project is provided, scope both stash and prune to that project.
3. Before pruning, stash/index the matching documents so the content remains in the local searchable SQLite datastore:

```bash
strata stash
strata stash --project "<project name>"
```

4. For non-`--execute` commands, generate a report of markdown files that can be stashed and pruned. Do not delete files:

```bash
strata prune --archive-handoffs
strata prune "<project name>" --archive-handoffs
```

5. For `--execute` commands, confirm the user intended deletion, then stash and prune. Prune verifies file-backed documents match the SQLite body before marking them `db_only` and removing archival local files:

```bash
strata prune --archive-handoffs --execute
strata prune "<project name>" --archive-handoffs --execute
```

6. Report `would_prune` for dry runs or `pruned` for execute runs, plus skipped/errors. Never delete files without explicit `--execute`.

**If `/strata prune` is not recognized:** install the STRATA CLI, then add this rule file (`cursor-rules/strata-commands.md`) to `.cursor/rules/strata-memory-capture.mdc` or user-level Cursor rules, and restart/reload the AI IDE rules. Until then, use the CLI equivalents above.

## Security (hard rules)

- Never include passwords, tokens, API keys, or raw `.env` values.
- Default visibility: `internal`.
- Client-management context: `internal` or `admin_only`, not `client_safe` unless explicitly safe.

## After capture

```bash
strata sync          # push queue to central API
strata search "..."  # verify on central store
```
