from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

_PKG = Path(__file__).resolve().parent
SCHEMA_PATH = _PKG / "schema.sql"

HANDOFF_GLOB = ".md/handoff/**/*.md"
BLUEPRINT_GLOB = ".md/blueprints/*.md"
PLAN_GLOB = ".cursor/plans/**/*.md"
PLAN_GLOB_MDC = ".cursor/plans/**/*.plan.md"
RULE_GLOB = ".cursor/rules/*.mdc"

PLAN_STATUSES = frozenset({"draft", "backlog", "in_queue", "in_progress", "done"})
PLAN_STATUS_FOLDERS = PLAN_STATUSES

LEGACY_PLAN_FOLDER_STATUS = {
    "new": "draft",
    "built": "done",
    "backlog": "backlog",
    "draft": "draft",
    "in_queue": "in_queue",
    "in_progress": "in_progress",
    "done": "done",
}

PREFIX_PROJECT_MAP = [
    ("CS_", "commonspace"),
    ("SS_", "seersite"),
    ("INVIV_", "invivaria"),
    ("SYNQ_", "synq-forge"),
    ("PROMP_", "v5.prompli.com"),
    ("BI_", "blind-insight"),
    ("CXL_", "cxl-sentinel"),
    ("SAN_", "cxl-sentinel"),
]

BLUEPRINT_ALIASES: dict[str, str] = {
    "commonspace-app": "commonspace-app.md",
    "commonspace-ui-v3": "commonspace-ui-v3.md",
    "commonspace-mobile-ui": "commonspace-ui-v3.md",
    "cs-space-builder": "commonspace-build-integration.md",
    "seersite-server": "seersite-server.md",
    "seersite-frontend": "seersite-frontend.md",
    "invivaria-frontend": "invivaria-frontend.md",
    "invivaria-backend": "invivaria-backend.md",
    "synq-phalanx": "synq-phalanx.md",
    "synq-filters": "synq-filters.md",
    "synq-forge": "synq-forge.md",
    "synq-net-scrapers": "synq-net-scrapers.md",
    "blind-insight": "prompli-prompter-data-flow.md",
    "blind-llm": "prompli-prompter-data-flow.md",
    "v5.prompli.com": "v5.prompli.com.md",
    "v4.prompli.com": "v4.prompli.com.md",
    "cxl-spore": "cxl-spore.md",
    "cxl-sentinel": "cxl-sentinel-saas.md",
    "cxl-sentinel-saas": "cxl-sentinel-saas.md",
}


def _looks_like_workspace(root: Path) -> bool:
    return (root / ".md" / "handoff").is_dir() or (root / ".md" / "blueprints").is_dir()


@lru_cache(maxsize=1)
def resolve_workspace_root(start: Path | None = None) -> Path:
    env = os.environ.get("STRATA_WORKSPACE_ROOT", "").strip()
    if env:
        root = Path(env).expanduser().resolve()
        if _looks_like_workspace(root):
            return root
        raise ValueError(f"STRATA_WORKSPACE_ROOT is not a workspace: {root}")

    candidates: list[Path] = []
    if start is not None:
        candidates.append(start.resolve())
    candidates.append(Path.cwd().resolve())

    for base in candidates:
        current = base
        for _ in range(12):
            if _looks_like_workspace(current):
                return current
            if current.parent == current:
                break
            current = current.parent

    # Fallback: parent of projects/ orchestration root when indexing from repo checkout.
    fallback = _PKG.parents[4]
    if _looks_like_workspace(fallback):
        return fallback
    return candidates[0]


WORKSPACE_ROOT = resolve_workspace_root()
DB_PATH = WORKSPACE_ROOT / ".md" / "workspace_index.sqlite"


def set_workspace_root(root: Path | str) -> Path:
    """Override workspace root (tests / explicit CLI --root)."""
    global WORKSPACE_ROOT, DB_PATH
    resolve_workspace_root.cache_clear()
    resolved = Path(root).expanduser().resolve()
    WORKSPACE_ROOT = resolved
    DB_PATH = resolved / ".md" / "workspace_index.sqlite"
    return resolved
