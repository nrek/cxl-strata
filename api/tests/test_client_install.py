from __future__ import annotations

from fastapi.testclient import TestClient


def test_install_sh_served(client: TestClient) -> None:
    response = client.get("/install.sh")
    assert response.status_code == 200
    body = response.text
    assert "#!/usr/bin/env bash" in body
    assert "pip install" in body
    assert "/install.sh" in body
    assert "strata init" in body or "strata \"${INIT_ARGS[@]}\"" in body
    assert "STRATA pip user bin" in body
    assert "python3 -m cxl_strata.cli" in body


def test_install_ps1_served(client: TestClient) -> None:
    response = client.get("/install.ps1")
    assert response.status_code == 200
    body = response.text
    assert "STRATA local client installer" in body
    assert "pip install" in body
    assert "STRATA pip user Scripts" in body
    assert "[Environment]::SetEnvironmentVariable" in body
    assert "python -m cxl_strata.cli" in body


def test_client_manifest(client: TestClient) -> None:
    response = client.get("/v1/client/manifest")
    assert response.status_code == 200
    body = response.json()
    assert body["api"] == "strata"
    assert "install" in body
    assert "curl -fsSL" in body["install"]["unix_one_liner"]
    assert "packages" in body
    assert "cli" in body["packages"]
    assert "#subdirectory=cli" in body["packages"]["cli"]["pip_spec"]


def test_strata_logo_asset_served(client: TestClient) -> None:
    response = client.get("/assets/strata-logo.png")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(b"\x89PNG")


def test_favicon_and_icon_assets_served(client: TestClient) -> None:
    favicon = client.get("/favicon.ico")
    assert favicon.status_code == 200
    assert favicon.headers["content-type"] == "image/x-icon"

    icon = client.get("/assets/icons/favicon-32x32.png")
    assert icon.status_code == 200
    assert icon.headers["content-type"] == "image/png"
    assert icon.content.startswith(b"\x89PNG")

    manifest = client.get("/assets/icons/manifest.json")
    assert manifest.status_code == 200
    body = manifest.json()
    assert body["name"] == "STRATA"
    assert body["icons"]
