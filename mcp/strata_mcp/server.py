#!/usr/bin/env python3
"""MCP stdio server for STRATA project memory retrieval."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

server = Server("strata")


def _api_base() -> str:
    env = os.environ.get("STRATA_API_URL", "").strip()
    if env:
        return env.rstrip("/")
    global_file = Path.home() / ".strata" / "global.json"
    if global_file.is_file():
        data = json.loads(global_file.read_text(encoding="utf-8"))
        url = str(data.get("api_base_url", "")).strip()
        if url:
            return url.rstrip("/")
    return "http://127.0.0.1:8015"


def _api_key() -> str:
    key = os.environ.get("STRATA_API_KEY", "").strip()
    if key:
        return key
    for secrets_path in (Path(".strata") / "secrets.json", Path.home() / ".strata" / "secrets.json"):
        if secrets_path.is_file():
            data = json.loads(secrets_path.read_text(encoding="utf-8"))
            candidate = str(data.get("api_key", "")).strip()
            if candidate and not candidate.startswith("REPLACE_WITH"):
                return candidate
    raise RuntimeError(
        "STRATA_API_KEY is required (env, ~/.strata/secrets.json, or .strata/secrets.json)"
    )


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_api_key()}"}


def _text(data: object) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps(data, indent=2, ensure_ascii=False))]


def _get(path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
    with httpx.Client(timeout=30.0) as client:
        response = client.get(f"{_api_base()}{path}", headers=_headers(), params=params or {})
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else {"results": payload}


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="strata_search",
            description="Search STRATA memory events by keyword across title, summary, tags, and metadata.",
            inputSchema={
                "type": "object",
                "properties": {
                    "q": {"type": "string", "description": "Search query"},
                    "project": {"type": "string", "description": "Optional project slug filter"},
                    "limit": {"type": "integer", "default": 20, "minimum": 1, "maximum": 200},
                },
                "required": ["q"],
            },
        ),
        Tool(
            name="strata_recent",
            description="Recent STRATA memory events for a project within the last N days.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project": {"type": "string", "description": "Optional project slug filter"},
                    "days": {"type": "integer", "default": 7, "minimum": 1, "maximum": 365},
                    "limit": {"type": "integer", "default": 20, "minimum": 1, "maximum": 200},
                },
            },
        ),
        Tool(
            name="strata_get",
            description="Fetch a single STRATA memory event by id.",
            inputSchema={
                "type": "object",
                "properties": {"event_id": {"type": "string"}},
                "required": ["event_id"],
            },
        ),
        Tool(
            name="strata_context",
            description="Project context bundle: recent events and counts for agent prompts.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project": {"type": "string", "description": "Project slug"},
                    "limit": {"type": "integer", "default": 10, "minimum": 1, "maximum": 50},
                },
                "required": ["project"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    if name == "strata_search":
        return _text(
            _get(
                "/v1/search",
                params={
                    "q": arguments["q"],
                    "project": arguments.get("project"),
                    "limit": arguments.get("limit", 20),
                },
            )
        )
    if name == "strata_recent":
        params: dict[str, Any] = {
            "days": arguments.get("days", 7),
            "limit": arguments.get("limit", 20),
        }
        if arguments.get("project"):
            params["project"] = arguments["project"]
        return _text(_get("/v1/memory-events", params=params))
    if name == "strata_get":
        return _text(_get(f"/v1/memory-events/{arguments['event_id']}"))
    if name == "strata_context":
        project = arguments["project"]
        return _text(
            _get(
                f"/v1/projects/{project}/context",
                params={"limit": arguments.get("limit", 10)},
            )
        )
    raise ValueError(f"Unknown tool: {name}")


async def run() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main() -> None:
    import asyncio

    asyncio.run(run())


if __name__ == "__main__":
    main()
