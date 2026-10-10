"""GameState: merging DirectoryData deltas and object/objective/money events."""

from __future__ import annotations

import zlib

from src.bot.state import GameState
from src.protocol.rpc import build


def _str(text: str) -> bytes:
    raw = text.encode()
    return bytes([len(raw)]) + raw


def _node(name: str, fields: list[tuple[str, int, bytes]], children=()) -> bytes:
    out = b"<" + _str(name) + bytes([len(fields)])
    for key, kind, value in fields:
        out += _str(key) + bytes([kind]) + value
    return out + bytes([len(children)]) + b"".join(children) + b">"


def _event(system: str, tree: bytes) -> bytes:
    blob = zlib.compress(tree) + len(tree).to_bytes(2, "big") + b"\x03"
    return build(9, system, blob)


def _int(value: int) -> bytes:
    return value.to_bytes(4, "little", signed=True)


def test_deltas_merge_by_node_name() -> None:
    state = GameState()
    state.apply(9, _event("Finance", _node("Finance", [("v.6", 1, _int(100))])))
    world = _node("World", [], [_node("WorldData", [("SecondsPlayed", 1, _int(5))])])
    state.apply(9, _event("World", world))
    speed = _node("World", [], [_node("ClientData", [("gt", 1, _int(2))])])
    state.apply(9, _event("World", speed))
    state.apply(9, _event("Finance", _node("Finance", [("v.6", 1, _int(40))])))
    assert state.balance == 40
    assert state.speed == 2
    assert state.value("World", "WorldData", "SecondsPlayed") == 5
    assert state.updates == {"Finance": 2, "World": 2}


def test_list_items_are_replaced_not_merged() -> None:
    state = GameState()
    cell = _node("[i 0]", [("x", 1, _int(1))])
    two = [cell, _node("[i 1]", [("x", 1, _int(2))])]
    state.apply(9, _event("CellData", _node("CellData", [], two)))
    one = [_node("[i 0]", [("y", 1, _int(9))])]
    state.apply(9, _event("CellData", _node("CellData", [], one)))
    assert state.systems["CellData"].to_dict() == {"/[i 0]": {"y": 9}}


def test_objects_objectives_and_money() -> None:
    state = GameState()
    state.apply(13, build(13, (8427316, 17), 139))
    assert state.objects_of_type(139) == [(8427316, 17)]
    state.apply(14, build(14, (8427316, 17)))
    assert state.object_types() == {}
    objective = _node("Objective", [("Name", 4, _str("Grant_x"))])
    state.apply(9, _event("Objective", objective))
    assert list(state.objectives) == ["Grant_x"]
    state.apply(21, build(21, "Grant_x", True))
    assert state.objectives == {}
    state.apply(118, build(118, -5280, "finance_cost_foundations", 0, 0))
    assert state.transactions[-1].amount == -5280
    assert state.summary()["recent"][-1] == "money -5280 finance_cost_foundations"


def test_alerts_from_staff_and_speech() -> None:
    state = GameState()
    item = _node(
        "[i 0]",
        [("tts", 4, _str("d11_staffalert_summary_PRISONERS03")), ("aa", 1, _int(132))],
    )
    alert = _node("StaffAlert", [], [_node("sa", [("Size", 1, _int(1))], [item])])
    state.apply(9, _event("StaffAlert", alert))
    state.apply(9, _event("StaffAlert", alert))  # still showing: not repeated
    state.apply(117, build(117, 1, "help_warning_prisonerreleased"))
    lines = [line for _, _, line in state.since(0)]
    assert lines[0] == "alert: Warden: The general quality of our cells is too low."
    assert lines[1].startswith("alert: The CEO: Reform Programs are key")
    assert len(lines) == 2 and len(state.summary()["alerts"]) == 2


def test_area_from_cell_data() -> None:
    state = GameState()
    items = [
        _node(
            "[i 0]",
            [("x", 1, _int(1)), ("y", 1, _int(1)), ("Mat", 4, _str("ConcreteWall"))],
        ),
        _node(
            "[i 1]",
            [("x", 1, _int(2)), ("y", 1, _int(1)), ("Mat", 4, _str("BuildingFrame"))],
        ),
        _node(
            "[i 2]",
            [("x", 1, _int(1)), ("y", 1, _int(2)), ("Mat", 4, _str("ConcreteFloor"))],
        ),
    ]
    tree = _node("CellData", [], [_node("CellData", [], items)])
    state.apply(9, _event("CellData", tree))
    area = state.area(1, 1, 2, 2)
    assert area["rows"] == ["WB", "F."]
    assert area["materials"]["nothing"] == 1


def test_bad_payload_counts_an_error() -> None:
    state = GameState()
    state.apply(9, b"\x12\x05World\x12\x02xx")
    assert state.errors == 1


def test_host_stalled_after_silent_world_snapshots() -> None:
    state = GameState()
    assert not state.host_stalled(now=1e9)  # still joining: no snapshot yet
    world = _node("World", [], [_node("ClientData", [("gt", 1, _int(0))])])
    state.apply(9, _event("World", world))
    seen = state.world_seen
    assert seen > 0
    assert not state.host_stalled(now=seen + 5)
    assert state.host_stalled(now=seen + 11)
    state.apply(9, _event("World", world))  # a paused game still sends snapshots
    assert not state.host_stalled(now=state.world_seen + 1)


def test_summary_reports_host_stalled() -> None:
    state = GameState()
    state.apply(9, _event("Finance", _node("Finance", [("v.6", 1, _int(7))])))
    assert state.summary()["host_stalled"] is False  # no World snapshot yet
    state.world_seen = 1.0  # long ago
    assert state.summary()["host_stalled"] is True


def test_staff_alerts_are_interrupts_with_the_games_advice() -> None:
    state = GameState()
    item = _node(
        "[i 0]",
        [
            ("tts", 4, _str("d11_staffalert_urgentsummary_DOCTOR01")),
            ("aa", 1, _int(132)),
        ],
    )
    alert = _node("StaffAlert", [], [_node("sa", [("Size", 1, _int(1))], [item])])
    state.apply(9, _event("StaffAlert", alert))
    (first,) = state.take_new_alerts()
    assert first.urgent and first.id == "DOCTOR01"
    assert "Doctors" in first.text
    assert first.title == "Nobody is working in the Infirmary."
    assert first.advice.startswith("We can't treat anyone")
    assert state.take_new_alerts() == []  # delivered once
    assert [a.seq for a in state.alerts_since(0)] == [1]
    assert first.as_dict()["urgent"] is True


def test_todo_lists_exhausted_staff_with_the_staffroom_advice() -> None:
    state = GameState()
    state._exhausted_staff = lambda: 3  # type: ignore[method-assign]
    item = next(i for i in state.todo() if i["id"] == "StaffExhausted")
    assert item["text"] == "3 staff members are exhausted."
    assert item["advice"] == "Build a Staff Room so they can rest."


def test_going_green_tab_lists_the_six_info_items_in_order() -> None:
    state = GameState()
    items = state.going_green()
    assert [i["title"] for i in items] == [
        "Going Green!",
        "Basic Farming",
        "Advanced Farming",
        "Green Energy",
        "Narcotic Production",
        "Environmentally Friendly",
    ]
    energy = next(i for i in items if i["id"] == "HelpGreenEnergy")
    assert [s["title"] for s in energy["sections"]][:2] == [
        "Green energy types",
        "Weather effects",
    ]
    assert all(s["text"] for s in energy["sections"])
