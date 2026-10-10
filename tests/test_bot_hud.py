"""The bot HUD's pure helpers and its Application driven by pipe input (no network)."""

from __future__ import annotations

import threading
from types import SimpleNamespace

from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from src.bot import hud
from src.bot.actions import ACCEPT_GRANT, CANCEL_GRANT, FIRST_GRANT
from src.bot.catalog import ACTIONS, choices
from src.bot.session import Options
from src.bot.speed import GAME_SPEED_CHANGE
from src.bot.state import GameState, StateNode
from src.protocol import rpc


class FakeSession:
    """Just what the HUD reads and calls."""

    def __init__(self, objectives: dict[str, str] | None = None) -> None:
        self.state = GameState()
        self.objectives = objectives or {}
        self.sent: list[tuple[int, bytes]] = []
        self.disconnected: object | None = None
        self.joined = True
        self.lock = threading.RLock()
        player = SimpleNamespace(nick_name="Host", actor_number=1)
        room = SimpleNamespace(name="Prison", players={1: player})
        self.client = SimpleNamespace(current_room=room, local_player=player)

    def raise_event(self, code: int, data: bytes) -> bool:
        self.sent.append((code, data))
        return True


def test_grant_names() -> None:
    assert hud.grant_names(["Grant_a", "Grant_b_part", "Other", b"Grant_c"]) == [
        "a",
        "c",
    ]
    assert hud.grant_names(["Other"]) == [FIRST_GRANT]


def test_format_speed() -> None:
    assert hud.format_speed(None) == "?"
    assert hud.format_speed(0) == "paused"
    assert hud.format_speed(5) == "5x"


def test_quick_items_speed_values_and_grants() -> None:
    items = hud.quick_items(["Grant_x"])
    speeds = [i for i in items if i.action and i.action.code == GAME_SPEED_CHANGE]
    assert [i.values for i in speeds] == [(0,), (1,), (2,), (5,), (10,)]
    indexed = [i.values for i in hud.quick_items([], speed_index=True)][:5]
    assert indexed == [(0,), (1,), (2,), (3,), (4,)]
    grants = {
        (i.action.code, i.values) for i in items if i.action and "grant" in i.label
    }
    assert grants == {(ACCEPT_GRANT, ("x",)), (CANCEL_GRANT, ("x",))}


def test_all_items_cover_catalog_and_filter() -> None:
    items = hud.all_items([])
    codes = {i.action.code for i in items if i.action and i.group != "quick"}
    assert codes == set(ACTIONS)
    assert items[-1].special == "quit"
    found = hud.filter_items(items, "accept")
    assert found and all("accept" in i.label.lower() for i in found[:2])
    assert hud.filter_items(items, "") == items
    assert hud.filter_items(items, "zzzzqqq") == []


def test_hud_lines() -> None:
    summary = GameState().summary()
    lines = hud.hud_lines(summary, "Room", ["Host #1"], "in room")
    text = "\n".join(lines)
    assert "Room: Room" in text and "Host #1" in text
    assert "Bank: ?" in text and "Speed: ?" in text
    assert "Errors: 0" in text


def test_room_info() -> None:
    session = FakeSession()
    assert hud.room_info(session) == ("Prison", ["Host #1"], "in room")
    session.disconnected = "gone"
    assert hud.room_info(session)[2] == "disconnected (gone)"
    assert hud.room_info(SimpleNamespace())[0] == "-"


def test_browse_text() -> None:
    state = GameState()
    node = StateNode(fields={"v": 1})
    node.children["Child"] = StateNode(fields={"k": b"\xff"})
    state.systems["Finance"] = node
    assert "Finance" in hud.browse_text(state, "")
    assert '"/Child"' in hud.browse_text(state, "Finance")
    assert '"k": "ff"' in hud.browse_text(state, "Finance/Child")
    assert "No state" in hud.browse_text(state, "Nope")


def test_send_logs_result_and_errors() -> None:
    session = FakeSession()
    line = hud.send(session, ACTIONS[GAME_SPEED_CHANGE], ["5"])
    assert line == "sent GameSpeedChange(5) -> queued"
    assert session.sent == [(GAME_SPEED_CHANGE, rpc.build(GAME_SPEED_CHANGE, 5))]
    assert hud.send(session, ACTIONS[GAME_SPEED_CHANGE], ["x"]).startswith("error")
    assert len(session.sent) == 1


def run_keys(session: FakeSession, keys: str) -> hud.Hud:
    with create_pipe_input() as pipe:
        pipe.send_text(keys)
        app = hud.Hud(session, Options(app_id="x"), input=pipe, output=DummyOutput())
        app.run()
    return app


def test_app_filter_and_quick_action() -> None:
    session = FakeSession()
    run_keys(session, "speed 5x\r\x11")  # filter, Enter, Ctrl-Q
    assert session.sent == [(GAME_SPEED_CHANGE, rpc.build(GAME_SPEED_CHANGE, 5))]


def test_app_argument_form() -> None:
    session = FakeSession()
    name = ACTIONS[GAME_SPEED_CHANGE].signature
    app = run_keys(session, f"{name}\r7\r\x11")
    assert session.sent == [(GAME_SPEED_CHANGE, rpc.build(GAME_SPEED_CHANGE, 7))]
    assert any("sent GameSpeedChange(7)" in line for line in app.ui.log)


def test_app_browse_and_disconnect() -> None:
    session = FakeSession()
    session.state.feed.append("object added: #1")
    app = run_keys(session, "\x1bOQFinance\x1bOQ\x03")  # F2, path, F2, Ctrl-C
    assert app.ui.mode == "list"
    assert "object added: #1" in app.ui.log
    session.disconnected = "bye"
    run_keys(session, "")  # exits on its own


def test_quick_items_vehicles_and_squads() -> None:
    state = GameState()
    sqd = StateNode()
    sqd.children["0"] = StateNode(fields={"Id.u": 77, "Id.i": 5, "Type": 3})
    state.systems["Squads"] = StateNode(children={"sqd": sqd})
    items = hud.quick_items([], state=state)
    labels = [i.label for i in items]
    assert "Set speed paused" in labels
    vehicles = {i.label: i.values for i in items if i.action and i.action.code == 43}
    assert vehicles["Call vehicle RiotPolice"] == (3,)
    dismiss = [i for i in items if i.label.startswith("Dismiss squad")]
    assert [(i.action and i.action.code, i.values) for i in dismiss] == [
        (44, ((77, 5),))
    ]


def test_app_argument_choices() -> None:
    session = FakeSession()
    name = ACTIONS[43].signature
    labels = [c.label for c in choices(ACTIONS[43].args[0])]
    down = "\x1b[B" * labels.index("RiotPolice")
    app = run_keys(session, f"{name}\r{down}\r\x11")  # open, Down..., Enter, Ctrl-Q
    assert session.sent == [(43, rpc.build(43, 3))]
    assert app.ui.mode == "list"


def test_app_argument_choices_filter() -> None:
    session = FakeSession()
    run_keys(session, f"{ACTIONS[43].signature}\rriot\r\x11")  # typing filters
    assert session.sent == [(43, rpc.build(43, 3))]  # RiotPolice
