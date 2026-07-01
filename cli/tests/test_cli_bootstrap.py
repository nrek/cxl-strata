from __future__ import annotations

import json

from typer.testing import CliRunner

from cxl_strata import cli, cursor_rule
from cxl_strata.workspace_index.paths import set_workspace_root


def test_global_init_runs_client_bootstrap(monkeypatch) -> None:
    calls: list[str] = []

    def fake_bootstrap() -> None:
        calls.append("bootstrap")

    monkeypatch.setattr(cli, "bootstrap_client_environment", fake_bootstrap, raising=False)

    result = CliRunner().invoke(cli.app, ["--init"])

    assert result.exit_code == 0
    assert calls == ["bootstrap"]


def test_install_cursor_integration_writes_project_skill_and_rule(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    result = cursor_rule.install_cursor_integration()

    rule = tmp_path / ".cursor" / "rules" / "strata-memory-capture.mdc"
    skill = tmp_path / ".cursor" / "skills" / "strata" / "SKILL.md"
    assert result["rule"]["status"] == "installed"
    assert result["rule"]["path"] == str(rule)
    assert result["skill"]["status"] == "installed"
    assert result["skill"]["path"] == str(skill)
    assert rule.is_file()
    assert skill.is_file()
    rule_text = rule.read_text(encoding="utf-8")
    skill_text = skill.read_text(encoding="utf-8")
    assert "/strata add" in rule_text
    assert "name: strata" in skill_text
    assert "/strata add" in skill_text
    assert "/strata summary" in skill_text
    assert "/strata prune" in skill_text


def test_init_command_installs_cursor_skill(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    set_workspace_root(tmp_path)
    (tmp_path / ".cursor").mkdir()

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
    assert (tmp_path / ".cursor" / "skills" / "strata" / "SKILL.md").is_file()


def test_init_command_does_not_force_cursor_skill_without_cursor_workspace(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    set_workspace_root(tmp_path)

    result = CliRunner().invoke(
        cli.app,
        [
            "init",
            "--org",
            "example-org",
        ],
    )

    assert result.exit_code == 0
    assert (tmp_path / ".strata" / "config.json").is_file()
    assert not (tmp_path / ".cursor" / "skills" / "strata" / "SKILL.md").exists()


def test_init_command_allows_workspace_config_without_project_repo(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    set_workspace_root(tmp_path)

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


def test_client_bootstrap_installs_cursor_skill(monkeypatch) -> None:
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
    def fake_install_supported_agent_integrations(root):
        calls.append(f"agents:{root}")
        return {
            "cursor": {
                "rule": {"path": ".cursor/rules/strata-memory-capture.mdc", "status": "installed"},
                "skill": {"path": ".cursor/skills/strata/SKILL.md", "status": "installed"},
            }
        }

    monkeypatch.setattr(
        cli.cursor_rule,
        "install_supported_agent_integrations",
        fake_install_supported_agent_integrations,
    )

    cli.bootstrap_client_environment()

    assert calls == [f"agents:{cli.paths.WORKSPACE_ROOT}", "index:proj", "run_app"]


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
