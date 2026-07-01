# Client Installation

This guide installs STRATA on developer workstations and connects Cursor, Claude, Codex, or any terminal-based workflow to the central API.

The installer does three things:

1. Installs the STRATA CLI (`strata`).
2. Installs the STRATA MCP server package.
3. Writes user-level defaults in `~/.strata/global.json` and `~/.strata/secrets.json`.
4. When run with repo init, creates the local SQLite workspace index used by the localhost UI.

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

This command hardens PATH, creates `.md/workspace_index.sqlite`, and opens the browser UI.

If PowerShell reports `No such option: --init`, the installed CLI is older than the docs. Rerun the installer bootstrap instead:

```powershell
& ([scriptblock]::Create((irm https://strata.example.com/install.ps1))) -Org example-org -Init -Project my-project
```

That path uses the installer script itself to refresh the package, initialize the repo, create the SQLite cache, and open the UI.

## Linux, macOS, WSL, xTerm, Bash, Zsh

Use the Unix installer from any shell:

```bash
curl -fsSL https://strata.example.com/install.sh | bash
```

Install and initialize the current repo:

```bash
curl -fsSL https://strata.example.com/install.sh | bash -s -- \
  --org example-org \
  --init \
  --project my-project
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

Install and initialize the current repo:

```powershell
& ([scriptblock]::Create((irm https://strata.example.com/install.ps1))) -Org example-org -Init -Project my-project
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

## Local SQLite And UI Bootstrap

The localhost UI reads from a local SQLite cache at:

```text
.md/workspace_index.sqlite
```

Fresh workstations should not have to create that file by hand.

After setting the API key, users should run:

```bash
python -m cxl_strata.cli --init
```

This is the easiest all-in-one command: it adds STRATA to PATH for future terminals, creates the local SQLite database, indexes local Cursor/Claude/Codex context files, pulls shared docs when possible, and opens the localhost UI.

If `--init` is not recognized, rerun the installer with `-Init -Project my-project`; the installer bootstrap is the compatibility fallback for older local CLI installs.

When you install with repo initialization, STRATA now runs `strata index` automatically after `strata init`:

```bash
curl -fsSL https://strata.example.com/install.sh | bash -s -- --org example-org --init --project my-project
```

PowerShell:

```powershell
& ([scriptblock]::Create((irm https://strata.example.com/install.ps1))) -Org example-org -Init -Project my-project
```

That creates `.md/workspace_index.sqlite` in the detected workspace/repo root and indexes local agent context files.

The UI also bootstraps the database when it starts:

```bash
strata app --open
```

No-PATH fallback:

```bash
python -m cxl_strata.cli app --open
```

Cursor, Claude, and Codex context files are indexed as local rules when present:

- Cursor: `.cursor/rules/*.mdc`
- Claude: `CLAUDE.md`, `.claude/**/*.md`
- Codex: `AGENTS.md`, `.codex/**/*.md`

If the UI opens but looks empty, run:

```bash
strata index
strata pull --project my-project
strata app --open
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

## Initialize A Repo

Run this from the repo root:

```bash
strata init \
  --api https://strata.example.com \
  --org example-org \
  --project my-project \
  --repo my-repo \
  --actor-name "Your Name" \
  --actor-email you@example.com
```

PowerShell:

```powershell
strata init --api https://strata.example.com --org example-org --project my-project --repo my-repo --actor-name "Your Name" --actor-email you@example.com
```

This creates:

```text
.strata/config.json
.strata/events.jsonl
.strata/synced.jsonl
.strata/failed.jsonl
```

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

Install the CLI first, then add the project rule from [../cursor-rules/strata-commands.md](../cursor-rules/strata-commands.md) to either:

- `.cursor/rules/strata-memory-capture.mdc`
- User-level Cursor rules

For MCP retrieval, add a server config such as:

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
strata org add commonspace --key strata_live_... --org commonspace --api https://strata.example.com
strata -org commonspace whoami
strata -org commonspace search "deploy apache"
strata org list
```
