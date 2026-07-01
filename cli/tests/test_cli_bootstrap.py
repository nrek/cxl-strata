from __future__ import annotations

import json

from typer.testing import CliRunner

from cxl_strata import cli, cursor_rule


def test_global_init_runs_client_bootstrap(monkeypatch) -> None:
    calls: list[str] = []

    def fake_bootstrap() -> None:
        calls.append("bootstrap")

    monkeypatch.setattr(cli, "bootstrap_client_environment", fake_bootstrap, raising=False)

    result = CliRunner().invoke(cli.app, ["--init"])

    assert result.exit_code == 0
    assert calls == ["bootstrap"]


def test_install_cursor_rule_writes_project_rule(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    result = cursor_rule.install_cursor_rule()

    rule = tmp_path / ".cursor" / "rules" / "strata-memory-capture.mdc"
    assert result["status"] == "installed"
    assert result["path"] == str(rule)
    assert rule.is_file()
    text = rule.read_text(encoding="utf-8")
    assert "/strata add" in text
    assert "/strata summary" in text
    assert "/strata prune" in text


def test_init_command_installs_cursor_rule(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(
        cli.app,
        [
            "init",
            "--org",
            "example-org",
            "--project",
            "example-project",
            "--repo",
            "example-repo",
        ],
    )

    assert result.exit_code == 0
    assert (tmp_path / ".strata" / "config.json").is_file()
    assert (tmp_path / ".cursor" / "rules" / "strata-memory-capture.mdc").is_file()


def test_init_command_allows_workspace_config_without_project_repo(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(
        cli.app,
        [
            "init",
            "--api",
            "https://strata.example.com",
            "--org",
            "example-org",
        ],
    )

    assert result.exit_code == 0
    config = json.loads((tmp_path / ".strata" / "config.json").read_text(encoding="utf-8"))
    assert config["api_base_url"] == "https://strata.example.com"
    assert config["organization_slug"] == "example-org"
    assert "project_slug" not in config
    assert "repo_name" not in config


def test_client_bootstrap_installs_cursor_rule(monkeypatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr(cli, "harden_user_path", lambda: {"scripts_dir": "scripts"})
    monkeypatch.setattr(cli.local_store, "load_config", lambda: {"project_slug": "proj"})

    def fake_bootstrap_workspace_index(**kwargs):
        calls.append(f"index:{kwargs['project']}")
        return {"db_path": "db.sqlite", "index": {"indexed": 0}}

    monkeypatch.setattr(
        "cxl_strata.app.server.bootstrap_workspace_index",
        fake_bootstrap_workspace_index,
    )
    monkeypatch.setattr("cxl_strata.app.server.run_app", lambda **kwargs: calls.append("run_app"))
    def fake_install_cursor_rule():
        calls.append("rule")
        return {"path": ".cursor/rules/strata-memory-capture.mdc", "status": "installed"}

    monkeypatch.setattr(cli.cursor_rule, "install_cursor_rule", fake_install_cursor_rule)

    cli.bootstrap_client_environment()

    assert calls == ["rule", "index:proj", "run_app"]


def test_recent_command_allows_workspace_config_without_project(monkeypatch) -> None:
    captured: list[dict] = []

    class FakeResponse:
        def raise_for_status(self) -> None:
            return

        def json(self) -> dict:
            return {"results": []}

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return

        def get(self, path: str, params: dict) -> FakeResponse:
            captured.append({"path": path, "params": params})
            return FakeResponse()

    monkeypatch.setattr(cli.local_store, "load_config", lambda: {"organization_slug": "example-org"})
    monkeypatch.setattr(cli.api_client, "_client", lambda: FakeClient())

    result = CliRunner().invoke(cli.app, ["recent", "--days", "7"])

    assert result.exit_code == 0
    assert captured == [{"path": "/v1/memory-events", "params": {}}]
