#!/usr/bin/env python3
"""MCP stdio server for workspace knowledge index."""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Allow running as script: python scripts/workspace_knowledge/mcp_server.py
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_ROOT / "scripts"))

from mcp.server import Server  # noqa: E402
from mcp.server.stdio import stdio_server  # noqa: E402
from mcp.types import TextContent, Tool  # noqa: E402

from workspace_knowledge import db, plan_ops, queries, storage  # noqa: E402
from workspace_knowledge.indexer import index_all  # noqa: E402

server = Server("workspace-knowledge")


def _text(data: object) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps(data, indent=2, ensure_ascii=False))]


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="knowledge_recent",
            description=(
                "Recent workspace docs for a project. Handoffs use a rolling "
                "48-hour activity window (not calendar days); carries forward over "
                "weekends up to 7 days when the strict window is empty."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project": {"type": "string"},
                    "hours": {
                        "type": "integer",
                        "default": 48,
                        "description": "Rolling wall-clock hours of handoff activity",
                    },
                    "kind": {
                        "type": "string",
                        "enum": ["handoff", "blueprint", "plan", "rule"],
                    },
                    "limit": {"type": "integer", "default": 10},
                },
            },
        ),
        Tool(
            name="knowledge_search",
            description="Full-text search across indexed workspace documents.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "project": {"type": "string"},
                    "kind": {"type": "string"},
                    "plan_status": {"type": "string"},
                    "limit": {"type": "integer", "default": 15},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="knowledge_get",
            description="Fetch indexed document metadata and body by repo-relative path.",
            inputSchema={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        ),
        Tool(
            name="knowledge_blueprint",
            description="Resolve blueprint for a project alias (synq-forge, v5.prompli.com, etc.).",
            inputSchema={
                "type": "object",
                "properties": {
                    "project": {"type": "string"},
                    "max_chars": {"type": "integer", "default": 2000},
                },
                "required": ["project"],
            },
        ),
        Tool(
            name="plan_list",
            description="List plans filtered by status, project, or Linear task id.",
            inputSchema={
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": [
                            "draft",
                            "backlog",
                            "in_queue",
                            "in_progress",
                            "done",
                        ],
                    },
                    "project": {"type": "string"},
                    "linear_task_id": {"type": "string"},
                    "limit": {"type": "integer", "default": 50},
                },
            },
        ),
        Tool(
            name="plan_get",
            description="Get plan metadata, todos summary, and overview snippet by path.",
            inputSchema={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        ),
        Tool(
            name="plan_set_status",
            description="Update plan status in frontmatter, move file to status folder, reindex.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "status": {
                        "type": "string",
                        "enum": [
                            "draft",
                            "backlog",
                            "in_queue",
                            "in_progress",
                            "done",
                        ],
                    },
                    "linear_task_id": {"type": "string"},
                },
                "required": ["path", "status"],
            },
        ),
        Tool(
            name="handoff_write",
            description=(
                "Create or append a handoff log as a markdown file under "
                ".md/handoff/<project>/ and index it in SQLite (storage=file). "
                "New Agent tab: use project to create one file for the tab. "
                "Same Agent tab: use path to append at the END of that file (auto ## iN). "
                "Never edit handoff files with Write/StrReplace — use this tool only. "
                "Do not include ## iN or --- in append content; the writer adds them."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project": {"type": "string"},
                    "content": {"type": "string"},
                    "path": {
                        "type": "string",
                        "description": "Existing handoff path to append to",
                    },
                },
                "required": ["content"],
            },
        ),
        Tool(
            name="knowledge_reindex",
            description="Rebuild or refresh the workspace SQLite index from markdown sources.",
            inputSchema={
                "type": "object",
                "properties": {"full": {"type": "boolean", "default": True}},
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    args = arguments or {}
    with db.connect() as conn:
        db.init_db(conn)
        if name == "knowledge_recent":
            hours = int(args.get("hours", 48))
            project = args.get("project")
            kind = args.get("kind")
            limit = int(args.get("limit", 10))
            if project and kind == "handoff":
                data = queries.handoffs_recent_available(
                    conn, project, hours=hours, limit=limit
                )
                data["sections"] = queries.sections_recent_available(
                    conn, project, hours=hours, limit=limit
                )
            else:
                data = queries.knowledge_recent(
                    conn,
                    project=project,
                    hours=hours,
                    kind=kind,
                    limit=limit,
                )
            return _text(data)
        if name == "knowledge_search":
            return _text(
                queries.knowledge_search(
                    conn,
                    query=args["query"],
                    project=args.get("project"),
                    kind=args.get("kind"),
                    plan_status=args.get("plan_status"),
                    limit=int(args.get("limit", 15)),
                )
            )
        if name == "knowledge_get":
            return _text(queries.knowledge_get(conn, args["path"]))
        if name == "knowledge_blueprint":
            return _text(
                queries.knowledge_blueprint(
                    conn,
                    args["project"],
                    max_chars=int(args.get("max_chars", 2000)),
                )
            )
        if name == "plan_list":
            return _text(
                queries.plan_list(
                    conn,
                    status=args.get("status"),
                    project=args.get("project"),
                    linear_task_id=args.get("linear_task_id"),
                    limit=int(args.get("limit", 50)),
                )
            )
        if name == "plan_get":
            return _text(queries.plan_get(conn, args["path"]))
        if name == "plan_set_status":
            return _text(
                plan_ops.set_plan_status(
                    args["path"],
                    args["status"],
                    linear_task_id=args.get("linear_task_id"),
                )
            )
        if name == "handoff_write":
            project = args.get("project")
            if not project and not args.get("path"):
                return _text({"error": "Provide project or path"})
            return _text(
                storage.handoff_append(
                    conn,
                    project=project or "",
                    content=args["content"],
                    path=args.get("path"),
                )
            )
        if name == "knowledge_reindex":
            return _text(index_all())
    return _text({"error": f"Unknown tool: {name}"})


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
