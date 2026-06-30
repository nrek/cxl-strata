from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

EventType = Literal[
    "debug_discovery",
    "implementation_note",
    "ops_change",
    "deployment_note",
    "architecture_decision",
    "client_assumption",
    "planning_warning",
    "qa_finding",
    "general_note",
    "daily_summary",
    "handoff_upload",
]

Visibility = Literal["private", "internal", "client_safe", "admin_only"]
Confidence = Literal["observed", "confirmed", "assumed", "needs_review", "superseded"]


class MemoryEventCreate(BaseModel):
    project_slug: str
    repo_name: str | None = None
    event_type: EventType
    title: str = Field(max_length=500)
    summary: str
    details: str | None = None
    environment: str | None = None
    visibility: Visibility = "internal"
    tags: list[str] = Field(default_factory=list)
    related_files: list[str] = Field(default_factory=list)
    confidence: Confidence = "observed"
    source: str = "local_capture"
    source_ref: str | None = None
    occurred_at: datetime | None = None


class MemoryEventOut(MemoryEventCreate):
    id: str
    created_at: datetime


class SyncBatchIn(BaseModel):
    workspace_id: str | None = None
    events: list[dict]


class SyncBatchOut(BaseModel):
    synced: list[dict]
    failed: list[dict]
