from __future__ import annotations

from src.bot import catalog
from src.bot.state import GameState
from src.protocol.grants import GRANTS, canonical


def test_canonical_grant_names():
    assert canonical("greenmachine") == "Grant_GreenMachine"
    assert canonical("GreenMachine") == "Grant_GreenMachine"
    assert canonical("Grant_GreenMachine") == "Grant_GreenMachine"
    assert canonical("bootstraps") == "Grant_bootstraps"
    assert canonical("administration") == "Grant_Administration"
    assert canonical("target_PassReform") == "target_PassReform"
    assert canonical("SomethingNew") == "Grant_SomethingNew"  # the host decides


def test_table_has_the_base_and_dlc_grants():
    assert GRANTS["Grant_bootstraps"]["start"] == 20000
    assert GRANTS["Grant_bootstraps"]["completion"] == 10000
    assert ("Completed", "Grant_bootstraps", 0) in GRANTS["Grant_FirstCellBlock"][
        "requires"
    ]
    assert "Grant_GreenMachine" in GRANTS


def test_accept_grant_takes_any_spelling():
    action = catalog.find("AcceptGrant")
    state = GameState()
    for typed in ("greenMachine", "Grant_GreenMachine"):
        assert catalog.parse_args(action, [typed], state) == ["Grant_GreenMachine"]
    labels = [c.label for c in catalog.choices(action.args[0], state)]
    assert "Grant_GreenMachine: Green Machine" in labels


def test_hints_for_commands():
    from src.bot import hints

    assert any("Closed" in h for h in hints.for_action("IntakeTypeChange"))
    assert any(
        "Workmen CANNOT" in h
        for h in hints.for_jobs([{"tool": "place", "object": "JailDoor"}])
    )
    assert any(
        "indoor" in h.lower()
        for h in hints.for_jobs([{"tool": "place", "object": "Battery"}])
    )
    action = catalog.find("IntakeTypeChange")
    assert catalog.parse_args(action, ["Closed"], GameState()) == [0]
    assert catalog.parse_args(action, ["fill capacity"], GameState()) == [1]
    assert catalog.parse_args(action, ["None"], GameState()) == [0]


def test_staff_needs_flags_exhausted_workmen():
    from src.bot.state import StateNode

    state = GameState()
    state.systems["ObjectData"] = StateNode(
        children={
            "9": StateNode({"uId": 1, "name": "Workman", "el": 0.0, "rs": 1}),
            "10": StateNode({"uId": 2, "name": "Workman", "el": 80.0, "rs": 0}),
            "11": StateNode({"uId": 3, "name": "Cook", "el": 10.0, "rs": 0}),
            "12": StateNode({"uId": 4, "name": "Prisoner"}),
        }
    )
    needs = state.staff_needs()
    assert needs["exhausted"] == 1
    assert needs["summary"] == {
        "Cook": {"count": 1, "exhausted": 0, "tired": 1, "ok": 0},
        "Workman": {"count": 2, "exhausted": 1, "tired": 0, "ok": 1},
    }
    assert [p["status"] for p in needs["staff"]] == ["tired", "exhausted", "ok"]


def test_foundation_and_room_replies_carry_the_entrance_hint():
    from src.bot import hints

    for tool in ("foundation", "room"):
        found = hints.for_jobs([{"tool": tool, "x": 1, "y": 1}])
        assert any("VALID entrance" in h for h in found), tool
    assert any(
        "prisoners cannot open a StaffDoor" in h for h in hints.TOPICS["entrance"]
    )
