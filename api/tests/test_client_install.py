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


def test_install_ps1_served(client: TestClient) -> None:
    response = client.get("/install.ps1")
    assert response.status_code == 200
    assert "STRATA local client installer" in response.text
    assert "pip install" in response.text


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
