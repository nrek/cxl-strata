"""Local workspace knowledge index: SQLite over handoffs, blueprints, plans, and rules."""

from . import paths
from .paths import resolve_workspace_root, set_workspace_root

WORKSPACE_ROOT = paths.WORKSPACE_ROOT
DB_PATH = paths.DB_PATH

__all__ = ["WORKSPACE_ROOT", "DB_PATH", "resolve_workspace_root", "set_workspace_root"]
