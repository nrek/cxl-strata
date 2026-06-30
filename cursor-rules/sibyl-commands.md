# SIBYL Cursor commands

When the user types **`/sibyl add`** or **`/sibyl summary`**, treat it as a capture request for the **current repo's** SIBYL project memory.

## Prerequisites

- Repo has `.sibyl/config.json` (from `sibyl init`) or infer project from repo folder / blueprint
- Access token in `SIBYL_API_KEY` or `.sibyl/secrets.json` (never commit)
- Central API URL in `.sibyl/config.json`

## `/sibyl add`

**Purpose:** Capture durable project knowledge or upload an existing handoff.

**Agent behavior:**

1. Identify `project_slug` and `repo_name` from `.sibyl/config.json` or repo folder name.
2. If the user points at a handoff file (e.g. `.md/handoff/<project>/*.md`), queue it:

```bash
sibyl add --handoff-path .md/handoff/<project>/<timestamp>.md
```

3. Otherwise, distill the session into a concise memory note - **no secrets, no raw chat dump**:

```bash
sibyl add \
  --type "<event_type>" \
  --title "<short title>" \
  --summary "<1-2 sentence durable summary>" \
  --details "<optional supporting detail>" \
  --environment "<local|staging|production|none>" \
  --tags "<comma,separated,tags>" \
  --visibility internal \
  --confidence observed
```

4. Offer to run `sibyl sync` or run it if the user confirms.

**Event types:** `debug_discovery`, `implementation_note`, `ops_change`, `deployment_note`, `architecture_decision`, `client_assumption`, `planning_warning`, `qa_finding`, `general_note`, `handoff_upload`.

## `/sibyl summary`

**Purpose:** End-of-day or end-of-flow summary for the current project.

**Agent behavior:**

1. Summarize what changed, was verified, and any follow-ups from the session (or day).
2. Queue via CLI:

```bash
sibyl summary \
  --project "<project_slug>" \
  --text "<concise summary of work done>" \
  --sync
```

3. Default `event_type` on server: `daily_summary`. Title pattern: `Daily summary - <project>`.

## Security (hard rules)

- Never include passwords, tokens, API keys, or raw `.env` values.
- Default visibility: `internal`.
- Client-management context: `internal` or `admin_only`, not `client_safe` unless explicitly safe.

## After capture

```bash
sibyl sync          # push queue to central API
sibyl search "..."  # verify on central store
```
