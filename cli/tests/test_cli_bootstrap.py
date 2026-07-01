from __future__ import annotations

from typer.testing import CliRunner

from cxl_strata import cli


def test_global_init_runs_client_bootstrap(monkeypatch) -> None:
    calls: list[str] = []

    def fake_bootstrap() -> None:
        calls.append("bootstrap")

    monkeypatch.setattr(cli, "bootstrap_client_environment", fake_bootstrap, raising=False)

    result = CliRunner().invoke(cli.app, ["--init"])

    assert result.exit_code == 0
    assert calls == ["bootstrap"]
