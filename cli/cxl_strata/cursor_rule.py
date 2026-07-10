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

RULES_DIR_DEST = Path(".cursor") / "rules"
ORCHESTRATION_RESOURCE_DIR = "orchestration"
ORCHESTRATION_RULES = (
    "agent-context-bootstrap.mdc",
    "blueprints.mdc",
    "handoff-logging.mdc",
    "prior-art.mdc",
    "reports-organization.mdc",
    "workspace-knowledge.mdc",
    "workspace-repo-scope.mdc",
)

HOOKS_PACKAGE = "cxl_strata"
HOOKS_RESOURCE_DIR = "hooks"
HOOKS_JSON_DEST = Path(".cursor") / "hooks.json"
HOOKS_DIR_DEST = Path(".cursor") / "hooks"
HOOK_SCRIPTS = ("strata-session-digest.py", "reindex-workspace.py")


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


def packaged_orchestration_rule_text(name: str) -> str:
    return (
        resources.files(RULE_PACKAGE)
        .joinpath(ORCHESTRATION_RESOURCE_DIR)
        .joinpath(name)
        .read_text(encoding="utf-8")
    )


def packaged_hook_text(name: str) -> str:
    return (
        resources.files(HOOKS_PACKAGE)
        .joinpath(HOOKS_RESOURCE_DIR)
        .joinpath(name)
        .read_text(encoding="utf-8")
    )


def install_orchestration_rules(root: Path) -> dict[str, dict[str, Any]]:
    """Install the packaged orchestration rule bundle; never overwrite existing rules."""
    rules_dir = root / RULES_DIR_DEST
    rules_dir.mkdir(parents=True, exist_ok=True)
    results: dict[str, dict[str, Any]] = {}
    for name in ORCHESTRATION_RULES:
        target = rules_dir / name
        if target.is_file():
            results[name] = {"path": str(target.resolve()), "status": "present"}
            continue
        target.write_text(packaged_orchestration_rule_text(name), encoding="utf-8")
        results[name] = {"path": str(target.resolve()), "status": "installed"}
    return results


def install_hooks(root: Path) -> dict[str, dict[str, Any]]:
    """Install .cursor/hooks.json and hook scripts; never overwrite existing files."""
    results: dict[str, dict[str, Any]] = {}

    hooks_json = root / HOOKS_JSON_DEST
    if hooks_json.is_file():
        results["hooks.json"] = {"path": str(hooks_json.resolve()), "status": "present"}
    else:
        hooks_json.parent.mkdir(parents=True, exist_ok=True)
        hooks_json.write_text(packaged_hook_text("hooks.json"), encoding="utf-8")
        results["hooks.json"] = {"path": str(hooks_json.resolve()), "status": "installed"}

    hooks_dir = root / HOOKS_DIR_DEST
    for name in HOOK_SCRIPTS:
        target = hooks_dir / name
        if target.is_file():
            results[name] = {"path": str(target.resolve()), "status": "present"}
            continue
        hooks_dir.mkdir(parents=True, exist_ok=True)
        target.write_text(packaged_hook_text(name), encoding="utf-8", newline="\n")
        results[name] = {"path": str(target.resolve()), "status": "installed"}
    return results


def install_cursor_integration(root: Path | None = None) -> dict[str, Any]:
    """Install the Cursor skill, STRATA rule, orchestration rule bundle, and hooks."""
    skill_dest = root / SKILL_DEST if root else None
    rule_dest = root / RULE_DEST if root else None
    base = root or Path(".")
    return {
        "skill": install_cursor_skill(dest=skill_dest),
        "rule": install_cursor_rule(dest=rule_dest),
        "orchestration_rules": install_orchestration_rules(base),
        "hooks": install_hooks(base),
    }


def cursor_workspace_detected(root: Path) -> bool:
    return (root / ".cursor").exists() or (root / SKILL_DEST).is_file() or (root / RULE_DEST).is_file()


def install_supported_agent_integrations(
    root: Path, *, force: bool = False
) -> dict[str, dict[str, Any]]:
    """Install IDE-specific integrations.

    STRATA init is the Cursor workspace bootstrap, so init paths pass force=True
    to create .cursor/ even when it does not exist yet.
    """
    if not force and not cursor_workspace_detected(root):
        return {}
    return {"cursor": install_cursor_integration(root=root)}
