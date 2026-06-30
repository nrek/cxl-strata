# SIBYL MCP server

Stdio MCP server that calls the SIBYL HTTP API for AI context retrieval.

## Environment

```bash
export SIBYL_API_URL=http://127.0.0.1:8015
export SIBYL_API_KEY=sibyl_dev_...
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

## Tools

| Tool | Description |
|------|-------------|
| `sibyl_search` | Full-text search across memory events |
| `sibyl_recent` | Recent events for a project (optional days filter) |
| `sibyl_get` | Fetch one memory event by id |
| `sibyl_context` | Project summary bundle for agent prompts |
