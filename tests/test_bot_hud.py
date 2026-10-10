"""The bot HUD's pure helpers and its Application driven by pipe input (no network)."""

from __future__ import annotations

import threading
from types import SimpleNamespace

from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from src.bot import hud
from src.bot.actions import ACCEPT_GRANT, CANCEL_GRANT
from src.bot.catalog import ACTIONS, choices
from src.bot.session import Options
from src.bot.speed import GAME_SPEED_CHANGE
from src.bot.state import NEW_SPEECH
from src.bot.state import GameState, StateNode
from src.protocol import rpc
from src.protocol.grants import GRANTS


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

    def raise_event(self, code: int, data: bytes, *, broadcast: bool = False) -> bool:

        self.sent.append((code, data))
        return True


def test_grant_items_list_all_and_cancel_only_when_active() -> None:
    folders = hud.grant_items(["Grant_zzz_part"], None)
    assert len(folders) >= len(
        [n for n in GRANTS if n.count("_") == 1]
    )  # every known grant
    assert all(len(f.children) == 1 for f in folders)  # Accept only
    state = GameState()
    state.grants = lambda: {"Grant_bootstraps": "InProgress"}  # type: ignore[method-assign]
    by_title = {f.label: f for f in hud.grant_items([], state)}
    rows = by_title["Basic Detention Centre"].children
    assert [(r.action.code, r.values) for r in rows] == [
        (ACCEPT_GRANT, ("Grant_bootstraps",)),
        (CANCEL_GRANT, ("Grant_bootstraps",)),
    ]


def test_grant_with_streamed_objective_can_be_cancelled() -> None:
    by_title = {f.label: f for f in hud.grant_items(["Grant_bootstraps"], GameState())}
    rows = by_title["Basic Detention Centre"].children
    assert [r.action.code for r in rows] == [ACCEPT_GRANT, CANCEL_GRANT]


def test_locked_grants_are_dimmed_and_skipped() -> None:
    state = GameState()
    state.grants = lambda: {"Grant_bootstraps": "Completed"}  # type: ignore[method-assign]
    by_title = {f.label: f for f in hud.grant_items([], state)}
    assert not by_title["Administration Centre"].locked
    blocked = by_title["Security Procedure Certification"]  # needs bootstraps 1
    assert not blocked.locked or "Basic Detention Centre" not in blocked.locked
    locked = by_title["Governmental Security Ratings"]  # needs BasicSecurity
    assert locked.locked.startswith("locked: needs Security Procedure")
    rows = [by_title["Administration Centre"], locked, by_title["Prison Maintenance"]]
    assert hud._unlocked(rows, 1, 1, 0) == 2
    assert hud._unlocked(rows, 1, -1, 0) == 0
    assert hud._unlocked([locked], 0, 1, 0) == 0


def test_format_speed() -> None:
    assert hud.format_speed(None) == "?"
    assert hud.format_speed(0) == "paused"
    assert hud.format_speed(5) == "5x"


def test_quick_items_speed_values() -> None:
    items = hud.quick_items([])
    speeds = [i for i in items if i.action and i.action.code == GAME_SPEED_CHANGE]
    assert [i.values for i in speeds] == [(0,), (1,), (2,), (5,), (10,)]
    indexed = [i.values for i in hud.quick_items([], speed_index=True)][:5]
    assert indexed == [(0,), (1,), (2,), (3,), (4,)]


def test_speech_quick_items_and_broadcast() -> None:
    items = hud.quick_items([])
    warden = next(i for i in items if i.label == "Warden calls everyone")
    assert warden.values == (2,) and warden.action.code == NEW_SPEECH
    session = FakeSession()
    assert hud.send(session, warden.action, ["2", "Lockdown"]).startswith("sent")
    assert session.sent == [(NEW_SPEECH, rpc.build(NEW_SPEECH, 2, "Lockdown"))]


def test_all_items_cover_catalog_and_filter() -> None:
    items = hud.all_items([])
    codes = {i.action.code for i in items if i.action and i.group != "quick"}
    assert codes == set(ACTIONS)
    assert items[-1].special == "quit"
    found = hud.filter_items(items, "accept")
    assert found and "accept" in found[0].label.lower()
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


def test_state_folder_nests_systems_nodes_and_fields() -> None:
    state = GameState()
    node = StateNode(fields={"v": 1.23456})
    node.children["Child"] = StateNode(fields={"k": 7})
    state.systems["Finance"] = node
    top = hud.state_item(state)
    assert [r.label for r in top.rows] == ["Finance"]
    finance = top.rows[0].rows
    assert [(r.label, r.special) for r in finance] == [
        ("v: 1.23", "info"),
        ("Child", "group"),
    ]
    assert [r.label for r in finance[1].rows] == ["k: 7"]


def test_inmates_folder_lists_prisoners_with_bio() -> None:
    state = GameState()
    assert [i.special for i in hud.inmate_items(state)] == ["info"]  # no save yet
    objects = StateNode()
    for key, kind, first in (("[i 0]", "Prisoner", "Ann"), ("[i 1]", "Guard", "Bob")):
        node = StateNode(fields={"Type": kind, "Category": "Normal"})
        node.children["Bio"] = StateNode(
            fields={"Forname": first, "Surname": "Lee", "Age": 31}
        )
        objects.children[key] = node
    state.save = StateNode(children={"Objects": objects})
    rows = hud.inmate_items(state)
    assert [r.label for r in rows] == ["Ann Lee"]
    labels = [r.label for r in rows[0].rows]
    assert "Age: 31 years" in labels and "First name: Ann" in labels
    assert "Security group: Medium" in labels and "Biography" not in labels


def test_inmate_fields_are_readable() -> None:
    from src.bot import inmate_fields as f

    bio = {"SentenceF": 6.0, "Served": 1.5}
    assert f.value_of("Served", 1.5, bio)[0] == "1.5 of 6.0 years (25%)"
    assert f.title("BodyScale") == "Height scale" and f.title("HeadType") == "Face"
    assert f.title("WorkCredential") == f.title("WorkingCredential")
    assert f.title("CarrierId.i") == "Carried by (index)"
    assert f.value_of("CarrierId.i", 0xFFFFFFFF)[0] == "nobody"
    assert f.value_of("Carried", 0)[0] == "nothing"
    assert f.value_of("Carried", 7)[0] == "object #7"
    assert f.title("Carried") == "Carrying"
    assert f.value_of("HeadType", "Head8")[0] == "male face #8"
    assert f.value_of("SkinColour", "0x84512cff")[0] == "#84512c"
    assert f.value_of("Traits", ["Fraud", "Petty"])[0] == "Fraud, Petty"
    assert f.value_of("NextParole", "ThreeQuarters")[0].startswith("at three")
    assert f.title("SomeNewField") == "Some new field"


def test_inmate_stats_by_group_and_cell_occupancy() -> None:
    state = GameState()
    assert hud.inmate_stats(state) is None
    objects = StateNode()
    people = [
        {"Type": "Prisoner"},  # no Category: MinSec
        {"Type": "Prisoner", "Category": "MaxSec"},
        {"Type": "Prisoner", "Category": "MaxSec", "Damage": 1.0},  # dead
        {"Type": "Guard"},
    ]
    for i, fields in enumerate(people):
        objects.children[f"[i {i}]"] = StateNode(fields=fields)
    rooms = StateNode()
    for i, (kind, who) in enumerate([("Cell", 5), ("Cell", -1), ("Kitchen", -1)]):
        rooms.children[f"[i {i}]"] = StateNode(
            fields={"Id.i": i, "RoomType": kind, "Entity.i": who}
        )
    state.save = StateNode(children={"Objects": objects, "Rooms": rooms})
    groups, cells, total = hud.inmate_stats(state)
    assert (groups["MinSec"], groups["MaxSec"], total) == (1, 1, 2)
    assert cells == (1, 2)  # one of two cells occupied; the kitchen isn't a cell


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
    app = run_keys(session, "\x1bOQ\x1bOQ\x03")  # F2 (open), F2 (close), Ctrl-C
    assert app.ui.mode == "list" and app.ui.path == []
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


def test_menu_tree_nests_and_filter_searches_leaves() -> None:
    tree = hud.menu_tree([])
    labels = {i.label for i in tree}
    assert {"Game speed", "Staff", "Build", "All RPCs", "Leave / quit"} <= labels
    assert all(i.children for i in tree if i.special == "group")
    found = hud.filter_items(hud._leaves(tree), "hire guard")
    assert found and found[0].job is not None


def test_build_commands_make_valid_jobs() -> None:
    from src.bot import build

    for item in hud.build_items():
        assert item.job is not None and item.action is not None
        for spec in item.job([1] * len(item.action.args)):
            build.job_from(spec)


def test_hud_lines_format_money_time_and_names() -> None:
    summary = {"balance": 1234567.4, "time_index": 12.7, "object_types": {1: 5}}
    lines = hud.hud_lines(summary, "r", [], "c", {}, {1: "Wall"})
    assert "Bank: 1,234,567   Time: 13" in lines[2]
    assert "Wall: 5" in lines[4]


def test_fire_staff_folder_and_panel_click() -> None:
    session = FakeSession()
    objects = StateNode()
    for i, name in enumerate(["Guard", "Guard", "Cook"]):
        objects.children[str(i)] = StateNode(fields={"uId": 10 + i, "name": name})
    session.state.systems["ObjectData"] = objects
    app = hud.Hud(session, Options(app_id="x"), input=None, output=DummyOutput())
    assert app.staff_counts()["Guard"] == 2 and app.staff_counts()["Doctor"] == 0
    app.open_fire("Guard")
    rows = app.items()
    assert [r.action.code for r in rows] == [45, 45]
    assert rows[0].values == ((10, 0),)
    app.open_fire("Doctor")  # nobody: stays put
    assert app.ui.path == ["Staff", "Fire staff", "Guard"]


def test_inmate_panel_with_captured_prisoner() -> None:
    """A prisoner as run5 holds it: every row has a readable key and value."""
    bio = {
        "Forname": "John",
        "Surname": "Mackenzie",
        "Age": 40.0,
        "BodyType": 0,
        "BodyScale": 0.87,
        "HeadType": "Head8",
        "Traits": ["Fraud", "Theft", "Clever", "Petty"],
        "ReputationRevealed": True,
        "SentenceF": 6.0,
        "Served": 0.36,
        "NextParole": "Half",
        "CivilianClothes": False,
        "DrugAddiction": -1,
        "ClemencyChance": 0.0,
        "OriginalCategory": "MinSec",
        "StintNumber": 1,
        "WorkCredential": "Cook",
        "AgeCategory": "Young",
        "AgeToDieOldAge": -1.0,
        "SkinColour": "0x84512cff",
        "ClothingColour": "0x00000000",
    }
    fields = {
        "Type": "Prisoner",
        "Category": "MinSec",
        "Carried": 0,
        "CarrierId.i": -1,
        "CarrierId.u": -1,
    }
    node = StateNode(fields=fields)
    node.children["Bio"] = StateNode(fields=bio)
    convictions = StateNode()
    convictions.children["[i 0]"] = StateNode(
        fields={"Crime": "InsiderTrading", "SentenceF": 6.0}
    )
    node.children["Convictions"] = convictions
    state = GameState()
    state.save = StateNode(children={"Objects": StateNode(children={"[i 0]": node})})
    rows = hud.inmate_items(state)[0].rows
    text = {r.key: r.shown for r in rows if r.key}
    assert (
        text["Height scale"] == "87% of normal (shorter)"
        and text["Face"] == "male face #8"
    )
    assert text["Sentence"] == "6.0 years" and text["Served"] == "0.4 of 6.0 years (6%)"
    assert text["Work qualification"] == "Cook" and text["Carrying"] == "nothing"
    assert text["Carried by (index)"] == "nobody"
    assert text["Trait"] == "Fraud, Theft, Clever, Petty"
    assert text["Clothing colour"] == "none"
    assert text["Next parole hearing"] == "at half of the sentence"
    crime = next(r for r in rows if r.label == "Convictions").rows[0]
    assert crime.label == "Insider trading"
    assert [r.key for r in crime.rows] == ["Crime", "Sentence"]
    frags = hud.field_fragments(rows[0], "❯", "reverse")
    assert "bold" in frags[1][0] and frags[1][0] != frags[3][0]
