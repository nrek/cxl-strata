"""Guard against syncing scratch/cache artifacts (e.g. .codex/.tmp plugin dumps).

Workspace knowledge lives under hidden top-level roots (.md, .cursor, .claude,
.codex), so a leading dot on the first segment is fine. A hidden segment
anywhere deeper marks scratch/cache content (.codex/.tmp/**, .claude/.cache/**,
.md/.handoff/** legacy dirs) that must never be shared to or pulled from the
central STRATA API.
"""

from __future__ import annotations

SCRATCH_REASON = "scratch_path"


def is_scratch_path(path: str) -> bool:
    rel = (path or "").replace("\\", "/").strip("/")
    if not rel:
        return False
    return any(part.startswith(".") for part in rel.split("/")[1:])
