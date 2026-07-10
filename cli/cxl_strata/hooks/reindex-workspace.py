#!/usr/bin/env python3
"""afterFileEdit hook: reindex workspace knowledge when meta markdown changes."""

from __future__ import annotations

import json
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[2]

WATCH_PREFIXES = (
    ".md/handoff/",
    ".md/blueprints/",
    ".cursor/plans/",
    ".cursor/rules/",
)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0

    rel = (
        payload.get("file_path")
        or payload.get("path")
        or payload.get("filePath")
        or ""
    )
    rel = rel.replace("\\", "/")
    if not rel or not any(rel.startswith(p) for p in WATCH_PREFIXES):
        return 0

    try:
        from cxl_strata.workspace_index.indexer import index_paths
        from cxl_strata.workspace_index.paths import set_workspace_root

        set_workspace_root(WORKSPACE)
        path = WORKSPACE / rel
        if path.is_file():
            index_paths([path.resolve()])
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
