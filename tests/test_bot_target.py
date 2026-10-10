"""``bot REGION:GAME`` skips the region and game pickers."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

import src.bot.cli as bot_cli
from src.cli.app import app


@pytest.mark.parametrize(
    "argv",
    [
        ["bot", "au:MKS2", "--password", "123"],
        ["bot", "--password", "123", "au:MKS2"],
    ],
)
def test_target_picks_region_and_game(monkeypatch, argv) -> None:
    calls = []
    monkeypatch.setattr(
        bot_cli, "run", lambda opts, game=None: calls.append((opts, game))
    )
    monkeypatch.setattr(bot_cli, "require_app_id", lambda opts: None)
    result = CliRunner().invoke(app, argv)
    assert result.exit_code == 0, result.output
    [(opts, game)] = calls
    assert (opts.region, game, opts.password) == ("au", "MKS2", "123")


def test_option_value_with_colon_is_not_a_target(monkeypatch) -> None:
    seen = []
    monkeypatch.setattr(bot_cli, "require_app_id", lambda opts: None)
    monkeypatch.setattr(
        bot_cli, "fetch_regions", lambda opts, rec: seen.append(opts) or {}
    )
    result = CliRunner().invoke(
        app, ["bot", "--name-server", "1.2.3.4:5058", "regions"]
    )
    assert result.exit_code == 0, result.output
    assert seen[0].name_server == "1.2.3.4:5058"
    assert seen[0].region is None
