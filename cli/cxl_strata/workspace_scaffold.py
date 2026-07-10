"""Scaffold the front-facing .md workspace knowledge layout on client init."""

from __future__ import annotations

from pathlib import Path

MD_GITIGNORE_CONTENT = """workspace_index.sqlite
workspace_index.sqlite-wal
workspace_index.sqlite-shm
"""

MD_SUBDIRS = ("handoff", "blueprints", "reports")


def ensure_workspace_layout(root: Path, *, project: str | None = None) -> dict[str, str]:
    """Create the .md knowledge tree if missing. Idempotent; never overwrites.

    Returns a mapping of relative path -> "created" | "present".
    """
    result: dict[str, str] = {}
    md_root = root / ".md"

    def _ensure_dir(path: Path, rel: str) -> None:
        if path.is_dir():
            result[rel] = "present"
        else:
            path.mkdir(parents=True, exist_ok=True)
            result[rel] = "created"

    _ensure_dir(md_root, ".md")
    for name in MD_SUBDIRS:
        _ensure_dir(md_root / name, f".md/{name}")

    gitignore = md_root / ".gitignore"
    if gitignore.is_file():
        result[".md/.gitignore"] = "present"
    else:
        gitignore.write_text(MD_GITIGNORE_CONTENT, encoding="utf-8", newline="\n")
        result[".md/.gitignore"] = "created"

    if project:
        _ensure_dir(md_root / "handoff" / project, f".md/handoff/{project}")
        _ensure_dir(md_root / "reports" / project, f".md/reports/{project}")

    return result
