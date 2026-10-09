"""The main.py command line: command listing, option help, and common-option merging."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402
from typer.testing import CliRunner  # noqa: E402

from src.cli import local as local_module  # noqa: E402
from src.cli.app import app  # noqa: E402

runner = CliRunner()


def test_root_help_lists_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for name in ("local", "proxy", "bot", "capture"):
        assert name in result.output


def test_local_help_shows_options():
    result = runner.invoke(app, ["local", "--help"])
    assert result.exit_code == 0
    for flag in (
        "--upstream",
        "--listen",
        "--ip",
        "--timeout",
        "--region",
        "--max-players",
    ):
        assert flag in result.output


def test_proxy_help_shows_options():
    result = runner.invoke(app, ["proxy", "--help"])
    assert result.exit_code == 0
    for flag in ("--port", "--upstream", "--follow", "--record", "--hide"):
        assert flag in result.output


@pytest.fixture
def captured_local(monkeypatch):
    """Replace the server start with a recorder of the CommonOptions it receives."""
    calls = []

    def fake_start_local(opts, upstream=None):
        calls.append((opts, upstream))

    monkeypatch.setattr(local_module, "start_local", fake_start_local)
    return calls


def test_options_before_subcommand_are_used(captured_local):
    result = runner.invoke(app, ["-l", "10.0.0.1", "-r", "eu", "local"])
    assert result.exit_code == 0, result.output
    ((opts, upstream),) = captured_local
    assert opts.listen == "10.0.0.1"
    assert opts.region == "eu"
    assert upstream is None


def test_value_after_subcommand_wins(captured_local):
    result = runner.invoke(
        app, ["-l", "10.0.0.1", "local", "-l", "0.0.0.0", "--max-players", "8"]
    )
    assert result.exit_code == 0, result.output
    ((opts, _),) = captured_local
    assert opts.listen == "0.0.0.0"
    assert opts.max_players == 8
    assert opts.ip == "127.0.0.1"
    assert opts.timeout == 60


def test_local_matches_dockerfile_invocation(captured_local):
    result = runner.invoke(
        app,
        [
            "local",
            "-l",
            "0.0.0.0",
            "-i",
            "203.0.113.5",
            "--timeout",
            "30",
            "-r",
            "home",
            "--max-players",
            "6",
        ],
    )
    assert result.exit_code == 0, result.output
    ((opts, _),) = captured_local
    assert (opts.listen, opts.ip, opts.timeout, opts.region, opts.max_players) == (
        "0.0.0.0",
        "203.0.113.5",
        30,
        "home",
        6,
    )


def test_max_players_out_of_range_is_rejected_before_start():
    result = runner.invoke(app, ["local", "--max-players", "99"])
    assert result.exit_code != 0
    assert "max_players must be between 1 and 16" in result.output
