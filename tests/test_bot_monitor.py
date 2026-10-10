"""Tests for the live game monitor."""

from __future__ import annotations

import threading
from types import SimpleNamespace

from pyphotonrealtime.realtime.room import RoomInfo
from rich.console import Console

from src.bot import monitor
from src.bot.monitor import GameMonitor, build_games_table, run_monitor
from src.bot.session import Options


def _plain(renderable: object) -> str:
    c = Console(record=True, width=120)
    c.print(renderable)
    return c.export_text()


def _make_room(
    name: str,
    *,
    player_count: int = 1,
    max_players: int = 4,
    is_open: bool = True,
    removed: bool = False,
    mas: str = "",
    players: list[str] | None = None,
) -> RoomInfo:
    room = RoomInfo(name)
    room.player_count = player_count
    room.max_players = max_players
    room.is_open = is_open
    room.removed_from_list = removed
    props: dict[str, object] = {}
    if mas:
        props["MAS"] = mas
    if players is not None:
        props["players"] = players
    room.custom_properties = props
    return room


def test_build_games_table_empty() -> None:
    table = build_games_table({}, statuses={"eu": "connected"}, interval=3.0)
    text = _plain(table)
    assert "Prison Architect Live Games" in text
    assert "0 games" in text
    assert "No live games currently active" in text
    assert "eu: connected" in text


def test_build_games_table_with_rooms() -> None:
    room1 = _make_room(
        "Alcatraz",
        player_count=2,
        max_players=4,
        is_open=True,
        mas="Bob",
        players=["Bob", "Alice"],
    )
    room2 = _make_room(
        "FullHouse",
        player_count=4,
        max_players=4,
        is_open=False,
        mas="Charlie",
    )
    data = {"eu": [room1], "us": [room2]}

    table = build_games_table(data, interval=2.5, updated_at="12:00:00")
    text = _plain(table)

    assert "2 games" in text
    assert "6 players" in text
    assert "in 2 regions" in text
    assert "Alcatraz" in text
    assert "FullHouse" in text
    assert "2 / 4" in text
    assert "4 / 4" in text
    assert "open" in text
    assert "closed" in text
    assert "Bob (host)" in text
    assert "Alice" in text
    assert "Charlie" in text
    assert "Refresh: every 2.5s" in text


def test_build_games_table_empty_room_players() -> None:
    room = _make_room("GhostTown", player_count=0, max_players=8)
    table = build_games_table({"eu": [room]})
    text = _plain(table)
    assert "GhostTown" in text
    assert "0 / 8" in text
    assert "none" in text


class _FakeSession:
    def __init__(self, rooms: list[RoomInfo] | None = None) -> None:
        self.lock = threading.RLock()
        self.client = SimpleNamespace(
            room_list={r.name: r for r in (rooms or [])},
            op_join_lobby=lambda lobby: True,
        )
        self.lobby_joined = True
        self.disconnected = None
        self.stopped = False

    def wait_for(self, fn: object, timeout: float = 10.0) -> bool:
        return True

    def stop(self) -> None:
        self.stopped = True


def test_game_monitor_lifecycle() -> None:
    r1 = _make_room("Game1", player_count=1)
    r2 = _make_room("Game2", player_count=2, removed=True)
    fake_eu = _FakeSession([r1, r2])
    fake_us = _FakeSession([])

    sessions = {"eu": fake_eu, "us": fake_us}

    def factory(opts: Options, region: str, recorder: object) -> _FakeSession:
        return sessions[region]

    opts = Options(app_id="test")
    monitor_obj = GameMonitor(opts, ["eu", "us"], session_factory=factory)

    with monitor_obj:
        assert monitor_obj.statuses["eu"] == "connected"
        assert monitor_obj.statuses["us"] == "connected"
        snapshot = monitor_obj.snapshot()
        # r2 was removed, so only r1 should be returned
        assert len(snapshot["eu"]) == 1
        assert snapshot["eu"][0].name == "Game1"
        assert len(snapshot["us"]) == 0

    assert fake_eu.stopped
    assert fake_us.stopped


def test_game_monitor_handles_connect_error() -> None:
    def failing_factory(opts: Options, region: str, recorder: object) -> _FakeSession:
        raise RuntimeError("network down")

    opts = Options(app_id="test")
    monitor_obj = GameMonitor(opts, ["eu"], session_factory=failing_factory)

    with monitor_obj:
        assert "error" in monitor_obj.statuses["eu"]
        snapshot = monitor_obj.snapshot()
        assert snapshot == {}


def test_run_monitor_once(monkeypatch: object) -> None:
    opts = Options(app_id="test")
    fake = _FakeSession([_make_room("Solo", player_count=1)])

    class FakeMonitor:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self.statuses = {"eu": "connected"}

        def __enter__(self) -> FakeMonitor:
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def snapshot(self) -> dict[str, list[RoomInfo]]:
            return {"eu": [_make_room("Solo", player_count=1)]}

    out_console = Console(record=True, width=120)
    run_monitor(
        opts,
        region="eu",
        once=True,
        console=out_console,
        monitor_factory=FakeMonitor,
    )

    text = out_console.export_text()
    assert "Solo" in text
    assert "1 / 4" in text


def test_cli_monitor_help() -> None:
    from typer.testing import CliRunner
    from src.cli.app import app

    runner = CliRunner()
    result = runner.invoke(app, ["bot", "monitor", "--help"])
    assert result.exit_code == 0
    assert "--region" in result.output
    assert "--interval" in result.output
    assert "--once" in result.output


def test_cli_games_help() -> None:
    from typer.testing import CliRunner
    from src.cli.app import app

    runner = CliRunner()
    result = runner.invoke(app, ["bot", "games", "--help"])
    assert result.exit_code == 0
    assert "--region" in result.output
    assert "--interval" in result.output
    assert "--once" in result.output


def test_cli_monitor_once(monkeypatch: object) -> None:
    from typer.testing import CliRunner
    from src.cli.app import app
    from src.bot import cli

    called: list[dict[str, object]] = []

    def fake_run_monitor(opts: object, **kwargs: object) -> None:
        called.append(kwargs)

    monkeypatch.setattr(cli, "run_monitor", fake_run_monitor)
    runner = CliRunner()
    result = runner.invoke(
        app, ["bot", "--app-id", "test-app", "monitor", "-r", "eu", "--once"]
    )
    assert result.exit_code == 0
    assert len(called) == 1
    assert called[0]["region"] == "eu"
    assert called[0]["once"] is True
