"""Deduplicate shared documents and enforce organization/path uniqueness."""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# Production's alembic_version.version_num is VARCHAR(32).
revision: str = "004_shared_doc_path_unique"
down_revision: Union[str, None] = "003_published_at_comments"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CONSTRAINT_NAME = "uq_shared_documents_organization_path"


def _reparent_dependents(
    bind: sa.engine.Connection,
    loser_ids: list[str],
    winner_id: str,
) -> None:
    """Move every direct shared_documents foreign key to the retained row."""
    inspector = sa.inspect(bind)
    metadata = sa.MetaData()

    for table_name in inspector.get_table_names():
        if table_name == "shared_documents":
            continue
        for foreign_key in inspector.get_foreign_keys(table_name):
            if foreign_key.get("referred_table") != "shared_documents":
                continue
            constrained = foreign_key.get("constrained_columns") or []
            referred = foreign_key.get("referred_columns") or []
            if len(constrained) != 1 or referred != ["id"]:
                continue

            dependent = sa.Table(table_name, metadata, autoload_with=bind)
            document_id = dependent.c[constrained[0]]
            bind.execute(
                dependent.update()
                .where(document_id.in_(loser_ids))
                .values({document_id.key: winner_id})
            )


def _deduplicate_shared_documents(bind: sa.engine.Connection) -> None:
    documents = sa.Table("shared_documents", sa.MetaData(), autoload_with=bind)
    duplicate_keys = bind.execute(
        sa.select(documents.c.organization_id, documents.c.path)
        .group_by(documents.c.organization_id, documents.c.path)
        .having(sa.func.count(documents.c.id) > 1)
    ).all()

    newest_at = sa.func.coalesce(
        documents.c.updated_at,
        documents.c.shared_at,
        documents.c.created_at,
    )
    for organization_id, path in duplicate_keys:
        ordered_ids = list(
            bind.scalars(
                sa.select(documents.c.id)
                .where(
                    documents.c.organization_id == organization_id,
                    documents.c.path == path,
                )
                .order_by(newest_at.desc(), documents.c.id.desc())
            )
        )
        winner_id, *loser_ids = ordered_ids
        _reparent_dependents(bind, loser_ids, winner_id)
        bind.execute(documents.delete().where(documents.c.id.in_(loser_ids)))


def upgrade() -> None:
    bind = op.get_bind()
    _deduplicate_shared_documents(bind)
    with op.batch_alter_table("shared_documents") as batch_op:
        batch_op.create_unique_constraint(
            CONSTRAINT_NAME,
            ["organization_id", "path"],
        )


def downgrade() -> None:
    with op.batch_alter_table("shared_documents") as batch_op:
        batch_op.drop_constraint(CONSTRAINT_NAME, type_="unique")
