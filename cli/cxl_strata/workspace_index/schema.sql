PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('handoff', 'blueprint', 'plan', 'rule')),
    project TEXT,
    path TEXT NOT NULL UNIQUE,
    title TEXT,
    created_at TEXT,
    updated_at TEXT,
    published_at TEXT,
    body TEXT NOT NULL,
    body_hash TEXT NOT NULL,
    plan_status TEXT CHECK (
        plan_status IS NULL OR plan_status IN (
            'draft', 'backlog', 'in_queue', 'in_progress', 'done'
        )
    ),
    linear_task_id TEXT,
    files_changed TEXT,
    deploy_commands TEXT,
    tags TEXT,
    folder_status TEXT,
    status_mismatch INTEGER NOT NULL DEFAULT 0,
    storage TEXT NOT NULL DEFAULT 'file',
    sync_ignored_at TEXT,
    sync_ignore_reason TEXT,
    sync_locked INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS plans (
    document_id TEXT PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (
        status IN ('draft', 'backlog', 'in_queue', 'in_progress', 'done')
    ),
    name TEXT,
    overview TEXT,
    project TEXT,
    linear_task_id TEXT,
    todo_total INTEGER NOT NULL DEFAULT 0,
    todo_done INTEGER NOT NULL DEFAULT 0,
    status_changed_at TEXT
);

CREATE TABLE IF NOT EXISTS document_comments (
    id TEXT PRIMARY KEY,
    document_path TEXT NOT NULL,
    remote_comment_id TEXT,
    author_name TEXT,
    author_email TEXT,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL,
    synced_at TEXT
);

CREATE TABLE IF NOT EXISTS sections (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    heading TEXT,
    section_at TEXT,
    body TEXT NOT NULL,
    ordinal INTEGER NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
    document_id UNINDEXED,
    title,
    body,
    project,
    kind UNINDEXED
);

CREATE INDEX IF NOT EXISTS idx_documents_kind ON documents(kind);
CREATE INDEX IF NOT EXISTS idx_documents_project ON documents(project);
CREATE INDEX IF NOT EXISTS idx_documents_updated ON documents(updated_at);
CREATE INDEX IF NOT EXISTS idx_document_comments_path ON document_comments(document_path);
CREATE INDEX IF NOT EXISTS idx_document_comments_remote ON document_comments(remote_comment_id);
CREATE INDEX IF NOT EXISTS idx_documents_plan_status ON documents(plan_status);
CREATE INDEX IF NOT EXISTS idx_plans_status ON plans(status);
CREATE INDEX IF NOT EXISTS idx_plans_project ON plans(project);
CREATE INDEX IF NOT EXISTS idx_sections_document ON sections(document_id);
CREATE INDEX IF NOT EXISTS idx_sections_at ON sections(section_at);
