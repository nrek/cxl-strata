"""Shared workspace document storage (full artifacts)."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.content_safety import redact_secret_markers
from app.core.types import AuthContext, utcnow
from app.models import Project, SharedDocument, SharedDocumentComment, SharedDocumentSection
from app.schemas.shared_document import DocumentCommentCreate, SharedDocumentCreate


def _body_hash(body: str) -> str:
    return hashlib.sha256(body.encode()).hexdigest()


def comment_to_dict(row: SharedDocumentComment) -> dict[str, Any]:
    return {
        "id": row.id,
        "document_id": row.document_id,
        "author_name": row.author_name,
        "author_email": row.author_email,
        "body": row.body,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def document_to_dict(
    row: SharedDocument,
    *,
    include_body: bool = True,
    include_comments: bool = False,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": row.id,
        "organization_id": row.organization_id,
        "project_slug": row.project_slug,
        "repo_name": row.repo_name,
        "kind": row.kind,
        "title": row.title,
        "path": row.path,
        "body_hash": row.body_hash,
        "source": row.source,
        "storage_state": row.storage_state,
        "visibility": row.visibility,
        "plan_status": row.plan_status,
        "linear_task_id": row.linear_task_id,
        "author_name": row.author_name,
        "author_email": row.author_email,
        "actor_id": row.actor_id,
        "published_at": row.published_at.isoformat() if row.published_at else None,
        "shared_at": row.shared_at.isoformat() if row.shared_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
    if include_body:
        payload["body"] = row.body
    else:
        payload["body"] = row.body[:500]
    if include_comments:
        payload["comments"] = [comment_to_dict(c) for c in row.comments]
    return payload


class DocumentService:
    def __init__(self, db: Session, auth: AuthContext):
        self.db = db
        self.auth = auth

    def _author(self) -> tuple[str, str | None]:
        name = self.auth.actor_name or "unknown"
        email = None
        if self.auth.actor_id:
            from app.models import Actor

            actor = self.db.get(Actor, self.auth.actor_id)
            if actor and actor.email:
                email = actor.email
        return name, email

    def _ensure_project(self, slug: str | None) -> str | None:
        if not slug:
            return None
        stmt = select(Project).where(
            Project.organization_id == self.auth.organization_id,
            Project.slug == slug,
        )
        project = self.db.scalars(stmt).first()
        if project is None:
            project = Project(
                id=str(uuid.uuid4()),
                organization_id=self.auth.organization_id,
                slug=slug,
                name=slug,
            )
            self.db.add(project)
            self.db.flush()
        return project.id

    def upsert(self, body: SharedDocumentCreate) -> SharedDocument:
        redacted_body = redact_secret_markers(body.body)
        author_name, author_email = self._author()
        digest = _body_hash(redacted_body)
        project_id = self._ensure_project(body.project_slug)

        stmt = select(SharedDocument).where(
            SharedDocument.organization_id == self.auth.organization_id,
            SharedDocument.path == body.path,
        )
        row = self.db.scalars(stmt).first()
        now = utcnow()

        if row and row.body_hash == digest:
            if body.published_at is not None and row.published_at is None:
                row.published_at = body.published_at
                self.db.commit()
                self.db.refresh(row)
            return row

        if row is None:
            row = SharedDocument(
                id=str(uuid.uuid4()),
                organization_id=self.auth.organization_id,
                project_id=project_id,
                actor_id=self.auth.actor_id,
                project_slug=body.project_slug,
                repo_name=body.repo_name,
                kind=body.kind,
                title=body.title,
                path=body.path,
                body=redacted_body,
                body_hash=digest,
                source=body.source,
                storage_state=body.storage_state,
                visibility=body.visibility,
                plan_status=body.plan_status,
                linear_task_id=body.linear_task_id,
                author_name=author_name,
                author_email=author_email,
                published_at=body.published_at,
                shared_at=now,
            )
            self.db.add(row)
        else:
            row.project_id = project_id
            row.project_slug = body.project_slug
            row.repo_name = body.repo_name
            row.kind = body.kind
            row.title = body.title
            row.body = redacted_body
            row.body_hash = digest
            row.storage_state = body.storage_state
            row.visibility = body.visibility
            row.plan_status = body.plan_status
            row.linear_task_id = body.linear_task_id
            row.actor_id = self.auth.actor_id
            row.author_name = author_name
            row.author_email = author_email
            if body.published_at is not None:
                row.published_at = body.published_at
            row.updated_at = now
            row.shared_at = now

        self.db.flush()
        if body.sections:
            row.sections.clear()
            for idx, section in enumerate(body.sections):
                row.sections.append(
                    SharedDocumentSection(
                        id=str(uuid.uuid4()),
                        document_id=row.id,
                        heading=section.get("heading"),
                        section_at=section.get("section_at"),
                        body=section.get("body") or "",
                        ordinal=section.get("ordinal", idx),
                    )
                )
        self.db.commit()
        self.db.refresh(row)
        return row

    def get(self, document_id: str) -> SharedDocument | None:
        row = self.db.get(SharedDocument, document_id)
        if row is None or row.organization_id != self.auth.organization_id:
            return None
        return row

    def delete(self, document_id: str) -> bool:
        row = self.get(document_id)
        if row is None:
            return False
        self.db.delete(row)
        self.db.commit()
        return True

    def list_documents(
        self,
        *,
        project: str | None = None,
        repo: str | None = None,
        kind: str | None = None,
        author: str | None = None,
        since: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[SharedDocument]:
        stmt = select(SharedDocument).where(
            SharedDocument.organization_id == self.auth.organization_id
        )
        if project:
            stmt = stmt.where(SharedDocument.project_slug == project)
        if repo:
            stmt = stmt.where(SharedDocument.repo_name == repo)
        if kind:
            stmt = stmt.where(SharedDocument.kind == kind)
        if author:
            stmt = stmt.where(SharedDocument.author_name.ilike(f"%{author}%"))
        if since:
            stmt = stmt.where(SharedDocument.updated_at >= since)
        stmt = (
            stmt.order_by(
                func.coalesce(
                    SharedDocument.published_at, SharedDocument.created_at
                ).desc()
            )
            .offset(offset)
            .limit(limit)
        )
        return list(self.db.scalars(stmt).all())

    def search(
        self,
        q: str,
        *,
        project: str | None = None,
        repo: str | None = None,
        limit: int = 50,
    ) -> list[SharedDocument]:
        pattern = f"%{q}%"
        stmt = select(SharedDocument).where(
            SharedDocument.organization_id == self.auth.organization_id,
            or_(
                SharedDocument.title.ilike(pattern),
                SharedDocument.body.ilike(pattern),
                SharedDocument.path.ilike(pattern),
            ),
        )
        if project:
            stmt = stmt.where(SharedDocument.project_slug == project)
        if repo:
            stmt = stmt.where(SharedDocument.repo_name == repo)
        stmt = stmt.order_by(
            func.coalesce(SharedDocument.published_at, SharedDocument.created_at).desc()
        ).limit(limit)
        return list(self.db.scalars(stmt).all())

    def add_comment(
        self, document_id: str, body: DocumentCommentCreate
    ) -> SharedDocumentComment | None:
        row = self.get(document_id)
        if row is None:
            return None
        author_name, author_email = self._author()
        comment = SharedDocumentComment(
            id=str(uuid.uuid4()),
            document_id=row.id,
            actor_id=self.auth.actor_id,
            author_name=body.author_name or author_name,
            author_email=body.author_email or author_email,
            body=body.body,
            created_at=body.created_at or utcnow(),
        )
        self.db.add(comment)
        self.db.commit()
        self.db.refresh(comment)
        return comment

    def list_comments(self, document_id: str) -> list[SharedDocumentComment] | None:
        row = self.get(document_id)
        if row is None:
            return None
        return list(row.comments)

    def import_batch(self, documents: list[SharedDocumentCreate]) -> tuple[list[dict], list[dict]]:
        synced: list[dict] = []
        failed: list[dict] = []
        for raw in documents:
            try:
                row = self.upsert(raw)
                synced.append({"path": raw.path, "remote_id": row.id, "status": "upserted"})
            except Exception as exc:  # noqa: BLE001
                failed.append({"path": raw.path, "error": str(exc)})
        return synced, failed
