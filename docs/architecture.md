# Architecture

```text
Developer / Cursor
  /strata add | /strata summary | strata CLI
        ↓
  .strata/events.jsonl  (local queue)
        ↓  Bearer access token
  STRATA API (FastAPI)
        ↓
  PostgreSQL (production) | in-memory (v0 dev scaffold)
        ↓
  Search | MCP (future) | Synapse (future)
```

## OSS vs CXL deployment

| | OSS default |
|---|-------------|
| API URL | `http://127.0.0.1:8015` |
| Deploy | self-hosted |
| DB | operator Postgres |

Organization-specific hosts, deploy paths, and service names belong in private deployment config or workspace blueprints, not in the OSS defaults.

## Workspace bridge

The local workspace explorer (`scripts/workspace_explorer.py`) is a **prototype search UI** over the workspace SQLite index. Long term, STRATA central memory feeds the same UX from the configured central API host.
