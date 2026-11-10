"""Add ciphertext columns for organization memory stores."""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "005_memory_content_seal"
down_revision: Union[str, None] = "004_shared_doc_path_unique"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _add_seal_columns(table: str) -> None:
    op.add_column(table, sa.Column("content_ciphertext", sa.Text(), nullable=True))
    op.add_column(table, sa.Column("content_nonce", sa.String(length=64), nullable=True))
    op.add_column(table, sa.Column("dek_version", sa.Integer(), nullable=True))
    op.add_column(
        table,
        sa.Column("content_state", sa.String(length=16), nullable=False, server_default="plaintext"),
    )


def upgrade() -> None:
    _add_seal_columns("memory_events")
    _add_seal_columns("shared_documents")
    op.add_column("shared_documents", sa.Column("path_hash", sa.String(length=64), nullable=True))
    op.create_index("ix_shared_documents_path_hash", "shared_documents", ["path_hash"])
    _add_seal_columns("shared_document_sections")
    _add_seal_columns("shared_document_comments")


def downgrade() -> None:
    for table in (
        "shared_document_comments",
        "shared_document_sections",
        "shared_documents",
        "memory_events",
    ):
        op.drop_column(table, "content_state")
        op.drop_column(table, "dek_version")
        op.drop_column(table, "content_nonce")
        op.drop_column(table, "content_ciphertext")
    op.drop_index("ix_shared_documents_path_hash", table_name="shared_documents")
    op.drop_column("shared_documents", "path_hash")
