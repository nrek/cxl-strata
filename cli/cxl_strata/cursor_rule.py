from __future__ import annotations

from importlib import resources
from pathlib import Path
from typing import Any

RULE_DEST = Path(".cursor") / "rules" / "strata-memory-capture.mdc"
SKILL_DEST = Path(".cursor") / "skills" / "strata" / "SKILL.md"
RULE_PACKAGE = "cxl_strata.rules"
RULE_RESOURCE = "strata-memory-capture.mdc"
SKILL_PACKAGE = "cxl_strata.skills.strata"
SKILL_RESOURCE = "SKILL.md"
REQUIRED_MARKERS = ("/strata add", "/strata summary", "/strata prune")


def packaged_rule_text() -> str:
    return resources.files(RULE_PACKAGE).joinpath(RULE_RESOURCE).read_text(encoding="utf-8")


def packaged_skill_text() -> str:
    return resources.files(SKILL_PACKAGE).joinpath(SKILL_RESOURCE).read_text(encoding="utf-8")


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


def install_cursor_skill(dest: Path | None = None) -> dict[str, Any]:
    target = dest or SKILL_DEST
    result_path = str(target.resolve())
    skill_text = packaged_skill_text()

    if target.is_file():
        existing = target.read_text(encoding="utf-8")
        if "name: strata" in existing and all(marker in existing for marker in REQUIRED_MARKERS):
            return {"path": result_path, "status": "present"}

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(skill_text, encoding="utf-8")
    return {"path": result_path, "status": "installed"}


def install_cursor_integration(root: Path | None = None) -> dict[str, dict[str, Any]]:
    """Install the real Cursor skill plus the legacy rule fallback."""
    skill_dest = root / SKILL_DEST if root else None
    rule_dest = root / RULE_DEST if root else None
    return {
        "skill": install_cursor_skill(dest=skill_dest),
        "rule": install_cursor_rule(dest=rule_dest),
    }


def cursor_workspace_detected(root: Path) -> bool:
    return (root / ".cursor").exists() or (root / SKILL_DEST).is_file() or (root / RULE_DEST).is_file()


def install_supported_agent_integrations(root: Path) -> dict[str, dict[str, dict[str, Any]]]:
    """Install IDE-specific integrations only when the workspace uses that IDE."""
    if not cursor_workspace_detected(root):
        return {}
    return {"cursor": install_cursor_integration(root=root)}
