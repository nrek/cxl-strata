"""Resolve org/project/repo slugs and persist memory events."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.content_safety import find_secret_markers
from app.core.types import AuthContext, dump_json, load_json_list, utcnow
from app.models import Actor, MemoryEvent, Organization, Project, Repo
from app.schemas.memory_event import MemoryEventCreate


class MemoryService:
    def __init__(self, db: Session, auth: AuthContext):
        self.db = db
        self.auth = auth

    def create(self, body: MemoryEventCreate, *, local_id: str | None = None) -> MemoryEvent:
        if find_secret_markers(body.model_dump()):
            raise ValueError("Payload appears to contain secrets. Redact credentials before saving memory.")

        org = self._get_org()
        project = self._get_or_create_project(org, body.project_slug)
        repo = self._get_or_create_repo(project, body.repo_name) if body.repo_name else None

        event = MemoryEvent(
            organization_id=org.id,
            project_id=project.id,
            repo_id=repo.id if repo else None,
            actor_id=self.auth.actor_id,
            project_slug=body.project_slug,
            repo_name=body.repo_name,
            event_type=body.event_type,
            title=body.title,
            summary=body.summary,
            details=body.details,
            environment=body.environment,
            visibility=body.visibility,
            source=body.source,
            source_ref=body.source_ref,
            confidence=body.confidence,
            tags_json=dump_json(body.tags),
            related_files_json=dump_json(body.related_files),
            local_id=local_id,
            occurred_at=body.occurred_at,
        )
        self.db.add(event)
        self.db.commit()
        self.db.refresh(event)
        return event

    def get(self, event_id: str) -> MemoryEvent | None:
        return self.db.get(MemoryEvent, event_id)

    def list_events(self, *, project: str | None = None, limit: int = 50) -> list[MemoryEvent]:
        stmt = select(MemoryEvent).where(MemoryEvent.organization_id == self.auth.organization_id)
        if project:
            stmt = stmt.where(MemoryEvent.project_slug == project)
        stmt = stmt.order_by(MemoryEvent.created_at.desc()).limit(limit)
        return list(self.db.scalars(stmt))

    def recent(self, *, project: str | None = None, days: int = 7, limit: int = 20) -> list[MemoryEvent]:
        cutoff = utcnow() - timedelta(days=days)
        stmt = select(MemoryEvent).where(
            MemoryEvent.organization_id == self.auth.organization_id,
            MemoryEvent.created_at >= cutoff,
        )
        if project:
            stmt = stmt.where(MemoryEvent.project_slug == project)
        stmt = stmt.order_by(MemoryEvent.created_at.desc()).limit(limit)
        return list(self.db.scalars(stmt))

    def search(self, *, q: str, project: str | None = None, limit: int = 50) -> list[MemoryEvent]:
        needle = q.lower()
        stmt = select(MemoryEvent).where(MemoryEvent.organization_id == self.auth.organization_id)
        if project:
            stmt = stmt.where(MemoryEvent.project_slug == project)
        rows = list(self.db.scalars(stmt.order_by(MemoryEvent.created_at.desc()).limit(limit * 5)))
        hits: list[MemoryEvent] = []
        for row in rows:
            blob = " ".join(
                [
                    row.title,
                    row.summary,
                    row.details or "",
                    row.project_slug,
                    row.repo_name or "",
                    row.environment or "",
                    row.event_type,
                    " ".join(load_json_list(row.tags_json)),
                ]
            ).lower()
            if needle in blob:
                hits.append(row)
        return hits[:limit]

    def project_context(self, *, project: str, limit: int = 10) -> dict:
        recent = self.recent(project=project, days=14, limit=limit)
        return {
            "project": project,
            "organization": self.auth.organization_slug,
            "recent_count": len(recent),
            "recent": [event_to_dict(row) for row in recent],
        }

    def _get_org(self) -> Organization:
        org = self.db.get(Organization, self.auth.organization_id)
        if org is None:
            raise ValueError("Organization not found for authenticated key")
        return org

    def _get_or_create_project(self, org: Organization, slug: str) -> Project:
        stmt = select(Project).where(Project.organization_id == org.id, Project.slug == slug)
        project = self.db.scalar(stmt)
        if project:
            return project
        project = Project(organization_id=org.id, slug=slug, name=slug)
        self.db.add(project)
        self.db.flush()
        return project

    def _get_or_create_repo(self, project: Project, name: str) -> Repo:
        stmt = select(Repo).where(Repo.project_id == project.id, Repo.name == name)
        repo = self.db.scalar(stmt)
        if repo:
            return repo
        repo = Repo(project_id=project.id, name=name)
        self.db.add(repo)
        self.db.flush()
        return repo


def event_to_dict(row: MemoryEvent) -> dict:
    return {
        "id": row.id,
        "project_slug": row.project_slug,
        "repo_name": row.repo_name,
        "event_type": row.event_type,
        "title": row.title,
        "summary": row.summary,
        "details": row.details,
        "environment": row.environment,
        "visibility": row.visibility,
        "source": row.source,
        "source_ref": row.source_ref,
        "confidence": row.confidence,
        "tags": load_json_list(row.tags_json),
        "related_files": load_json_list(row.related_files_json),
        "occurred_at": row.occurred_at.isoformat() if row.occurred_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
