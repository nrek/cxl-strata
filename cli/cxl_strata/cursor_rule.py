from __future__ import annotations

from importlib import resources
from pathlib import Path
from typing import Any

RULE_DEST = Path(".cursor") / "rules" / "strata-memory-capture.mdc"
RULE_PACKAGE = "cxl_strata.rules"
RULE_RESOURCE = "strata-memory-capture.mdc"
REQUIRED_MARKERS = ("/strata add", "/strata summary", "/strata prune")


def packaged_rule_text() -> str:
    return resources.files(RULE_PACKAGE).joinpath(RULE_RESOURCE).read_text(encoding="utf-8")


def install_cursor_rule(dest: Path | None = None) -> dict[str, Any]:
    target = dest or RULE_DEST
    result_path = str(target.resolve())
    rule_text = packaged_rule_text()

    if target.is_file():
        existing = target.read_text(encoding="utf-8")
        if all(marker in existing for marker in REQUIRED_MARKERS):
            return {"path": result_path, "status": "present"}

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(rule_text, encoding="utf-8")
    return {"path": result_path, "status": "installed"}
