from __future__ import annotations

from cxl_strata import client_update
from cxl_strata.version import __version__, client_version


def test_client_version_matches_bundled_constant() -> None:
    assert client_version()
    assert __version__ == "0.3.3"


def test_update_status_offline_when_manifest_unreachable(
    monkeypatch,
) -> None:
    monkeypatch.setattr(client_update, "_api_base", lambda: "http://127.0.0.1:9")
    monkeypatch.setattr(client_update, "fetch_remote_manifest", lambda **_: None)
    status = client_update.update_status()
    assert status["local_version"] == client_version()
    assert status["online"] is False
    assert status["update_available"] is False


def test_update_status_detects_newer_remote(monkeypatch) -> None:
    monkeypatch.setattr(client_update, "_api_base", lambda: "https://strata.example.com")
    monkeypatch.setattr(
        client_update,
        "fetch_remote_manifest",
        lambda **_: {
            "version": "9.9.9",
            "install": {
                "unix_update": "curl -fsSL https://strata.example.com/install.sh | bash",
                "windows_update": (
                    "& ([scriptblock]::Create((irm https://strata.example.com/install.ps1)))"
                ),
            },
        },
    )
    status = client_update.update_status()
    assert status["online"] is True
    assert status["remote_version"] == "9.9.9"
    assert status["update_available"] is True
    assert status["local_version"] != "9.9.9"


def test_update_status_hides_cta_when_versions_match(monkeypatch) -> None:
    local = client_version()
    monkeypatch.setattr(client_update, "_api_base", lambda: "https://strata.example.com")
    monkeypatch.setattr(
        client_update,
        "fetch_remote_manifest",
        lambda **_: {"version": local, "install": {}},
    )
    status = client_update.update_status()
    assert status["update_available"] is False


def test_update_status_hides_cta_when_local_is_ahead(monkeypatch) -> None:
    monkeypatch.setattr(client_update, "client_version", lambda: "0.3.2")
    monkeypatch.setattr(client_update, "_api_base", lambda: "https://strata.example.com")
    monkeypatch.setattr(
        client_update,
        "fetch_remote_manifest",
        lambda **_: {"version": "0.3.0", "install": {}},
    )
    status = client_update.update_status()
    assert status["update_available"] is False
    assert client_update.is_remote_newer("0.3.2", "0.3.0") is False
    assert client_update.is_remote_newer("0.3.0", "0.3.2") is True


def test_run_client_update_refuses_invalid_base(monkeypatch) -> None:
    monkeypatch.setattr(
        client_update,
        "update_status",
        lambda: {
            "local_version": "0.3.2",
            "remote_version": "9.9.9",
            "update_available": True,
            "online": True,
            "api_base_url": "not-a-url",
        },
    )
    result = client_update.run_client_update()
    assert result["ok"] is False
    assert "invalid" in result["error"].lower()


def test_run_client_update_invokes_install_script(monkeypatch) -> None:
    calls: list[list[str]] = []

    class FakeCompleted:
        returncode = 0
        stdout = "installed"
        stderr = ""

    def fake_run(argv, **kwargs):
        calls.append(list(argv))
        return FakeCompleted()

    monkeypatch.setattr(
        client_update,
        "update_status",
        lambda: {
            "local_version": "0.3.0",
            "remote_version": "0.3.2",
            "update_available": True,
            "online": True,
            "api_base_url": "https://strata.example.com",
        },
    )
    monkeypatch.setattr(client_update, "_org_slug", lambda: "craftxlogic")
    monkeypatch.setattr(client_update.platform, "system", lambda: "Windows")
    monkeypatch.setattr(client_update.subprocess, "run", fake_run)
    monkeypatch.setattr(client_update, "schedule_app_restart", lambda **_: None)

    result = client_update.run_client_update()
    assert result["ok"] is True
    assert calls
    joined = " ".join(calls[0])
    assert "install.ps1" in joined
    assert "strata.example.com" in joined
    assert "-Org craftxlogic" in joined
    assert "-Init" not in joined
