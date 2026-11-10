"""Seal existing organization content so remote rows no longer hold plaintext."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.types import AuthContext, load_json_list
from app.models import MemoryEvent, SharedDocument, SharedDocumentComment, SharedDocumentSection
from app.schemas.memory_event import SealIn

TABLES = (
    "memory_events",
    "shared_documents",
    "shared_document_sections",
    "shared_document_comments",
)


class SealService:
    def __init__(self, db: Session, auth: AuthContext):
        self.db = db
        self.auth = auth

    def status(self) -> dict[str, int]:
        counts = {name: self._count(name) for name in TABLES}
        counts["remaining"] = sum(counts.values())
        return counts

    def backlog(self, *, limit: int = 25) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        remaining = limit
        for name in TABLES:
            if remaining <= 0:
                break
            batch = self._page(name, remaining)
            rows.extend(batch)
            remaining -= len(batch)
        return rows

    def seal(self, body: SealIn) -> dict[str, Any]:
        row = self._load(body.table, body.id)
        if row is None:
            raise ValueError("row not found")
        if getattr(row, "content_state", "") == "sealed":
            return {"ok": True, "sealed": False, "id": body.id}
        if body.table == "shared_documents":
            if not body.path_hash:
                raise ValueError("Sealed documents require path_hash")
            stored_path = "sealed:" + body.path_hash
            conflict = self.db.scalar(
                select(SharedDocument).where(
                    SharedDocument.organization_id == self.auth.organization_id,
                    SharedDocument.path == stored_path,
                    SharedDocument.id != row.id,
                )
            )
            if conflict is not None:
                self.db.delete(row)
                self.db.commit()
                return {"ok": True, "sealed": True, "id": body.id}
            row.path_hash = body.path_hash
            row.path = stored_path
            row.title = None
            row.body = ""
        elif body.table == "shared_document_sections":
            row.heading = None
            row.body = ""
        elif body.table == "shared_document_comments":
            row.body = ""
        else:
            row.title = ""
            row.summary = ""
            row.details = None
            row.source_ref = None
            row.tags_json = "[]"
            row.related_files_json = "[]"
        row.content_ciphertext = body.content_ciphertext
        row.content_nonce = body.content_nonce
        row.dek_version = body.dek_version
        row.content_state = "sealed"
        self.db.commit()
        return {"ok": True, "sealed": True, "id": body.id}

    def _count(self, table: str) -> int:
        model = self._model(table)
        stmt = select(func.count()).select_from(model).where(model.content_state == "plaintext")
        if table == "memory_events":
            stmt = stmt.where(MemoryEvent.organization_id == self.auth.organization_id)
        elif table == "shared_documents":
            stmt = stmt.where(SharedDocument.organization_id == self.auth.organization_id)
        else:
            stmt = stmt.where(model.document.has(organization_id=self.auth.organization_id))
        return int(self.db.scalar(stmt) or 0)

    def _page(self, table: str, limit: int) -> list[dict[str, Any]]:
        model = self._model(table)
        stmt = select(model).where(model.content_state == "plaintext")
        if table == "memory_events":
            stmt = stmt.where(MemoryEvent.organization_id == self.auth.organization_id)
        elif table == "shared_documents":
            stmt = stmt.where(SharedDocument.organization_id == self.auth.organization_id)
        else:
            stmt = stmt.where(model.document.has(organization_id=self.auth.organization_id))
        rows = list(self.db.scalars(stmt.limit(limit)))
        return [self._public_row(table, row) for row in rows]

    def _load(self, table: str, row_id: str):
        model = self._model(table)
        row = self.db.get(model, row_id)
        if row is None:
            return None
        if table == "memory_events" and row.organization_id != self.auth.organization_id:
            return None
        if table == "shared_documents" and row.organization_id != self.auth.organization_id:
            return None
        if table in {"shared_document_sections", "shared_document_comments"}:
            document = self.db.get(SharedDocument, row.document_id)
            if document is None or document.organization_id != self.auth.organization_id:
                return None
        return row

    def _model(self, table: str):
        return {
            "memory_events": MemoryEvent,
            "shared_documents": SharedDocument,
            "shared_document_sections": SharedDocumentSection,
            "shared_document_comments": SharedDocumentComment,
        }[table]

    def _public_row(self, table: str, row: Any) -> dict[str, Any]:
        if table == "memory_events":
            content = {
                "title": row.title,
                "summary": row.summary,
                "details": row.details or "",
                "source_ref": row.source_ref or "",
                "tags": load_json_list(row.tags_json),
                "related_files": load_json_list(row.related_files_json),
            }
        elif table == "shared_documents":
            content = {"title": row.title or "", "path": row.path, "body": row.body}
        elif table == "shared_document_sections":
            content = {"heading": row.heading or "", "body": row.body}
        else:
            content = {"body": row.body}
        return {"table": table, "id": row.id, "content": content}
