# Architecture

STRATA has one central service and two workstation-side surfaces.

```text
Developer workstation
  Cursor, Claude, Codex, terminal
      |
      | strata add / strata summary
      v
Repo-local .strata/ JSONL queue
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
Search, recent history, shared docs, MCP retrieval
```

The workstation also keeps a local knowledge layout and SQLite cache:

```text
.md/handoff/  .md/blueprints/  .md/reports/
  + pulled shared docs + agent rules
      |
      | strata init / strata refresh
      | strata index / strata pull
      v
.md/workspace_index.sqlite
      |
      | strata app --open
      v
http://127.0.0.1:8765
```

`strata init` (and installer `--init`) create the `.md/` folders and install Cursor skill/rules/hooks. `strata refresh` and app startup re-apply missing packaged assets after client updates without overwriting existing files.

## Components

| Component | Path | Role |
|-----------|------|------|
| Central API | `api/` | FastAPI app, auth, memory events, shared documents, key management |
| CLI | `cli/` | `strata` command, repo config, JSONL queue, sync/search, local workspace index |
| Workspace scaffold | `cli/cxl_strata/workspace_scaffold.py` | Idempotent `.md/handoff`, `.md/blueprints`, `.md/reports` layout |
| Local app | `cli/cxl_strata/app/` | Browser UI over `.md/workspace_index.sqlite` |
| MCP server | `mcp/` | Stdio MCP server that reads from the central API |
| Local workspace MCP | `cli/cxl_strata/workspace_index/mcp_server.py` | MCP tools over the local SQLite index (`workspace-knowledge`) |
| Agent integrations | `cli/cxl_strata/skills/`, `cli/cxl_strata/rules/`, `cli/cxl_strata/hooks/` | Cursor skill, orchestration rules, hooks; Claude/Codex use CLI, MCP, and their normal instruction files |
| Docs | `docs/` | Server setup, provisioning, client install, security, troubleshooting |

## Storage

| Storage | Location | Purpose |
|---------|----------|---------|
| PostgreSQL | Central server | Shared team memory, documents, API keys |
| `.strata/*.jsonl` | Each repo | Pending, synced, and failed local memory events |
| `.strata/config.json` | Each repo | API URL, org, project, repo, actor hints |
| `~/.strata/global.json` | Workstation | User-level API defaults from installers |
| `~/.strata/secrets.json` | Workstation | User-level API key |
| `.md/handoff/` | Workspace root | Per-project handoff markdown |
| `.md/blueprints/` | Workspace root | Architecture blueprints |
| `.md/reports/` | Workspace root | Audits, digests, and export artifacts |
| `.md/workspace_index.sqlite` | Workspace root | Local searchable cache for the browser app and agent context |
| `.cursor/rules/`, `.cursor/hooks/` | Workspace root | Packaged agent rules and Cursor hooks (installed by init/refresh) |

## API Boundaries

Public bootstrap endpoints:

- `GET /health`
- `GET /install.sh`
- `GET /install.ps1`
- `GET /v1/client/manifest`

Authenticated memory endpoints:

- `GET /v1/whoami`
- `POST /v1/memory-events`
- `GET /v1/memory-events`
- `GET /v1/memory-events/{id}`
- `GET /v1/search`
- `GET /v1/projects/{project_slug}/context`
- `POST /v1/sync/batch`
- `POST /v1/documents`
- `GET /v1/documents`
- `GET /v1/documents/search`
- `GET /v1/documents/{id}`
- `POST /v1/documents/import-batch`

Admin endpoints:

- `POST /v1/api-keys`
- `GET /v1/api-keys`
- `POST /v1/api-keys/{id}/revoke`

## OSS vs Private Deployments

The OSS defaults should stay generic:

| Concern | OSS default |
|---------|-------------|
| API URL | `http://127.0.0.1:8015` |
| Public URL examples | `https://strata.example.com` |
| Deploy model | Self-hosted |
| Database | Operator-managed PostgreSQL |

Organization-specific hosts, deploy paths, service names, and tokens belong in private server config or workspace blueprints, not in committed OSS defaults.
