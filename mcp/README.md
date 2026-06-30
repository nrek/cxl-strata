# STRATA MCP server

Stdio MCP server that calls the STRATA HTTP API for AI context retrieval.

## Environment

```bash
export STRATA_API_URL=http://127.0.0.1:8015
export STRATA_API_KEY=strata_dev_...
```

## Install

```bash
cd mcp
pip install -e .
```

## Cursor MCP config

```json
{
  "mcpServers": {
    "strata": {
      "command": "python",
      "args": ["-m", "strata_mcp.server"],
      "env": {
        "STRATA_API_URL": "http://127.0.0.1:8015",
        "STRATA_API_KEY": "strata_dev_your_token"
      }
    }
  }
}
```

## Tools

| Tool | Description |
|------|-------------|
| `strata_search` | Full-text search across memory events |
| `strata_recent` | Recent events for a project (optional days filter) |
| `strata_get` | Fetch one memory event by id |
| `strata_context` | Project summary bundle for agent prompts |
