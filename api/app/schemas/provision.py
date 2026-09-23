from __future__ import annotations

from pydantic import BaseModel, Field


class TeamProvisionIn(BaseModel):
    slug: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=255)
    actor_name: str = Field(default="team-owner", min_length=1, max_length=255)
    actor_email: str | None = Field(default=None, max_length=255)
    key_name: str = Field(default="scylla-team", min_length=1, max_length=255)
    prefix: str = Field(default="strata_live_", pattern=r"^strata_(dev|live)_$")


class TeamProvisionOrg(BaseModel):
    id: str
    slug: str
    name: str


class TeamProvisionActor(BaseModel):
    id: str
    name: str
    email: str | None = None


class TeamProvisionOut(BaseModel):
    organization: TeamProvisionOrg
    actor: TeamProvisionActor
    api_key: str
