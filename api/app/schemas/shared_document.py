from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class SharedDocumentCreate(BaseModel):
    path: str
    kind: str = Field(..., pattern="^(handoff|blueprint|plan|rule|memory_event)$")
    project_slug: str | None = None
    repo_name: str | None = None
    title: str | None = None
    body: str
    body_hash: str | None = None
    source: str = "workspace_index"
    storage_state: str = "file"
    visibility: str = "internal"
    plan_status: str | None = None
    linear_task_id: str | None = None
    published_at: datetime | None = None
    sections: list[dict[str, Any]] | None = None


class SharedDocumentOut(BaseModel):
    id: str
    organization_id: str
    project_slug: str | None
    repo_name: str | None
    kind: str
    title: str | None
    path: str
    body: str
    body_hash: str
    source: str
    storage_state: str
    visibility: str
    plan_status: str | None
    linear_task_id: str | None
    author_name: str
    author_email: str | None
    actor_id: str | None
    published_at: datetime | None
    shared_at: datetime | None
    created_at: datetime
    updated_at: datetime


class DocumentCommentCreate(BaseModel):
    body: str
    author_name: str | None = None
    author_email: str | None = None
    created_at: datetime | None = None


class DocumentCommentOut(BaseModel):
    id: str
    document_id: str
    author_name: str
    author_email: str | None
    body: str
    created_at: datetime


class SharedDocumentImportBatchIn(BaseModel):
    documents: list[SharedDocumentCreate]


class SharedDocumentImportBatchOut(BaseModel):
    synced: list[dict[str, str]]
    failed: list[dict[str, str]]
