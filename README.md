# STRATA

<p align="center">
  <img src="assets/strata-logo.png" alt="STRATA logo" width="240">
</p>

**STRATA** is a shared project memory system for technical teams.

It helps developers capture the durable context teams usually lose: what changed, why it changed, what broke, how it was fixed, which decisions were made, and which environment details matter later.

STRATA is intentionally small. It is not a task manager, chat-log archive, terminal recorder, secret store, or replacement for Linear/GitHub Issues.

## Current Status

| Area | Status |
|------|--------|
| FastAPI central API | Done |
| PostgreSQL + Alembic | Done |
| Hashed per-user API keys | Done |
| Python CLI (`strata`) | Done |
| Local JSONL capture queue | Done |
| Shared document sync | Done |
| Local SQLite workspace cache | Done |
| Localhost browser app | Done |
| MCP retrieval server | Done |
| Curl/PowerShell installers | Done |
| PyPI release | Planned |

## How It Works

```text
Developer workstation
  Cursor, Claude, Codex, terminal, WSL, PowerShell, xTerm
      |
      | strata add / strata summary / agent rules
      v
Repo-local .strata/ queue
      |
      | strata sync over HTTPS with Bearer token
      v
Central STRATA API
  FastAPI + Uvicorn on 127.0.0.1:8015
      |
      v
PostgreSQL
      |
      v
Team search, recent history, shared docs, MCP retrieval
```

There is also a local workstation cache:

```text
Workspace markdown files + pulled shared docs
      |
      | strata index / strata pull
      v
.md/workspace_index.sqlite
      |
      | strata app --open
      v
http://127.0.0.1:8765
```

The central API stores shared team memory in PostgreSQL. The local SQLite database powers fast local browsing for Cursor, Claude, Codex, and terminal workflows.

## Repository Layout

```text
cxl-strata/
  api/              FastAPI central API, migrations, key provisioning
  cli/              Typer CLI, local queue, local SQLite index, localhost app
  mcp/              MCP stdio server for AI context retrieval
  cursor-rules/     Cursor command/rule examples
  docs/             Installation, provisioning, operations, security
  assets/           STRATA logo and icons
```

## Quick Start

Use this when the central API already exists and you have a personal token.

Install on Linux, macOS, WSL, bash, zsh, or xTerm:

```bash
curl -fsSL https://strata.example.com/install.sh | bash
```

Install on Windows PowerShell:

```powershell
irm https://strata.example.com/install.ps1 | iex
```

The installer tries to add `strata` to PATH automatically by updating the current session and common shell profiles or the Windows user PATH. Open a new terminal after install, then run `strata whoami`. If your shell still cannot find `strata`, use `python -m cxl_strata.cli whoami` (or `python3 -m cxl_strata.cli whoami`) and see [Client Installation](docs/client-installation.md#about-path).

Add your token:

```json
{
  "api_key": "strata_live_your_personal_token"
}
```

Store it in `~/.strata/secrets.json` or `%USERPROFILE%\.strata\secrets.json`.

Run the post-key bootstrap:

```bash
python -m cxl_strata.cli --init
```

This hardens PATH, installs `.cursor/rules/strata-memory-capture.mdc`, creates `.md/workspace_index.sqlite`, and opens the local UI.

If that returns `No such option: --init`, the workstation still has an older CLI. On Windows, rerun the installer bootstrap instead:

```powershell
& ([scriptblock]::Create((irm https://strata.example.com/install.ps1))) -Org example-org -Init
```

Initialize the workspace:

```bash
strata init \
  --api https://strata.example.com \
  --org example-org
```

Verify:

```bash
strata whoami
```

Capture and sync:

```bash
strata add \
  --type debug_discovery \
  --title "OAuth redirect used stale domain" \
  --summary "The redirect issue was caused by stale runtime environment configuration." \
  --environment staging \
  --tags oauth,env,redirect

strata sync
strata search "oauth redirect"
```

Open the local browser app:

```bash
strata index
strata pull
strata app --open
```

`strata index` creates `.md/workspace_index.sqlite` if it does not exist. The app also initializes this SQLite cache on startup, and indexes Cursor (`.cursor/rules/*.mdc`), Claude (`CLAUDE.md`, `.claude/**/*.md`), and Codex (`AGENTS.md`, `.codex/**/*.md`) instruction files as local rules.

See [Quick Start](docs/quickstart.md) for the full local workflow.

## Central Server/API Setup

The central API runs behind a reverse proxy:

```text
Apache or Nginx on 443
  -> Uvicorn on 127.0.0.1:8015
  -> PostgreSQL
```

Local development:

```bash
cd api
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
createdb strata
alembic upgrade head
python scripts/seed_key.py --org-slug example-org --prefix strata_dev_
uvicorn app.main:app --reload --host 127.0.0.1 --port 8015
```

Verify:

```bash
curl http://127.0.0.1:8015/health
```

Production setup includes:

- Ubuntu host
- PostgreSQL database
- `.env` with API URL, database URL, key pepper, installer metadata, and default org
- systemd service for `cxl-strata-api`
- Apache or Nginx TLS reverse proxy
- `alembic upgrade head`
- first admin token from `api/scripts/seed_key.py`

See [Server Setup](docs/server-setup.md).

## Provisioning Users

Each developer should have their own token. Install scripts are public bootstrap scripts; they do not grant access.

Create the first admin key on the API host:

```bash
cd /var/www/cxl-strata/api
source .venv/bin/activate
set -a && source .env && set +a
python scripts/seed_key.py \
  --org-slug example-org \
  --actor-name "Admin Name" \
  --actor-email admin@example.com \
  --key-name bootstrap-admin \
  --prefix strata_live_
```

Create additional user keys through `POST /v1/api-keys` using an admin token with `keys:manage` and `admin`.

Recommended onboarding:

1. Send the public install command and org slug.
2. Send the personal token separately through a secure channel.
3. Ask the user to run `strata whoami`.

See [Provisioning](docs/provisioning.md).

## Client Installation

Supported workstation surfaces:

- Linux terminal
- macOS Terminal or iTerm
- WSL
- xTerm
- Bash and zsh
- Windows PowerShell
- Cursor
- Claude Code or Claude Desktop with MCP
- Codex-style agent environments

Installers:

```bash
curl -fsSL https://strata.example.com/install.sh | bash
```

```powershell
irm https://strata.example.com/install.ps1 | iex
```

After a user sets their token, have them run:

```bash
python -m cxl_strata.cli --init
```

That post-key bootstrap hardens PATH, creates the local SQLite cache, and opens the browser UI. Both installers also persist Python's user scripts directory to PATH where possible so `strata` works in new terminals, including agent terminals in Cursor, Claude, and Codex. When installed with workspace init, they also run `strata index` so the local SQLite cache exists before the UI opens. The fallback command is `python -m cxl_strata.cli ...` or `python3 -m cxl_strata.cli ...`.

If a client sees `No such option: --init`, they are running an older installed CLI. Have them rerun the scriptblock installer with `-Init`; that path does not require the root `--init` option.

Workspace initialization can be included during install:

```bash
curl -fsSL https://strata.example.com/install.sh | bash -s -- --org example-org --init
```

```powershell
& ([scriptblock]::Create((irm https://strata.example.com/install.ps1))) -Org example-org -Init
```

See [Client Installation](docs/client-installation.md).

## Cursor, Claude, Codex, And MCP

STRATA has two integration layers:

1. CLI capture: `strata add`, `strata summary`, `strata sync`, `strata search`.
2. MCP retrieval: `strata_search`, `strata_recent`, `strata_get`, `strata_context`.

Cursor:

- Install the CLI.
- Run `python -m cxl_strata.cli --init` to install the project Cursor rule.
- Use `/strata add`, `/strata summary`, and `/strata prune` from Cursor once the rule is installed.
- Configure the MCP server if you want AI context retrieval.

Claude:

- Use the CLI from Claude Code.
- Add project guidance in `CLAUDE.md`.
- Configure MCP for Claude Desktop if desired.

Codex:

- Use the CLI from the agent shell.
- Add project guidance in `AGENTS.md`.
- Ensure `STRATA_API_KEY` or `~/.strata/secrets.json` is available.

MCP config example:

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

See [Client Installation](docs/client-installation.md#mcp-for-ai-context-retrieval) and [mcp/README.md](mcp/README.md).

## Verification Checklist

Server:

```bash
curl -fsS https://strata.example.com/health
curl -fsS https://strata.example.com/v1/client/manifest
```

Client:

```bash
strata whoami
strata add --type general_note --title "Install check" --summary "Verified STRATA."
strata sync
strata search "Install check"
```

Local SQLite and app:

```bash
strata index
strata pull
ls .md/workspace_index.sqlite
strata app --open
```

PowerShell SQLite check:

```powershell
Test-Path .md\workspace_index.sqlite
```

See [Quick Start](docs/quickstart.md#10-smoke-test).

## Troubleshooting

Common issues:

- `strata` not found after install
- Python, pip, or Git missing
- `401 Unauthorized`
- Missing `.strata/config.json`
- Sync failures
- Secret detection `422`
- Local SQLite database missing
- Localhost app opens but looks empty
- MCP tools do not appear
- Apache/Nginx reverse proxy `502`

See [Troubleshooting](docs/troubleshooting.md).

## Security Rules

- Never capture passwords, API keys, private keys, OAuth secrets, raw `.env` values, or unredacted terminal logs.
- Use HTTPS in production.
- Bind Uvicorn to `127.0.0.1` behind Apache or Nginx.
- Give every developer a separate token.
- Store tokens in `STRATA_API_KEY`, `~/.strata/secrets.json`, or `.strata/secrets.json`.
- Do not commit `.strata/secrets.json`, queue files, or failed sync payloads.

See [Security](docs/security.md).

## Event Types

| Type | Use when |
|------|----------|
| `debug_discovery` | A bug cause or surprising behavior is discovered |
| `implementation_note` | Future developers need a useful implementation detail |
| `ops_change` | Server, permission, env, or infrastructure state changed |
| `deployment_note` | A deployment step or gotcha should be remembered |
| `architecture_decision` | A direction was chosen and the why matters |
| `client_assumption` | A client belief or simplification affects future work |
| `planning_warning` | Prior work changes future estimates or sequencing |
| `qa_finding` | QA found a durable regression pattern |
| `general_note` | Nothing else fits |
| `daily_summary` | End-of-day or end-of-flow summary |
| `handoff_upload` | Existing handoff markdown uploaded into STRATA |

## Contributing

```bash
cd api && pip install -r requirements.txt && python -m pytest -q
cd ../cli && pip install -e . && python -m cxl_strata.cli --help
cd ../mcp && pip install -e .
```

Keep changes focused. STRATA should capture less, but capture better.

## License

STRATA is released under the [MIT License](LICENSE).

## Related Docs

- [Quick Start](docs/quickstart.md)
- [Server Setup](docs/server-setup.md)
- [Provisioning](docs/provisioning.md)
- [Client Installation](docs/client-installation.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Architecture](docs/architecture.md)
- [Security](docs/security.md)
- [MCP Server](mcp/README.md)
- [Cursor Commands](cursor-rules/strata-commands.md)
