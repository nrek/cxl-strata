from __future__ import annotations

from pathlib import Path

import cxl_strata


def _package_root() -> Path:
    return Path(cxl_strata.__file__).resolve().parent


def test_local_app_includes_strata_logo_asset() -> None:
    root = _package_root()
    logo = root / "static" / "strata-logo.png"
    index = (root / "static" / "index.html").read_text(encoding="utf-8")

    assert logo.is_file()
    assert logo.read_bytes().startswith(b"\x89PNG")
    assert "/static/strata-logo.png" in index
