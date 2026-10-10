"""The bot's JSON control server, its CLI client, and headless room selection."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from pyphotonrealtime.realtime.lobby import TypedLobby
from typer.testing import CliRunner

from src.bot import flow
from src.bot.cli import app
from src.bot.control import ControlServer, call
from src.bot.session import ConnectError, Options
from src.bot.state import GameState, StateNode


class FakeSession:
    """Just what the control server touches; records sent RPCs."""

    def __init__(self) -> None:
        self.state = GameState()
        self.lock = threading.RLock()
        self.disconnected: object | None = None
        self.sent: list[tuple[int, bytes]] = []
        self.broadcasts: list[bool] = []
        host = SimpleNamespace(nick_name="Host")
        room = SimpleNamespace(name="Jail", players={1: host})
        self.client = SimpleNamespace(current_room=room)

    def raise_event(self, code: int, data: bytes, *, broadcast: bool = False) -> bool:
        self.sent.append((code, data))
        self.broadcasts.append(broadcast)
        return True

    def build(self, jobs: list[Any]) -> bool:
        self.sent.append((9, b"Construction"))
        self.built = jobs
        return True


def test_build_and_names(served: tuple[ControlServer, FakeSession]) -> None:
    server, session = served
    spec = {"tool": "place", "object": "Bed", "x": 3, "y": 4}
    status, body = call("POST", "/build", {"jobs": [spec]}, port=server.port)
    assert status == 200 and body["sent"] is True
    assert body["jobs"][0]["material"] == 5
    assert session.built[0].type == "Objects"
    status, body = call("POST", "/build", {"jobs": [{"tool": "x"}]}, port=server.port)
    assert status == 400 and "unknown tool" in body["error"]
    status, body = call("GET", "/names/rooms?q=cell", port=server.port)
    assert body["1"] == "Cell" and all("cell" in n.lower() for n in body.values())
    assert call("GET", "/names/nope", port=server.port)[0] == 404
    port = ["ctl", "--port", str(server.port)]
    result = CliRunner().invoke(app, [*port, "build", "room", "1", "2", "3", "3"])
    assert result.exit_code == 0, result.output
    assert session.built[0].type == "Designation"


@pytest.fixture
def served() -> Iterator[tuple[ControlServer, FakeSession]]:
    session = FakeSession()
    world = StateNode(fields={"a": 1})
    world.children["WorldData"] = StateNode(fields={"TimeIndex": 2.5})
    world.children["WorldData"].children["Deep"] = StateNode(fields={"x": 1})
    session.state.systems["World"] = world
    objects = session.state.systems.setdefault("ObjectData", StateNode())
    objects.children["17"] = StateNode(fields={"uId": 8427316, "t": 3})
    session.state.note("before start")
    server = ControlServer(session, port=0)
    server.start()
    yield server, session
    server.stop()


def test_state_and_nodes(served: tuple[ControlServer, FakeSession]) -> None:
    server, _ = served
    status, body = call("GET", "/state", port=server.port)
    assert status == 200
    assert body["time_index"] == 2.5
    assert body["room"] == "Jail"
    assert body["players"] == [{"actor": 1, "name": "Host"}]
    assert body["connected"] is True
    status, body = call("GET", "/state/World/WorldData?depth=0", port=server.port)
    assert status == 200
    assert body == {"TimeIndex": 2.5, "/children": 1}
    assert call("GET", "/state/World", port=server.port)[1]["/WorldData"]["/Deep"]
    status, body = call("GET", "/state/Nope", port=server.port)
    assert status == 404 and "error" in body


def test_actions(served: tuple[ControlServer, FakeSession]) -> None:
    server, _ = served
    _, body = call("GET", "/actions?kind=player", port=server.port)
    names = {a["name"] for a in body}
    assert "GameSpeedChange" in names
    assert all(a["kind"] == "player" and not a["blocked"] for a in body)
    _, everything = call("GET", "/actions?all=1", port=server.port)
    assert any(a["blocked"] for a in everything)
    speed = next(a for a in body if a["code"] == 96)
    assert speed["args"] == [
        {"name": "speed", "type": "int", "hint": "whole number", "source": "speed"}
    ]


def test_action_choices(served: tuple[ControlServer, FakeSession]) -> None:
    server, _ = served
    status, body = call("GET", "/actions/NewVehicleCallout", port=server.port)
    assert status == 200 and body["code"] == 43
    (arg,) = body["args"]
    assert arg["source"] == "vehicle"
    assert {"value": 3, "label": "RiotPolice"} in arg["choices"]
    _, body = call("GET", "/actions/45", port=server.port)
    assert body["name"] == "SackStaff"
    assert all(isinstance(c["value"], list) for c in body["args"][0]["choices"])
    assert call("GET", "/actions/Nope", port=server.port)[0] == 404


def test_send(served: tuple[ControlServer, FakeSession]) -> None:
    server, session = served
    status, body = call(
        "POST", "/send", {"action": "SackStaff", "args": ["#17"]}, port=server.port
    )
    assert status == 200
    assert body["sent"] is True and body["code"] == 45
    assert session.sent == [(45, bytes.fromhex(body["data_hex"]))]
    for bad in (
        {"action": "NoSuchThing", "args": []},
        {"action": 96, "args": ["fast"]},
        {"action": "GameSpeedChange", "args": []},
        {"action": 56, "args": ["1,2", "3"]},
    ):
        status, body = call("POST", "/send", bad, port=server.port)
        assert status == 400 and body["error"]
    assert len(session.sent) == 1


def test_events_are_numbered(served: tuple[ControlServer, FakeSession]) -> None:
    server, session = served
    _, body = call("GET", "/events", port=server.port)
    assert [e["line"] for e in body["events"]] == ["before start"]
    session.state.note("object added: #1")
    session.state.note("money +5 x")
    _, body = call("GET", "/events?since=1", port=server.port)
    assert [(e["seq"], e["line"]) for e in body["events"]] == [
        (2, "object added: #1"),
        (3, "money +5 x"),
    ]
    assert body["last"] == 3
    _, body = call("GET", "/events?since=0&limit=1", port=server.port)
    assert len(body["events"]) == 1
    assert list(session.state.feed)[-1] == "money +5 x"


def test_wait_and_quit(served: tuple[ControlServer, FakeSession]) -> None:
    server, _ = served
    status, body = call("POST", "/wait", {"seconds": 0.05}, port=server.port)
    assert status == 200 and body["room"] == "Jail"
    assert call("POST", "/nope", {}, port=server.port)[0] == 404
    status, body = call("POST", "/quit", {}, port=server.port)
    assert body == {"quit": True}
    assert server.wait() == "quit"


def test_wait_returns_on_disconnect() -> None:
    session = FakeSession()
    server = ControlServer(session, port=0)
    session.disconnected = "timeout"
    assert server.wait(poll=0.01) == "disconnected"
    server.stop()


def test_ctl_commands(served: tuple[ControlServer, FakeSession]) -> None:
    server, session = served
    runner = CliRunner()
    port = ["ctl", "--port", str(server.port)]
    result = runner.invoke(app, [*port, "state"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["room"] == "Jail"
    result = runner.invoke(app, [*port, "state", "World", "WorldData", "--depth", "0"])
    assert json.loads(result.output) == {"TimeIndex": 2.5, "/children": 1}
    assert runner.invoke(app, [*port, "state", "Nope"]).exit_code == 1
    result = runner.invoke(app, [*port, "actions", "--kind", "player"])
    assert result.exit_code == 0 and "GameSpeedChange" in result.output
    result = runner.invoke(app, [*port, "action", "GameSpeedChange"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["args"][0]["choices"][0]["label"] == "paused"
    result = runner.invoke(app, [*port, "send", "GameSpeedChange", "2"])
    assert result.exit_code == 0, result.output
    assert session.sent[-1][0] == 96
    assert runner.invoke(app, [*port, "send", "GameSpeedChange"]).exit_code == 1
    result = runner.invoke(app, [*port, "events", "--since", "0"])
    assert json.loads(result.output)["last"] == 1
    assert runner.invoke(app, [*port, "wait", "0"]).exit_code == 0
    assert runner.invoke(app, [*port, "quit"]).exit_code == 0
    assert server.stopped.is_set()


def _room(name: str, is_open: bool = True) -> Any:
    return SimpleNamespace(name=name, is_open=is_open)


def test_choose_room() -> None:
    rooms = [_room("Closed", False), _room("Alpha"), _room("Beta")]
    assert flow.choose_room(rooms, None) == "Alpha"
    assert flow.choose_room(rooms, "beta") == "Beta"
    with pytest.raises(ConnectError, match="closed"):
        flow.choose_room(rooms, "Closed")
    with pytest.raises(ConnectError, match="open games: 'Alpha', 'Beta'"):
        flow.choose_room(rooms, "Gamma")
    with pytest.raises(ConnectError, match="no open games"):
        flow.choose_room([_room("Closed", False)], None)


def test_join_room_headless(monkeypatch: pytest.MonkeyPatch) -> None:
    stopped: list[bool] = []
    fake = SimpleNamespace(stop=lambda: stopped.append(True))
    joined: list[str] = []
    monkeypatch.setattr(flow, "connect", lambda opts, region, recorder: fake)
    monkeypatch.setattr(flow, "lobbies_of", lambda s: [TypedLobby()])
    monkeypatch.setattr(flow, "list_rooms", lambda s, lobby: [_room("Alpha")])
    monkeypatch.setattr(flow, "enter_room", lambda s, o, name: joined.append(name))
    opts = Options(app_id="x")
    assert flow.join_room(opts, "eu", None) is fake
    assert joined == ["Alpha"] and not stopped
    with pytest.raises(ConnectError):
        flow.join_room(opts, "eu", "Missing")
    assert stopped == [True]


def test_ctl_broadcast_speakers_and_recipients(
    served: tuple[ControlServer, FakeSession],
) -> None:
    server, session = served
    runner = CliRunner()
    port = ["ctl", "--port", str(server.port)]
    result = runner.invoke(app, [*port, "broadcast", "Hello all", "--from", "Warden"])
    assert result.exit_code == 0, result.output
    assert session.sent[-1][0] == 117  # NewSpeechAdded
    assert session.broadcasts[-1] is True  # default: everyone
    result = runner.invoke(
        app, [*port, "broadcast", "Just you", "--from", "the ceo", "--to", "host"]
    )
    assert result.exit_code == 0, result.output
    assert session.broadcasts[-1] is False
    assert runner.invoke(app, [*port, "broadcast", "x", "--from", "Nobody"]).exit_code
    assert runner.invoke(
        app, [*port, "broadcast", "x", "--from", "CEO", "--to", "all"]
    ).exit_code
