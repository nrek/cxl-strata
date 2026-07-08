"""Shared document published_at column and comments table."""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003_published_at_comments"
down_revision: Union[str, None] = "002_shared_documents"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "shared_documents",
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_shared_documents_published_at", "shared_documents", ["published_at"])
    # Backfill so existing shares keep a stable published order.
    op.execute("UPDATE shared_documents SET published_at = created_at WHERE published_at IS NULL")

    op.create_table(
        "shared_document_comments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("actor_id", sa.String(length=36), nullable=True),
        sa.Column("author_name", sa.String(length=255), nullable=False),
        sa.Column("author_email", sa.String(length=255), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["shared_documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_id"], ["actors.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_shared_document_comments_document", "shared_document_comments", ["document_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_shared_document_comments_document", table_name="shared_document_comments")
    op.drop_table("shared_document_comments")
    op.drop_index("ix_shared_documents_published_at", table_name="shared_documents")
    op.drop_column("shared_documents", "published_at")
