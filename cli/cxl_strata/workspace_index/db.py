from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .paths import SCHEMA_PATH
from . import paths as _paths


def _db_path(db_path: Path | None = None) -> Path:
    return db_path or _paths.DB_PATH


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@contextmanager
def connect(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    path = _db_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


_MIGRATION_COLUMNS: tuple[tuple[str, str], ...] = (
    ("published_at", "TEXT"),
    ("storage", "TEXT NOT NULL DEFAULT 'file'"),
    ("origin", "TEXT NOT NULL DEFAULT 'local'"),
    ("remote_id", "TEXT"),
    ("author_name", "TEXT"),
    ("author_email", "TEXT"),
    ("shared_at", "TEXT"),
    ("synced_at", "TEXT"),
    ("remote_updated_at", "TEXT"),
    ("sync_ignored_at", "TEXT"),
    ("sync_ignore_reason", "TEXT"),
    ("sync_locked", "INTEGER NOT NULL DEFAULT 0"),
    ("indexed_file_body_hash", "TEXT"),
    ("last_pushed_body_hash", "TEXT"),
    ("remote_body_hash", "TEXT"),
)


def init_db(conn: sqlite3.Connection) -> None:
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    conn.executescript(schema)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(documents)").fetchall()}
    added_columns: set[str] = set()
    for name, typedef in _MIGRATION_COLUMNS:
        if name not in cols:
            conn.execute(f"ALTER TABLE documents ADD COLUMN {name} {typedef}")
            added_columns.add(name)
    # Legacy shared/pulled rows stored the acknowledged remote hash in
    # ``body_hash``. Seed both checkpoints as clean; future local indexing only
    # changes ``body_hash`` while transfers advance these checkpoint columns.
    if {"last_pushed_body_hash", "remote_body_hash"} & added_columns:
        conn.execute(
            """
            UPDATE documents
            SET last_pushed_body_hash = COALESCE(last_pushed_body_hash, body_hash),
                remote_body_hash = COALESCE(remote_body_hash, body_hash)
            WHERE remote_id IS NOT NULL
            """
        )
    if "indexed_file_body_hash" in added_columns:
        conn.execute(
            """
            UPDATE documents
            SET indexed_file_body_hash = body_hash
            WHERE indexed_file_body_hash IS NULL AND remote_id IS NULL
                  AND COALESCE(storage, 'file') = 'file'
            """
        )
    # Index on a migrated column must be created after the ALTERs on legacy DBs.
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_documents_published ON documents(published_at)"
    )


def is_db_only(conn: sqlite3.Connection, path: str) -> bool:
    row = conn.execute(
        "SELECT storage FROM documents WHERE path = ?", (path.replace("\\", "/"),)
    ).fetchone()
    return bool(row and row["storage"] == "db_only")


def delete_document(conn: sqlite3.Connection, doc_id: str) -> None:
    conn.execute("DELETE FROM documents_fts WHERE document_id = ?", (doc_id,))
    conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))


def upsert_fts(
    conn: sqlite3.Connection,
    doc_id: str,
    title: str | None,
    body: str,
    project: str | None,
    kind: str,
) -> None:
    conn.execute("DELETE FROM documents_fts WHERE document_id = ?", (doc_id,))
    conn.execute(
        """
        INSERT INTO documents_fts (document_id, title, body, project, kind)
        VALUES (?, ?, ?, ?, ?)
        """,
        (doc_id, title or "", body, project or "", kind),
    )


def upsert_document(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    payload = {
        "published_at": None,
        "origin": "local",
        "remote_id": None,
        "author_name": None,
        "author_email": None,
        "shared_at": None,
        "synced_at": None,
        "remote_updated_at": None,
        "indexed_file_body_hash": None,
        "last_pushed_body_hash": None,
        "remote_body_hash": None,
        "sync_ignored_at": None,
        "sync_ignore_reason": None,
        "sync_locked": 0,
        **row,
    }
    conn.execute(
        """
        INSERT INTO documents (
            id, kind, project, path, title, created_at, updated_at, published_at,
            body, body_hash, plan_status, linear_task_id, files_changed,
            deploy_commands, tags, folder_status, status_mismatch, storage,
            origin, remote_id, author_name, author_email, shared_at, synced_at,
            remote_updated_at, indexed_file_body_hash, last_pushed_body_hash, remote_body_hash,
            sync_ignored_at, sync_ignore_reason, sync_locked
        ) VALUES (
            :id, :kind, :project, :path, :title, :created_at, :updated_at, :published_at,
            :body, :body_hash, :plan_status, :linear_task_id, :files_changed,
            :deploy_commands, :tags, :folder_status, :status_mismatch,
            COALESCE(:storage, 'file'),
            COALESCE(:origin, 'local'), :remote_id, :author_name, :author_email,
            :shared_at, :synced_at, :remote_updated_at, :indexed_file_body_hash,
            :last_pushed_body_hash,
            :remote_body_hash, :sync_ignored_at, :sync_ignore_reason,
            COALESCE(:sync_locked, 0)
        )
        ON CONFLICT(path) DO UPDATE SET
            id = COALESCE(documents.id, excluded.id),
            kind = excluded.kind,
            project = excluded.project,
            title = excluded.title,
            created_at = COALESCE(documents.created_at, excluded.created_at),
            updated_at = excluded.updated_at,
            published_at = COALESCE(excluded.published_at, documents.published_at),
            body = excluded.body,
            body_hash = excluded.body_hash,
            plan_status = excluded.plan_status,
            linear_task_id = excluded.linear_task_id,
            files_changed = excluded.files_changed,
            deploy_commands = excluded.deploy_commands,
            tags = excluded.tags,
            folder_status = excluded.folder_status,
            status_mismatch = excluded.status_mismatch,
            storage = excluded.storage,
            origin = COALESCE(excluded.origin, documents.origin),
            remote_id = COALESCE(excluded.remote_id, documents.remote_id),
            author_name = COALESCE(excluded.author_name, documents.author_name),
            author_email = COALESCE(excluded.author_email, documents.author_email),
            shared_at = COALESCE(excluded.shared_at, documents.shared_at),
            synced_at = COALESCE(excluded.synced_at, documents.synced_at),
            remote_updated_at = COALESCE(
                excluded.remote_updated_at, documents.remote_updated_at
            ),
            indexed_file_body_hash = COALESCE(
                excluded.indexed_file_body_hash, documents.indexed_file_body_hash
            ),
            last_pushed_body_hash = COALESCE(
                excluded.last_pushed_body_hash, documents.last_pushed_body_hash
            ),
            remote_body_hash = COALESCE(
                excluded.remote_body_hash, documents.remote_body_hash
            ),
            sync_ignored_at = COALESCE(
                documents.sync_ignored_at, excluded.sync_ignored_at
            ),
            sync_ignore_reason = COALESCE(
                documents.sync_ignore_reason, excluded.sync_ignore_reason
            ),
            sync_locked = COALESCE(documents.sync_locked, excluded.sync_locked)
        """,
        payload,
    )
    upsert_fts(
        conn,
        payload["id"],
        payload.get("title"),
        payload["body"],
        payload.get("project"),
        payload["kind"],
    )


def upsert_plan(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO plans (
            document_id, status, name, overview, project, linear_task_id,
            todo_total, todo_done, status_changed_at
        ) VALUES (
            :document_id, :status, :name, :overview, :project, :linear_task_id,
            :todo_total, :todo_done, :status_changed_at
        )
        ON CONFLICT(document_id) DO UPDATE SET
            status = excluded.status,
            name = excluded.name,
            overview = excluded.overview,
            project = excluded.project,
            linear_task_id = excluded.linear_task_id,
            todo_total = excluded.todo_total,
            todo_done = excluded.todo_done,
            status_changed_at = COALESCE(plans.status_changed_at, excluded.status_changed_at)
        """,
        row,
    )


def replace_sections(
    conn: sqlite3.Connection, document_id: str, sections: list[dict[str, Any]]
) -> None:
    conn.execute("DELETE FROM sections WHERE document_id = ?", (document_id,))
    for s in sections:
        conn.execute(
            """
            INSERT INTO sections (id, document_id, heading, section_at, body, ordinal)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                s["id"],
                document_id,
                s.get("heading"),
                s.get("section_at"),
                s["body"],
                s["ordinal"],
            ),
        )


def list_indexed_paths(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT path FROM documents").fetchall()
    return {r["path"] for r in rows}


def mark_shared(
    conn: sqlite3.Connection,
    *,
    path: str,
    remote_id: str,
    author_name: str | None,
    author_email: str | None,
    shared_at: str | None = None,
    remote_updated_at: str | None = None,
    remote_body_hash: str | None = None,
) -> None:
    """Mark a local doc as shared after a successful stash/import-batch.

    Preserve ``body_hash`` as the current local SQLite revision. The local
    revision just pushed and the server revision acknowledged are separate
    checkpoints because server-side redaction can change the remote hash.
    """
    now = shared_at or utc_now()
    remote_ts = remote_updated_at or now
    conn.execute(
        """
        UPDATE documents SET
            origin = 'shared',
            remote_id = ?,
            author_name = COALESCE(?, author_name),
            author_email = COALESCE(?, author_email),
            shared_at = ?,
            synced_at = ?,
            remote_updated_at = ?,
            last_pushed_body_hash = body_hash,
            remote_body_hash = COALESCE(?, remote_body_hash, body_hash),
            sync_ignored_at = NULL,
            sync_ignore_reason = NULL
        WHERE path = ?
        """,
        (
            remote_id,
            author_name,
            author_email,
            now,
            now,
            remote_ts,
            remote_body_hash,
            path.replace("\\", "/"),
        ),
    )


def set_sync_locked(
    conn: sqlite3.Connection,
    *,
    path: str,
    locked: bool,
) -> bool:
    cur = conn.execute(
        """
        UPDATE documents SET sync_locked = ?
        WHERE path = ?
        """,
        (1 if locked else 0, path.replace("\\", "/")),
    )
    return cur.rowcount > 0


def mark_remote_deleted(
    conn: sqlite3.Connection,
    *,
    path: str,
    reason: str = "deleted_remote",
    ignored_at: str | None = None,
) -> None:
    now = ignored_at or utc_now()
    conn.execute(
        """
        UPDATE documents SET
            origin = 'local',
            remote_id = NULL,
            shared_at = NULL,
            synced_at = NULL,
            remote_updated_at = NULL,
            last_pushed_body_hash = NULL,
            remote_body_hash = NULL,
            sync_ignored_at = ?,
            sync_ignore_reason = ?
        WHERE path = ?
        """,
        (now, reason, path.replace("\\", "/")),
    )


ARCHIVED_BODY_HASH = "archived-local"


def archive_document(
    conn: sqlite3.Connection,
    *,
    path: str,
    reason: str = "archived_local",
    ignored_at: str | None = None,
) -> bool:
    """Tombstone a doc locally: ignore future syncs, drop body/FTS/sections.

    The row is kept (with empty body and a sentinel hash) so pull can see the
    ignore marker and never re-import the remote copy.
    """
    rel = path.replace("\\", "/")
    row = conn.execute("SELECT id FROM documents WHERE path = ?", (rel,)).fetchone()
    if not row:
        return False
    doc_id = row["id"]
    now = ignored_at or utc_now()
    conn.execute(
        """
        UPDATE documents SET
            origin = 'local',
            remote_id = NULL,
            shared_at = NULL,
            synced_at = NULL,
            remote_updated_at = NULL,
            last_pushed_body_hash = NULL,
            remote_body_hash = NULL,
            sync_ignored_at = ?,
            sync_ignore_reason = ?,
            body = '',
            body_hash = ?
        WHERE path = ?
        """,
        (now, reason, ARCHIVED_BODY_HASH, rel),
    )
    conn.execute("DELETE FROM documents_fts WHERE document_id = ?", (doc_id,))
    conn.execute("DELETE FROM sections WHERE document_id = ?", (doc_id,))
    return True


def add_comment(
    conn: sqlite3.Connection,
    *,
    comment_id: str,
    document_path: str,
    body: str,
    author_name: str | None = None,
    author_email: str | None = None,
    created_at: str | None = None,
    remote_comment_id: str | None = None,
    synced_at: str | None = None,
) -> dict[str, Any]:
    row = {
        "id": comment_id,
        "document_path": document_path.replace("\\", "/"),
        "remote_comment_id": remote_comment_id,
        "author_name": author_name,
        "author_email": author_email,
        "body": body,
        "created_at": created_at or utc_now(),
        "synced_at": synced_at,
    }
    conn.execute(
        """
        INSERT INTO document_comments (
            id, document_path, remote_comment_id, author_name, author_email,
            body, created_at, synced_at
        ) VALUES (
            :id, :document_path, :remote_comment_id, :author_name, :author_email,
            :body, :created_at, :synced_at
        )
        ON CONFLICT(id) DO UPDATE SET
            body = excluded.body,
            remote_comment_id = COALESCE(excluded.remote_comment_id, document_comments.remote_comment_id),
            synced_at = COALESCE(excluded.synced_at, document_comments.synced_at)
        """,
        row,
    )
    return row


def upsert_remote_comment(
    conn: sqlite3.Connection,
    *,
    document_path: str,
    remote_comment_id: str,
    body: str,
    author_name: str | None = None,
    author_email: str | None = None,
    created_at: str | None = None,
) -> None:
    existing = conn.execute(
        "SELECT id FROM document_comments WHERE remote_comment_id = ?",
        (remote_comment_id,),
    ).fetchone()
    comment_id = existing["id"] if existing else f"remote-{remote_comment_id}"
    add_comment(
        conn,
        comment_id=comment_id,
        document_path=document_path,
        body=body,
        author_name=author_name,
        author_email=author_email,
        created_at=created_at,
        remote_comment_id=remote_comment_id,
        synced_at=utc_now(),
    )


def list_comments(conn: sqlite3.Connection, path: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, document_path, remote_comment_id, author_name, author_email,
               body, created_at, synced_at
        FROM document_comments
        WHERE document_path = ?
        ORDER BY created_at ASC
        """,
        (path.replace("\\", "/"),),
    ).fetchall()
    return [dict(r) for r in rows]


def unsynced_comments(conn: sqlite3.Connection, path: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, document_path, author_name, author_email, body, created_at
        FROM document_comments
        WHERE document_path = ? AND synced_at IS NULL
        ORDER BY created_at ASC
        """,
        (path.replace("\\", "/"),),
    ).fetchall()
    return [dict(r) for r in rows]


def mark_comment_synced(
    conn: sqlite3.Connection,
    *,
    comment_id: str,
    remote_comment_id: str | None = None,
) -> None:
    conn.execute(
        """
        UPDATE document_comments
        SET synced_at = ?,
            remote_comment_id = COALESCE(?, remote_comment_id)
        WHERE id = ?
        """,
        (utc_now(), remote_comment_id, comment_id),
    )


def prune_missing(conn: sqlite3.Connection, existing_paths: set[str]) -> int:
    """Remove DB rows only for file-backed docs whose files were deleted."""
    rows = conn.execute(
        "SELECT path, id FROM documents WHERE COALESCE(storage, 'file') = 'file'"
    ).fetchall()
    removed = 0
    for row in rows:
        if row["path"] not in existing_paths:
            delete_document(conn, row["id"])
            removed += 1
    return removed
