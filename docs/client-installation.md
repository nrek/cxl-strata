# Client Installation

This guide installs STRATA on developer workstations and connects Cursor, Claude, Codex, or any terminal-based workflow to the central API.

The installer:

1. Installs the STRATA CLI (`strata`).
2. Installs the STRATA MCP server package.
3. Writes user-level defaults in `~/.strata/global.json` and `~/.strata/secrets.json`.
4. When run with bootstrap init (`--init` / `-Init`), scaffolds the `.md/` knowledge layout, creates the local SQLite workspace index, installs Cursor skill/rules/hooks, and opens the localhost UI.
5. When re-run without init (update mode), upgrades packages and runs `strata refresh` so newly packaged workspace assets appear without overwriting existing files.

It does not grant access by itself. Each user still needs a personal token from an admin.

## Requirements

- Python 3.10+ for the CLI
- Python 3.11+ for the MCP server
- `pip`
- Git, until STRATA is published to PyPI
- A STRATA API URL such as `https://strata.example.com`
- A personal `strata_live_...` token

## About PATH

The `strata` command is installed by `pip install --user`. That puts the executable in Python's **user scripts** directory, which is not always on PATH by default.

The installer now tries to make `strata` work automatically:

- Linux, macOS, WSL, bash, zsh, xTerm: asks Python for the actual user scripts directory, adds it to the current session, and writes a managed STRATA PATH block to `.profile`, `.bashrc`, and `.zshrc` when those files are writable.
- Windows PowerShell: asks Python for the actual user `Scripts` directory, adds it to the current session, adds it to the user PATH environment variable, and writes a managed STRATA PATH block to the PowerShell profile.

The managed profile block is marked with `STRATA_PATH_BLOCK_BEGIN` / `STRATA_PATH_BLOCK_END`, so it is easy to find or remove later.

After install, open a new terminal and run:

```bash
strata whoami
```

If `strata` still is not found, the CLI is usually installed correctly but the shell has not picked up PATH yet. Use the module fallback:

```bash
python -m cxl_strata.cli whoami
```

On macOS/Linux systems where Python is named `python3`:

```bash
python3 -m cxl_strata.cli whoami
```

After setting your API key, run the post-key bootstrap:

```bash
python -m cxl_strata.cli --init
```

On macOS/Linux systems where Python is named `python3`:

```bash
python3 -m cxl_strata.cli --init
```

This command hardens PATH, scaffolds the workspace knowledge layout (`.md/handoff/`, `.md/blueprints/`, `.md/reports/`), creates `.md/workspace_index.sqlite`, installs the Cursor STRATA skill, the orchestration rule bundle (`.cursor/rules/`), and Cursor hooks (`.cursor/hooks.json`), and opens the browser UI.

If PowerShell reports `No such option: --init`, the installed CLI is older than the docs. Rerun the installer bootstrap instead:

```powershell
& ([scriptblock]::Create((irm https://strata.example.com/install.ps1))) -Org example-org -Init
```

That path uses the installer script itself to refresh the package, initialize the workspace, create the SQLite cache, and open the UI.

## Linux, macOS, WSL, xTerm, Bash, Zsh

Use the Unix installer from any shell:

```bash
curl -fsSL https://strata.example.com/install.sh | bash
```

Install and initialize the current workspace:

```bash
curl -fsSL https://strata.example.com/install.sh | bash -s -- \
  --org example-org \
  --init
```

The installer persists PATH for future shells in `.profile`, `.bashrc`, and `.zshrc` when possible. If this shell was already open before install and `strata` is not found yet, open a new shell or use:

```bash
python3 -m cxl_strata.cli whoami
```

## Windows PowerShell

Install:

```powershell
irm https://strata.example.com/install.ps1 | iex
```

Install and initialize the current workspace:

```powershell
& ([scriptblock]::Create((irm https://strata.example.com/install.ps1))) -Org example-org -Init
```

Ask for a Cursor MCP snippet:

```powershell
& ([scriptblock]::Create((irm https://strata.example.com/install.ps1))) -Cursor
```

The installer persists PATH for future PowerShell sessions. If `strata` is not found immediately, reopen PowerShell or run:

```powershell
python -m cxl_strata.cli whoami
```

The installer adds the Python user Scripts directory to the current session, the user PATH environment variable, and your PowerShell profile when possible. The user PATH update is what makes `strata` available to new PowerShell, Cursor, Claude, and Codex terminals.

## Workspace Layout, Local SQLite, And UI Bootstrap

STRATA expects a uniform knowledge layout at the workspace root:

```text
.md/handoff/                 per-project handoffs
.md/blueprints/              architecture blueprints
.md/reports/                 audits, digests, exports
.md/workspace_index.sqlite   local searchable cache
.md/.gitignore               ignores sqlite + wal/shm
```

Fresh workstations should not create these by hand.

After setting the API key, users should run from the workspace root:

```bash
python -m cxl_strata.cli --init
```

This is the easiest all-in-one command: it adds STRATA to PATH for future terminals, scaffolds the `.md/` folders, creates the local SQLite database, installs Cursor skill/rules/hooks, indexes local Cursor/Claude/Codex context files, pulls shared docs when possible, and opens the localhost UI.

If `--init` is not recognized, rerun the installer with `-Init`; the installer bootstrap is the compatibility fallback for older local CLI installs.

When you install with workspace initialization, STRATA runs `strata index` automatically after `strata init`:

```bash
curl -fsSL https://strata.example.com/install.sh | bash -s -- --org example-org --init
```

PowerShell:

```powershell
& ([scriptblock]::Create((irm https://strata.example.com/install.ps1))) -Org example-org -Init
```

That creates `.md/workspace_index.sqlite` in the detected workspace root and indexes local agent context files.

The UI also bootstraps the database and refreshes missing packaged assets when it starts:

```bash
strata app --open
```

No-PATH fallback:

```bash
python -m cxl_strata.cli app --open
```

Cursor, Claude, and Codex context files are indexed as local rules when present:

- Cursor: `.cursor/skills/**/SKILL.md`, `.cursor/rules/*.mdc`
- Claude: `CLAUDE.md`, `.claude/**/*.md`
- Codex: `AGENTS.md`, `.codex/**/*.md`

If the UI opens but looks empty, run:

```bash
strata index
strata pull
strata app --open
```

## Updating An Existing Client

Re-run the installer without `--init` / `-Init` to upgrade the CLI and MCP packages (this is also what the in-app **Update** button runs):

```bash
curl -fsSL https://strata.example.com/install.sh | bash
```

```powershell
irm https://strata.example.com/install.ps1 | iex
```

Update mode also runs `strata refresh` in the current directory: it re-scaffolds any missing `.md/` folders and installs any newly packaged Cursor rules and hooks. The refresh is non-destructive — files that already exist on disk are never overwritten — and it is a no-op outside a STRATA workspace. `strata app` performs the same refresh on startup, so the app restart after an in-app update picks up new assets too.

Run it manually anytime:

```bash
strata refresh
```

## Set The API Key

Preferred user-level file:

```json
{
  "api_key": "strata_live_your_personal_token"
}
```

Paths:

- Linux, macOS, WSL: `~/.strata/secrets.json`
- Windows PowerShell: `%USERPROFILE%\.strata\secrets.json`

Environment variable alternative:

```bash
export STRATA_API_KEY="strata_live_your_personal_token"
```

PowerShell:

```powershell
$env:STRATA_API_KEY = "strata_live_your_personal_token"
```

## Initialize A Workspace

Run this from the workspace root, for example the folder Cursor opens:

```bash
strata init \
  --api https://strata.example.com \
  --org example-org \
  --actor-name "Your Name" \
  --actor-email you@example.com
```

PowerShell:

```powershell
strata init --api https://strata.example.com --org example-org --actor-name "Your Name" --actor-email you@example.com
```

`--project` is only for choosing a default project for memory-capture commands. `--repo` is only for scoping those notes to one repo. Leave both off for all-project/all-repo workspace sync.

This creates:

```text
.strata/config.json
.strata/events.jsonl
.strata/synced.jsonl
.strata/failed.jsonl
.md/handoff/
.md/blueprints/
.md/reports/
.md/.gitignore
.cursor/rules/            (STRATA rule + 7 orchestration rules)
.cursor/skills/strata/SKILL.md
.cursor/hooks.json
.cursor/hooks/            (strata-session-digest.py, reindex-workspace.py)
```

The `.md/` tree is the uniform home for workspace knowledge: handoffs, blueprints, reports, and the SQLite index (`.md/workspace_index.sqlite`). The orchestration rules teach agents to write handoffs to `.md/handoff/<project>/`, blueprints to `.md/blueprints/`, and reports to `.md/reports/<repo-slug>/`. Existing files are never overwritten — re-running init is safe.

Recommended `.gitignore` entries:

```gitignore
.strata/secrets.json
.strata/events.jsonl
.strata/synced.jsonl
.strata/failed.jsonl
```

## Verify Installation

API health:

```bash
curl -fsS https://strata.example.com/health
```

PowerShell:

```powershell
irm https://strata.example.com/health
```

CLI and auth:

```bash
strata whoami
```

No-PATH fallback:

```bash
python -m cxl_strata.cli whoami
```

Expected output includes actor, organization, scopes, and API.

## Cursor

`strata init`, `python -m cxl_strata.cli --init`, and installer `-Init` automatically write the project Cursor skill to `.cursor/skills/strata/SKILL.md`, the STRATA rule `.cursor/rules/strata-memory-capture.mdc`, the seven orchestration rules (`agent-context-bootstrap`, `blueprints`, `handoff-logging`, `prior-art`, `reports-organization`, `workspace-knowledge`, `workspace-repo-scope`), and Cursor hooks (`.cursor/hooks.json` plus `.cursor/hooks/strata-session-digest.py` and `.cursor/hooks/reindex-workspace.py`). The `.cursor/` folder is created if missing. Existing files are never overwritten.

Shared rule updates continue to flow after init: `strata pull` writes pulled `kind: rule` documents to `.cursor/rules/` on disk so Cursor `alwaysApply` picks them up.

If `/strata` is not suggested, confirm the skill exists, then restart or reload Cursor's skills:

- `.cursor/skills/strata/SKILL.md`

Without the Cursor skill, use the CLI equivalents directly: `strata stash`, `strata stash --project <project>`, `strata prune --archive-handoffs`, and `strata prune <project> --archive-handoffs --execute`.

For MCP retrieval, add both servers — `strata` talks to the central API; `workspace-knowledge` serves the local SQLite index (`knowledge_recent`, `knowledge_search`, `knowledge_graph_neighbors`, `handoff_write`, and more):

```json
{
  "mcpServers": {
    "strata": {
      "command": "python",
      "args": ["-m", "strata_mcp.server"],
      "env": {
        "STRATA_API_URL": "https://strata.example.com",
        "STRATA_API_KEY": "strata_live_your_personal_token"
      }
    },
    "workspace-knowledge": {
      "command": "python",
      "args": ["-m", "cxl_strata.workspace_index.mcp_server"]
    }
  }
}
```

Restart Cursor after editing MCP config.

## Claude

Claude Code can use the CLI directly from the project terminal. Add project instructions in `CLAUDE.md`:

````markdown
## STRATA project memory

When durable project knowledge is discovered, propose a STRATA memory note.
Never include secrets, raw `.env` values, or full chat logs.

Useful commands:

```bash
strata add --type implementation_note --title "..." --summary "..."
strata summary --text "..." --sync
strata search "..."
```
````

For Claude Desktop with MCP, configure `strata_mcp.server` with `STRATA_API_URL` and `STRATA_API_KEY` in the same shape your MCP client expects.

## Codex

Codex-style agents work best with CLI plus `AGENTS.md`:

````markdown
## STRATA memory capture

After meaningful work, suggest a concise STRATA capture:

```bash
strata add --type <event_type> --title "..." --summary "..."
strata sync
```

Do not capture secrets or raw chat logs.
````

Make sure the shell where Codex runs has either `STRATA_API_KEY` or `~/.strata/secrets.json`.

## MCP For AI Context Retrieval

The MCP server exposes:

- `strata_search`
- `strata_recent`
- `strata_get`
- `strata_context`

Environment:

```bash
export STRATA_API_URL=https://strata.example.com
export STRATA_API_KEY=strata_live_your_personal_token
```

Manual install from the repo:

```bash
cd mcp
pip install -e .
```

The one-line installers install the MCP package automatically.

## Named Org Profiles

Use named profiles when one workstation talks to more than one STRATA installation:

```bash
strata org add team-a --key strata_live_... --org example-org --api https://strata.example.com
strata -org team-a whoami
strata -org team-a search "deploy apache"
strata org list
```
