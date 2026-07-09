"""Installed STRATA client version (must match cli/pyproject.toml)."""

from __future__ import annotations

__version__ = "0.3.2"


def client_version() -> str:
    """Return the client version shipped with this code.

    Prefer the bundled constant so editable/dev checkouts reflect source
    bumps immediately. Fall back to package metadata only if the constant
    is missing.
    """
    if __version__:
        return __version__
    try:
        from importlib.metadata import version

        return version("cxl-strata")
    except Exception:  # noqa: BLE001
        return "0.0.0"