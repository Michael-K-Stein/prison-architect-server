"""Planning a whole building: validation, shared walls and the build order."""

from __future__ import annotations

import pytest

from src.bot import building

SPEC = {
    "x": 20,
    "y": 90,
    "width": 9,
    "height": 8,
    "entrances": [[4, 7]],
    "rooms": [
        {
            "type": "Cell",
            "x": 1,
            "y": 1,
            "w": 3,
            "h": 4,
            "door": [2, 5],
            "objects": [["Bed", 0, 0], ["Toilet", 1, 0]],
        },
        {
            "type": "Cell",
            "x": 5,
            "y": 1,
            "w": 3,
            "h": 4,
            "door": [6, 5],
            "objects": [["Bed", 0, 0], ["Toilet", 1, 0]],
        },
    ],
}


def _spec(**changes: object) -> dict:
    return {**SPEC, **changes}


def test_a_good_building_validates_and_shares_walls() -> None:
    b = building.parse(SPEC)
    assert building.validate(b) == []
    assert b.rooms[0].ring() & b.rooms[1].ring()  # the wall column x=4 is shared
    assert (4, 2) in building.walls(b)
    picture = building.render(b)
    assert picture[0] == "#########" and picture[5][2] == "D"


def test_rules_are_checked_per_room() -> None:
    bad = _spec(rooms=[{**SPEC["rooms"][0], "objects": [["Bed", 0, 0]]}])
    errors = building.validate(building.parse(bad))
    assert any("needs Toilet" in e for e in errors)


def test_overlap_and_wall_through_a_room_are_refused() -> None:
    moved = {**SPEC["rooms"][1], "x": 3}
    errors = building.validate(building.parse(_spec(rooms=[SPEC["rooms"][0], moved])))
    assert any("overlaps" in e or "walls run through" in e for e in errors)


def test_every_room_must_be_reachable() -> None:
    # two cells joined by a door in their shared wall, but no door to the corridor
    a = {
        **SPEC["rooms"][0],
        "door": [4, 2],
        "objects": [["Bed", 0, 0], ["Toilet", 1, 0]],
    }
    b = {
        **SPEC["rooms"][1],
        "door": [4, 2],
        "objects": [["Bed", 2, 0], ["Toilet", 1, 0]],
    }
    errors = building.validate(building.parse(_spec(rooms=[a, b])))
    assert any("cannot be reached" in e for e in errors)
    # a door onto the corridor fixes it
    a["door"] = [2, 5]
    assert building.validate(building.parse(_spec(rooms=[a, b]))) == []


def test_a_blocked_door_cell_is_refused() -> None:
    blocked = {**SPEC["rooms"][0], "door": [0, 1]}  # Bed at (0,0)-(0,1) is inside it
    errors = building.validate(building.parse(_spec(rooms=[blocked, SPEC["rooms"][1]])))
    assert any("blocks the cell inside the door" in e for e in errors)


def test_stages_come_in_the_right_order() -> None:
    names = [n for n, _ in building.stages(building.parse(SPEC))]
    assert names == ["foundation", "entrances", "walls", "doors", "rooms", "objects"]
    stages = dict(building.stages(building.parse(SPEC)))
    assert stages["foundation"][0]["width"] == 9
    assert {j["x"] for j in stages["entrances"]} == {24}
    assert all(j["tool"] == "wall" for j in stages["walls"])


def test_malformed_specs_are_reported() -> None:
    with pytest.raises(ValueError):
        building.parse({"x": 1})


def test_object_facing_in_a_spec_reaches_the_place_job() -> None:
    spec = {**SPEC, "rooms": [dict(SPEC["rooms"][0])]}
    spec["rooms"][0]["objects"] = [["Bed", 0, 0], ["Toilet", 1, 0, "left"]]
    b = building.parse(spec)
    jobs = dict(building.stages(b))["objects"]
    assert [j["facing"] for j in jobs] == ["down", "left"]
