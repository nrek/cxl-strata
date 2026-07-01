from __future__ import annotations

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
