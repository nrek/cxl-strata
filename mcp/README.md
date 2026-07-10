# STRATA MCP server

Stdio MCP server that calls the STRATA HTTP API for AI context retrieval.

For the **local** SQLite index (handoffs, blueprints, graph neighbors, `handoff_write`), use the `workspace-knowledge` server shipped with the CLI package — see [Client Installation](../docs/client-installation.md#cursor).

## Environment

```bash
export STRATA_API_URL=https://strata.example.com
export STRATA_API_KEY=strata_live_...
```

Local API development:

```bash
export STRATA_API_URL=http://127.0.0.1:8015
export STRATA_API_KEY=strata_dev_...
```

## Install

```bash
cd mcp
pip install -e .
```

The one-line client installers install this package automatically.

## Cursor MCP config

Recommended: both the central API server and the local workspace index:

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

## Tools (central API)

| Tool | Description |
|------|-------------|
| `strata_search` | Full-text search across memory events |
| `strata_recent` | Recent events for a project (optional days filter) |
| `strata_get` | Fetch one memory event by id |
| `strata_context` | Project summary bundle for agent prompts |
