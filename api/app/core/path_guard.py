"""Guard against importing scratch/cache artifacts (e.g. .codex/.tmp plugin dumps).

Workspace knowledge lives under hidden top-level roots (.md, .cursor, .claude,
.codex), so a leading dot on the first segment is fine. A hidden segment
anywhere deeper marks scratch/cache content (.codex/.tmp/**, .claude/.cache/**,
legacy .md/.handoff/**) that must never be stored as shared team knowledge.
"""

from __future__ import annotations


def is_scratch_path(path: str) -> bool:
    rel = (path or "").replace("\\", "/").strip("/")
    if not rel:
        return False
    return any(part.startswith(".") for part in rel.split("/")[1:])
