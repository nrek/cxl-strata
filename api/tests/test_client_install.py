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
    assert "sysconfig.get_path('scripts'" in body
    assert "--force-reinstall --no-cache-dir" in body
    assert 'PROFILE_FILES=("$HOME/.profile" "$HOME/.bashrc" "$HOME/.zshrc")' in body
    assert "STRATA_PATH_BLOCK_BEGIN" in body
    assert 'INDEX_ARGS=(index)' in body
    assert '"${STRATA_CMD[@]}" "${INDEX_ARGS[@]}"' in body
    assert 'APP_ARGS=(app --open)' in body
    assert "python3 -m cxl_strata.cli --init" in body
    assert "installs .cursor/skills/strata/SKILL.md when a Cursor workspace is detected" in body


def test_install_ps1_served(client: TestClient) -> None:
    response = client.get("/install.ps1")
    assert response.status_code == 200
    body = response.text
    assert "STRATA local client installer" in body
    assert "pip install" in body
    assert "STRATA pip user Scripts" in body
    assert "[Environment]::SetEnvironmentVariable" in body
    assert "python -m cxl_strata.cli" in body
    assert "sysconfig.get_path('scripts'" in body
    assert "--force-reinstall --no-cache-dir" in body
    assert "[EnvironmentVariableTarget]::User" in body
    assert "STRATA_PATH_BLOCK_BEGIN" in body
    assert '$indexArgs = @("index")' in body
    assert "Invoke-Strata @indexArgs" in body
    assert '$appArgs = @("app", "--open")' in body
    assert "python -m cxl_strata.cli --init" in body
    assert "installs .cursor\\skills\\strata\\SKILL.md when a Cursor workspace is detected" in body


def test_client_manifest(client: TestClient) -> None:
    response = client.get("/v1/client/manifest")
    assert response.status_code == 200
    body = response.json()
    assert body["api"] == "strata"
    assert body["version"]
    assert "install" in body
    assert "curl -fsSL" in body["install"]["unix_one_liner"]
    assert "unix_update" in body["install"]
    assert "windows_update" in body["install"]
    assert "-Init" not in body["install"]["windows_update"]
    assert "packages" in body
    assert "cli" in body["packages"]
    assert "#subdirectory=cli" in body["packages"]["cli"]["pip_spec"]
    assert body["workspace_knowledge"]["post_key_bootstrap"] == "python -m cxl_strata.cli --init"
    assert body["workspace_knowledge"]["cursor_skill"] == ".cursor/skills/strata/SKILL.md"
    assert body["workspace_knowledge"]["cursor_rule"] == ".cursor/rules/strata-memory-capture.mdc"
    assert "-Init" in body["workspace_knowledge"]["post_key_bootstrap_fallback_windows"]
    assert "-Project" not in body["workspace_knowledge"]["post_key_bootstrap_fallback_windows"]


def test_strata_large_logo_asset_served(client: TestClient) -> None:
    response = client.get("/assets/strata_large.png")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(b"\x89PNG")


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
