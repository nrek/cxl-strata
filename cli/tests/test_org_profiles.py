from __future__ import annotations

import json
from pathlib import Path

import pytest

from cxl_strata import local_store


@pytest.fixture()
def strata_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(local_store, "USER_STRATA_DIR", tmp_path)
    monkeypatch.setattr(local_store, "USER_GLOBAL_FILE", tmp_path / "global.json")
    monkeypatch.setattr(local_store, "USER_SECRETS_FILE", tmp_path / "secrets.json")
    (tmp_path / "global.json").write_text(
        json.dumps(
            {
                "api_base_url": "https://strata.craftxlogic.com",
                "organization_slug": "craftxlogic",
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "secrets.json").write_text(
        json.dumps({"api_key": "strata_live_default_key"}),
        encoding="utf-8",
    )
    local_store.set_active_org(None)
    return tmp_path


def test_default_profile_uses_global_secrets(strata_home: Path) -> None:
    assert local_store.load_api_key() == "strata_live_default_key"
    cfg = local_store.load_config()
    assert cfg["organization_slug"] == "craftxlogic"


def test_org_alias_uses_separate_key(strata_home: Path) -> None:
    local_store.save_org_profile(
        "commonspace",
        api_key="strata_live_commonspace_key",
        org="commonspace",
    )
    local_store.set_active_org("commonspace")

    assert local_store.load_api_key() == "strata_live_commonspace_key"
    cfg = local_store.load_config()
    assert cfg["organization_slug"] == "commonspace"
    assert cfg["api_base_url"] == "https://strata.craftxlogic.com"


def test_org_alias_can_override_api_base_url(strata_home: Path) -> None:
    local_store.save_org_profile(
        "client-a",
        api_key="strata_live_client_a",
        org="client-a",
        api_base_url="https://strata.example.com",
    )
    local_store.set_active_org("client-a")
    cfg = local_store.load_config()
    assert cfg["api_base_url"] == "https://strata.example.com"


def test_unknown_org_alias_raises(strata_home: Path) -> None:
    local_store.set_active_org("missing")
    with pytest.raises(RuntimeError, match="Unknown org alias"):
        local_store.load_api_key()


def test_list_org_profiles(strata_home: Path) -> None:
    local_store.save_org_profile("commonspace", api_key="k1", org="commonspace")
    local_store.save_org_profile("seersite", api_key="k2", org="seersite")
    names = local_store.list_org_profiles()
    assert names == ["commonspace", "seersite"]
