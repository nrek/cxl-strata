"""Shared documents tables."""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002_shared_documents"
down_revision: Union[str, None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "shared_documents",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=True),
        sa.Column("actor_id", sa.String(length=36), nullable=True),
        sa.Column("project_slug", sa.String(length=120), nullable=True),
        sa.Column("repo_name", sa.String(length=255), nullable=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=True),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("body_hash", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False, server_default="workspace_index"),
        sa.Column("storage_state", sa.String(length=32), nullable=False, server_default="file"),
        sa.Column("visibility", sa.String(length=32), nullable=False, server_default="internal"),
        sa.Column("plan_status", sa.String(length=32), nullable=True),
        sa.Column("linear_task_id", sa.String(length=64), nullable=True),
        sa.Column("author_name", sa.String(length=255), nullable=False),
        sa.Column("author_email", sa.String(length=255), nullable=True),
        sa.Column("shared_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["actor_id"], ["actors.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_shared_documents_org", "shared_documents", ["organization_id"])
    op.create_index("ix_shared_documents_project_slug", "shared_documents", ["project_slug"])
    op.create_index("ix_shared_documents_kind", "shared_documents", ["kind"])
    op.create_index("ix_shared_documents_path", "shared_documents", ["path"])
    op.create_index("ix_shared_documents_body_hash", "shared_documents", ["body_hash"])

    op.create_table(
        "shared_document_sections",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("heading", sa.String(length=500), nullable=True),
        sa.Column("section_at", sa.String(length=64), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["document_id"], ["shared_documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_shared_document_sections_document", "shared_document_sections", ["document_id"])


def downgrade() -> None:
    op.drop_index("ix_shared_document_sections_document", table_name="shared_document_sections")
    op.drop_table("shared_document_sections")
    op.drop_index("ix_shared_documents_body_hash", table_name="shared_documents")
    op.drop_index("ix_shared_documents_path", table_name="shared_documents")
    op.drop_index("ix_shared_documents_kind", table_name="shared_documents")
    op.drop_index("ix_shared_documents_project_slug", table_name="shared_documents")
    op.drop_index("ix_shared_documents_org", table_name="shared_documents")
    op.drop_table("shared_documents")
