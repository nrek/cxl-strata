from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    projects: Mapped[list["Project"]] = relationship(back_populates="organization")
    actors: Mapped[list["Actor"]] = relationship(back_populates="organization")
    api_keys: Mapped[list["ApiKey"]] = relationship(back_populates="organization")


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    slug: Mapped[str] = mapped_column(String(120), index=True)
    name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    organization: Mapped["Organization"] = relationship(back_populates="projects")
    repos: Mapped[list["Repo"]] = relationship(back_populates="project")
    memory_events: Mapped[list["MemoryEvent"]] = relationship(back_populates="project")


class Repo(Base):
    __tablename__ = "repos"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    project: Mapped["Project"] = relationship(back_populates="repos")
    memory_events: Mapped[list["MemoryEvent"]] = relationship(back_populates="repo")


class Actor(Base):
    __tablename__ = "actors"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    organization: Mapped["Organization"] = relationship(back_populates="actors")
    api_keys: Mapped[list["ApiKey"]] = relationship(back_populates="actor")
    memory_events: Mapped[list["MemoryEvent"]] = relationship(back_populates="actor")


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("actors.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(255))
    key_prefix: Mapped[str] = mapped_column(String(32), index=True)
    key_hash: Mapped[str] = mapped_column(String(64))
    scopes_json: Mapped[str] = mapped_column(Text, default="[]")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    organization: Mapped["Organization"] = relationship(back_populates="api_keys")
    actor: Mapped["Actor | None"] = relationship(back_populates="api_keys")


class MemoryEvent(Base):
    __tablename__ = "memory_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    repo_id: Mapped[str | None] = mapped_column(ForeignKey("repos.id"), nullable=True)
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("actors.id"), nullable=True)

    project_slug: Mapped[str] = mapped_column(String(120), index=True)
    repo_name: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(500))
    summary: Mapped[str] = mapped_column(Text)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    environment: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    visibility: Mapped[str] = mapped_column(String(32), default="internal")
    source: Mapped[str] = mapped_column(String(64), default="local_capture")
    source_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[str] = mapped_column(String(32), default="observed")
    tags_json: Mapped[str] = mapped_column(Text, default="[]")
    related_files_json: Mapped[str] = mapped_column(Text, default="[]")
    local_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    organization: Mapped["Organization"] = relationship()
    project: Mapped["Project"] = relationship(back_populates="memory_events")
    repo: Mapped["Repo | None"] = relationship(back_populates="memory_events")
    actor: Mapped["Actor | None"] = relationship(back_populates="memory_events")


class SharedDocument(Base):
    __tablename__ = "shared_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("actors.id"), nullable=True, index=True)

    project_slug: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    repo_name: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    path: Mapped[str] = mapped_column(Text, index=True)
    body: Mapped[str] = mapped_column(Text)
    body_hash: Mapped[str] = mapped_column(String(64), index=True)
    source: Mapped[str] = mapped_column(String(64), default="workspace_index")
    storage_state: Mapped[str] = mapped_column(String(32), default="file")
    visibility: Mapped[str] = mapped_column(String(32), default="internal")
    plan_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    linear_task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    author_name: Mapped[str] = mapped_column(String(255))
    author_email: Mapped[str | None] = mapped_column(String(255), nullable=True)

    shared_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    organization: Mapped["Organization"] = relationship()
    project: Mapped["Project | None"] = relationship()
    actor: Mapped["Actor | None"] = relationship()
    sections: Mapped[list["SharedDocumentSection"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class SharedDocumentSection(Base):
    __tablename__ = "shared_document_sections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    document_id: Mapped[str] = mapped_column(ForeignKey("shared_documents.id", ondelete="CASCADE"), index=True)
    heading: Mapped[str | None] = mapped_column(String(500), nullable=True)
    section_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    body: Mapped[str] = mapped_column(Text)
    ordinal: Mapped[int] = mapped_column(default=0)

    document: Mapped["SharedDocument"] = relationship(back_populates="sections")
