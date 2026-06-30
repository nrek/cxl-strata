from __future__ import annotations

from pydantic import BaseModel, Field


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    actor_id: str | None = None
    scopes: list[str] = Field(default_factory=lambda: ["memory:read", "memory:write", "memory:sync"])
    prefix: str = "sibyl_dev_"


class ApiKeyOut(BaseModel):
    id: str
    organization_id: str
    actor_id: str | None
    name: str
    key_prefix: str
    scopes: list[str]
    is_active: bool
    last_used_at: str | None = None
    created_at: str | None = None
    revoked_at: str | None = None


class ApiKeyCreated(ApiKeyOut):
    raw_key: str
