# SIBYL

**SIBYL** is an open-source shared project memory system for technical teams.

Developers capture durable notes, handoffs, and daily summaries from local workspaces. A central API stores that memory so the whole team can search it later. SIBYL is designed to preserve **what changed, why, and how it was fixed** — not raw chat logs or terminal surveillance.

```text
Developer machine (Cursor, Claude, Codex, or terminal)
    |
    |  sibyl add | sibyl summary | /sibyl add | /sibyl summary
    v
Local .sibyl/ queue (JSONL)
    |
    |  HTTPS + Bearer access token
    v
Central SIBYL API (FastAPI + Uvicorn)
    |
    v
PostgreSQL (production target; v0 scaffold may use in-memory store)
    |
    v
Search, recent history, future MCP retrieval
```

| | |
|---|---|
| **Stack** | FastAPI, PostgreSQL, Python CLI (Typer) |
| **Local API** | `http://127.0.0.1:8015` |
| **CLI command** | `sibyl` |
| **License** | [MIT](LICENSE) |

> **v0 status:** This repository is an early OSS scaffold. The API, CLI, and capture flow work end-to-end for local development. Production Postgres migrations and hashed per-user API keys are the next milestones. See [Roadmap](#roadmap) below.

---

## Table of contents

1. [Why SIBYL exists](#why-sibyl-exists)
2. [Quickstart (local)](#quickstart-local)
3. [API deployment (central server)](#api-deployment-central-server)
4. [Client integration (Cursor, Claude, Codex)](#client-integration-cursor-claude-codex)
5. [Troubleshooting](#troubleshooting)
6. [License](#license)
7. [Contributing](#contributing)
8. [Security](#security)
9. [Roadmap](#roadmap)

---

## Why SIBYL exists

Teams lose context between sessions. SIBYL captures durable project knowledge:

- What changed and why
- Debugging discoveries and fixes
- Deployment and ops notes
- Architecture decisions
- Client assumptions and planning warnings

Each developer uses their own **access token** (`sibyl_live_...` or `sibyl_dev_...`). Tokens authenticate to the central API. Secrets stay in `SIBYL_API_KEY` or `.sibyl/secrets.json` — never in git.

**SIBYL is not:** a task manager, a chat-log dump, a secret store, or a replacement for Linear/GitHub Issues.

---

## Quickstart (local)

### Prerequisites

- Python 3.10+
- PostgreSQL 16+ (required for persistence; bootstrap env keys work without seeding hashed keys)
- A Linux or macOS host for server deployment (Windows works for local CLI dev)

### 1. Run the API locally

```bash
git clone https://github.com/YOUR_ORG/cxl-sibyl.git
cd cxl-sibyl/api

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env — set DATABASE_URL, API_KEY_PEPPER, and SIBYL_API_KEYS for bootstrap dev auth

# Create database (once), then apply schema:
# createdb sibyl   # or use your Postgres admin flow
alembic upgrade head
python scripts/seed_key.py       # optional — creates hashed per-user key (shown once)

uvicorn app.main:app --reload --host 127.0.0.1 --port 8015
```

Verify:

```bash
curl http://127.0.0.1:8015/health
# {"status":"ok","service":"sibyl-api","storage":"postgres"}
```

### 2. Install the CLI

```bash
cd ../cli
pip install -e .

export SIBYL_API_KEY="sibyl_dev_example"   # must match a key in SIBYL_API_KEYS on the server
```

### 3. Initialize a repo

From any project directory:

```bash
sibyl init \
  --api http://127.0.0.1:8015 \
  --org my-org \
  --project my-project \
  --repo my-repo

sibyl whoami
```

This creates `.sibyl/config.json` and empty JSONL queue files. Add `.sibyl/secrets.json` or keep using `SIBYL_API_KEY` in your shell profile.

### 4. Capture and sync memory

```bash
# Structured note
sibyl add \
  --type debug_discovery \
  --title "OAuth redirect used stale domain" \
  --summary "Redirect issue was caused by stale runtime env configuration." \
  --environment staging \
  --tags oauth,env,redirect

# End-of-day summary
sibyl summary --text "Shipped auth fix; verified staging redirect URIs."

# Push local queue to central API
sibyl sync

# Search central memory
sibyl search "oauth redirect"
sibyl recent --days 7
```

### Repository layout

```text
cxl-sibyl/
  api/              FastAPI central memory API
  cli/              sibyl Typer CLI (pip install -e cli)
  cursor-rules/     Agent command docs for Cursor and other AI clients
  docs/             Architecture and security notes
  LICENSE
  README.md
```

---

## API deployment (central server)

SIBYL runs as a **FastAPI app behind a reverse proxy**. The API binds to localhost; Apache or Nginx terminates TLS and proxies to Uvicorn.

**Recommended production layout:**

```text
Internet
    |
    v
Apache or Nginx (TLS, port 443)
    |
    v
127.0.0.1:8015  (Uvicorn / systemd)
    |
    v
PostgreSQL
```

Replace `sibyl.example.com`, paths, and token values with your own.

### Server prerequisites

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip postgresql nginx   # or apache2
```

Create a dedicated user and app directory:

```bash
sudo useradd --system --home /opt/cxl-sibyl --shell /usr/sbin/nologin sibyl || true
sudo mkdir -p /opt/cxl-sibyl
sudo chown sibyl:sibyl /opt/cxl-sibyl
```

### Deploy application code

```bash
sudo -u sibyl git clone https://github.com/YOUR_ORG/cxl-sibyl.git /opt/cxl-sibyl
cd /opt/cxl-sibyl/api

sudo -u sibyl python3 -m venv .venv
sudo -u sibyl .venv/bin/pip install -r requirements.txt
sudo -u sibyl cp .env.example .env
```

Edit `/opt/cxl-sibyl/api/.env`:

```env
SIBYL_ENV=production
SIBYL_API_BASE_URL=https://sibyl.example.com
DATABASE_URL=postgresql+psycopg://sibyl:STRONG_PASSWORD@127.0.0.1:5432/sibyl
API_KEY_PEPPER=generate-a-long-random-string
SIBYL_API_KEYS=sibyl_live_team_key_one,sibyl_live_team_key_two
```

> **v0 note:** Set `SIBYL_API_KEYS` to comma-separated tokens your team will use. Only listed tokens are accepted. Hashed per-user keys in Postgres are planned for a later release.

Create the database (when Postgres migrations are available):

```bash
sudo -u postgres createuser sibyl
sudo -u postgres createdb -O sibyl sibyl
# Future: cd /opt/cxl-sibyl/api && .venv/bin/alembic upgrade head
cd /opt/cxl-sibyl/api && .venv/bin/alembic upgrade head
python scripts/seed_key.py
```

### systemd service

Create `/etc/systemd/system/cxl-sibyl-api.service`:

```ini
[Unit]
Description=SIBYL central memory API
After=network.target postgresql.service

[Service]
User=sibyl
Group=sibyl
WorkingDirectory=/opt/cxl-sibyl/api
EnvironmentFile=/opt/cxl-sibyl/api/.env
ExecStart=/opt/cxl-sibyl/api/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8015
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable cxl-sibyl-api
sudo systemctl start cxl-sibyl-api
sudo systemctl status cxl-sibyl-api
curl http://127.0.0.1:8015/health
```

### Option A: Nginx reverse proxy

Create `/etc/nginx/sites-available/sibyl`:

```nginx
server {
    listen 80;
    server_name sibyl.example.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name sibyl.example.com;

    ssl_certificate     /etc/letsencrypt/live/sibyl.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/sibyl.example.com/privkey.pem;

    client_max_body_size 2m;

    location / {
        proxy_pass http://127.0.0.1:8015;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Enable and reload:

```bash
sudo ln -sf /etc/nginx/sites-available/sibyl /etc/nginx/sites-enabled/sibyl
sudo nginx -t
sudo systemctl reload nginx
curl -fsS https://sibyl.example.com/health
```

Obtain TLS certificates with Certbot if needed:

```bash
sudo certbot --nginx -d sibyl.example.com
```

### Option B: Apache reverse proxy

Enable modules:

```bash
sudo a2enmod proxy proxy_http ssl headers rewrite
```

Create `/etc/apache2/sites-available/sibyl.conf`:

```apache
<VirtualHost *:80>
    ServerName sibyl.example.com
    Redirect permanent / https://sibyl.example.com/
</VirtualHost>

<VirtualHost *:443>
    ServerName sibyl.example.com

    SSLEngine on
    SSLCertificateFile      /etc/letsencrypt/live/sibyl.example.com/fullchain.pem
    SSLCertificateKeyFile   /etc/letsencrypt/live/sibyl.example.com/privkey.pem

    ProxyPreserveHost On
    RequestHeader set X-Forwarded-Proto "https"

    ProxyPass        / http://127.0.0.1:8015/
    ProxyPassReverse / http://127.0.0.1:8015/

    ErrorLog ${APACHE_LOG_DIR}/sibyl-error.log
    CustomLog ${APACHE_LOG_DIR}/sibyl-access.log combined
</VirtualHost>
```

Enable and reload:

```bash
sudo a2ensite sibyl
sudo apache2ctl configtest
sudo systemctl reload apache2
curl -fsS https://sibyl.example.com/health
```

### Deploy updates

```bash
cd /opt/cxl-sibyl
sudo -u sibyl git pull
cd api
sudo -u sibyl .venv/bin/pip install -r requirements.txt
alembic upgrade head
python scripts/seed_key.py
sudo systemctl restart cxl-sibyl-api
```

### API endpoints (v1)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/health` | No | Liveness check |
| GET | `/v1/whoami` | Bearer | Verify token and scopes |
| POST | `/v1/memory-events` | Bearer | Create one memory event |
| GET | `/v1/memory-events` | Bearer | List events (optional `?project=`) |
| GET | `/v1/memory-events/{id}` | Bearer | Fetch one event |
| GET | `/v1/search` | Bearer | Search (`?q=` required; optional `?project=`) |
| POST | `/v1/sync/batch` | Bearer | Batch sync from CLI queue |

All authenticated requests use:

```http
Authorization: Bearer sibyl_live_your_token_here
```

---

## Client integration (Cursor, Claude, Codex)

SIBYL has two integration layers:

1. **CLI** — works from any terminal (`sibyl add`, `sibyl summary`, `sibyl sync`)
2. **Agent rules** — tell AI assistants when and how to capture memory

Copy [cursor-rules/sibyl-commands.md](cursor-rules/sibyl-commands.md) into your project or IDE config.

### Per-developer setup (all clients)

In each repo that should report to SIBYL:

```bash
pip install -e /path/to/cxl-sibyl/cli   # or: pip install cxl-sibyl when published

export SIBYL_API_KEY="sibyl_live_your_personal_token"

sibyl init \
  --api https://sibyl.example.com \
  --org your-org \
  --project your-project \
  --repo your-repo-name \
  --actor-name "Your Name" \
  --actor-email you@example.com
```

Add to the repo `.gitignore`:

```gitignore
.sibyl/secrets.json
.sibyl/events.jsonl
.sibyl/synced.jsonl
.sibyl/failed.jsonl
```

Optional: store the token in `.sibyl/secrets.json` (gitignored):

```json
{
  "api_key": "sibyl_live_your_personal_token"
}
```

### Cursor

**Slash commands (natural language in chat):**

| Command | What it does |
|---------|----------------|
| `/sibyl add` | Capture durable memory or upload an existing handoff markdown file |
| `/sibyl summary` | Upload an end-of-day or end-of-flow summary for the current project |

**Install the rule:**

Copy the contents of [cursor-rules/sibyl-commands.md](cursor-rules/sibyl-commands.md) into one of:

- `.cursor/rules/sibyl-memory-capture.mdc` (project rule), or
- Your user-level Cursor rules

The rule instructs the agent to:

1. Read `.sibyl/config.json` for project/repo context
2. Distill the session into a concise `sibyl add` command (no secrets, no raw chat dump)
3. Queue locally, then run `sibyl sync` when you confirm

**Example prompts:**

```text
/sibyl add — we fixed OAuth redirect by aligning APP_URL with Google console settings
/sibyl summary — shipped staging deploy fix and verified Apache proxy headers
```

### MCP (AI context retrieval)

The MCP server exposes SIBYL memory to Cursor, Claude Desktop, and other MCP clients.

**Install:**

```bash
cd mcp
pip install -e .
```

**Cursor MCP config** (`.cursor/mcp.json` or Cursor settings):

```json
{
  "mcpServers": {
    "sibyl": {
      "command": "python",
      "args": ["-m", "sibyl_mcp.server"],
      "env": {
        "SIBYL_API_URL": "http://127.0.0.1:8015",
        "SIBYL_API_KEY": "sibyl_dev_your_token"
      }
    }
  }
}
```

**Tools:** `sibyl_search`, `sibyl_recent`, `sibyl_get`, `sibyl_context`

See [mcp/README.md](mcp/README.md) for full tool schemas and troubleshooting.

### Claude (Claude Code / Claude Desktop with project files)

Claude does not have native slash commands for SIBYL. Use the CLI plus a project instruction file.

**1. Add project instructions**

Create or extend `CLAUDE.md` in the repo root:

```markdown
## SIBYL project memory

When durable project knowledge is discovered (bug root cause, deploy fix, architecture
decision, client assumption), propose capturing it with the SIBYL CLI.

Never include secrets, API keys, or raw .env values.

Example:
  sibyl add --type debug_discovery --title "..." --summary "..." --tags tag1,tag2
  sibyl sync

For end-of-session summaries:
  sibyl summary --text "..." --sync
```

**2. Ensure `.sibyl/config.json` exists** (from `sibyl init`).

**3. Set `SIBYL_API_KEY`** in your shell or `.sibyl/secrets.json` before asking Claude to run capture commands.

Claude Code can run terminal commands directly; Desktop users can copy the proposed `sibyl` commands from chat.

### Codex (OpenAI Codex CLI / agent environments)

Same pattern as Claude: CLI + instructions file.

**1. Add `AGENTS.md` or extend existing agent instructions:**

```markdown
## SIBYL memory capture

After meaningful work (fixes, deploy changes, decisions), suggest:

  sibyl add --type <event_type> --title "..." --summary "..."
  sibyl sync

Event types: debug_discovery, implementation_note, ops_change, deployment_note,
architecture_decision, client_assumption, planning_warning, qa_finding, general_note.

Do not capture secrets or full chat logs.
```

**2. Initialize SIBYL in the repo** (`sibyl init`).

**3. Export `SIBYL_API_KEY`** in the environment where Codex runs commands.

### Event types reference

| Type | Use when |
|------|----------|
| `debug_discovery` | Bug cause or unexpected behavior found |
| `implementation_note` | Useful dev detail future devs should know |
| `ops_change` | Server, permissions, env, infrastructure change |
| `deployment_note` | Deploy-specific steps or gotchas |
| `architecture_decision` | Direction chosen and why |
| `client_assumption` | Client belief that affects estimates or scope |
| `planning_warning` | Prior work suggests future estimates should change |
| `qa_finding` | Durable QA/regression pattern |
| `general_note` | Nothing else fits |
| `daily_summary` | End-of-day or end-of-flow summary (`sibyl summary`) |
| `handoff_upload` | Existing handoff markdown uploaded via `--handoff-path` |

---

## Troubleshooting

### `401 Unauthorized` or `Unknown access token`

- Confirm `SIBYL_API_KEY` on the client matches a token listed in server `SIBYL_API_KEYS`
- Token must start with `sibyl_live_` or `sibyl_dev_`
- Check for trailing whitespace in `.env` or shell export
- Test: `curl -H "Authorization: Bearer YOUR_TOKEN" https://sibyl.example.com/v1/whoami`

### `Missing .sibyl/config.json`

Run `sibyl init` from the repo root:

```bash
sibyl init --api https://sibyl.example.com --org ORG --project PROJECT --repo REPO
```

### `sibyl sync` reports failures or nothing syncs

- Verify API is reachable: `curl https://sibyl.example.com/health`
- Check pending queue: `cat .sibyl/events.jsonl`
- Inspect failures: `cat .sibyl/failed.jsonl`
- Secret-like content is rejected by design; redact credentials and retry
- After a successful sync, synced rows move to `.sibyl/synced.jsonl` and leave the pending queue

### `422` — payload appears to contain secrets

SIBYL rejects obvious secret patterns (private keys, `API_KEY=...`, Stripe-style keys, AWS access key IDs). Describe the **setting** without recording the value:

```text
Good:  OAuth depends on GOOGLE_CLIENT_ID and APP_URL alignment.
Bad:   GOOGLE_CLIENT_SECRET=actual-secret-value
```

### `sibyl` command not found after pip install

- Ensure the install venv/bin directory is on `PATH`, or run: `python -m cxl_sibyl.cli --help`
- Reinstall: `pip install -e cli` from the repo

### API health OK but search returns nothing

- Confirm events were synced: `sibyl sync` then `sibyl search "your terms"`
- v0 search is substring match over title, summary, details, tags, environment, event_type, project, and repo
- **v0 in-memory store:** restarting the API process clears memory until Postgres persistence lands

### Reverse proxy returns 502 Bad Gateway

- Check Uvicorn is running: `systemctl status cxl-sibyl-api`
- Confirm bind address: API must listen on `127.0.0.1:8015` (or update proxy target)
- Check logs: `journalctl -u cxl-sibyl-api -n 50`
- Nginx: `sudo nginx -t` — Apache: `sudo apache2ctl configtest`

### SSL / certificate errors from CLI

- Use `https://` in `sibyl init --api` and in `.sibyl/config.json`
- Ensure the certificate covers the hostname clients use
- For local dev only, use `http://127.0.0.1:8015` without TLS

### Windows-specific notes

- Activate venv: `.venv\Scripts\activate`
- Prefer `python -m cxl_sibyl.cli` if the `sibyl.exe` shim is not on PATH
- Use `set SIBYL_API_KEY=...` in cmd or `$env:SIBYL_API_KEY="..."` in PowerShell

---

## License

SIBYL is released under the [MIT License](LICENSE).

Copyright (c) 2026 Craft & Logic

You may use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, subject to the conditions in the LICENSE file. The above copyright notice and permission notice must be included in all copies or substantial portions.

---

## Contributing

Contributions are welcome. SIBYL is early-stage; focused PRs are easier to review than large rewrites.

### How to contribute

1. **Fork** the repository on GitHub
2. **Create a branch** from `main`: `git checkout -b feature/short-description`
3. **Make focused changes** — one concern per PR when possible
4. **Test locally:**
   ```bash
   cd api && pip install -r requirements.txt && python -m pytest -q
   cd ../cli && pip install -e . && python -m cxl_sibyl.cli --help
   cd ../mcp && pip install -e .
   ```
5. **Open a pull request** with:
   - What changed and why
   - How you tested it
   - Any deployment or migration notes

### Good first issues

- GitHub release / PyPI publish for CLI and MCP packages
- Full-text search index (Postgres `tsvector` or external search)
- Sync conflict resolution and deduplication policies
- Documentation improvements and deployment examples

### Code guidelines

- Keep SIBYL **small and boring** — capture less, but capture better
- Never add features that store secrets or raw chat logs by default
- Match existing Python style (type hints, minimal dependencies)
- OSS defaults stay generic; org-specific hosts belong in private deploy config

### Security reports

If you find a security issue, **do not** open a public GitHub issue with exploit details. Contact the maintainers privately.

### Questions

Open a GitHub Discussion or Issue for design questions, deployment help, or integration ideas.

---

## Security

- Never store passwords, API keys, private keys, or raw `.env` values in memory events
- Each developer should have their own access token
- Use HTTPS in production; bind the API to localhost behind a reverse proxy
- See [docs/security.md](docs/security.md) for full guidance

---

## Roadmap

| Milestone | Status |
|-----------|--------|
| FastAPI app + health endpoint | Done (v0) |
| CLI: init, add, summary, sync, search, recent, whoami | Done (v0) |
| Bearer token auth (configured keys) | Done (v0) |
| Secret pattern rejection | Done (v0) |
| PostgreSQL + Alembic migrations | Done (v0.2) |
| Hashed per-user API keys | Done (v0.2) |
| MCP retrieval for AI context | Done (v0.2) |
| GitHub release / PyPI publish | Planned |

---

## Related docs

- [cursor-rules/sibyl-commands.md](cursor-rules/sibyl-commands.md) — agent behavior for `/sibyl add` and `/sibyl summary`
- [docs/architecture.md](docs/architecture.md) — system overview
- [docs/security.md](docs/security.md) — token and content safety rules
- [mcp/README.md](mcp/README.md) — MCP server for AI context retrieval
