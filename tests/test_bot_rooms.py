"""The room planner: every room type gets a plan that fits its rules."""

from __future__ import annotations

import pytest

from src.bot import rooms
from src.protocol.room_rules import ROOM_RULES


def _cells(plan: rooms.RoomPlan) -> list[tuple[int, int]]:
    out = []
    for obj in plan.objects:
        w, h = rooms.size_of(obj.name)
        out += [(obj.dx + i, obj.dy + j) for i in range(w) for j in range(h)]
    return out


@pytest.mark.parametrize("room", sorted(ROOM_RULES))
@pytest.mark.parametrize("variant", rooms.VARIANTS)
def test_every_room_has_a_valid_plan(room: str, variant: str) -> None:
    plan = rooms.plan_room(room, variant)
    cells = _cells(plan)
    assert len(cells) == len(set(cells)), "objects overlap"
    assert all(0 <= x < plan.w and 0 <= y < plan.h for x, y in cells)
    # the right-hand column and bottom row stay free: the corridor to the door
    assert all(x != plan.door for x, _ in cells)
    assert all(y != plan.h - 1 for _, y in cells)
    min_size = ROOM_RULES[room][0]
    if min_size:
        assert plan.w >= min_size[0] and plan.h >= min_size[1]


def test_required_objects_are_present() -> None:
    names = {o.name for o in rooms.plan_room("Cell").objects}
    assert "Toilet" in names
    assert names & {"Bed", "Mattress", "ComfyBed", "CoffinBed", "OldBed", "CampBed"}


def test_lavish_is_bigger_than_minimum() -> None:
    small, big = rooms.plan_room("Office"), rooms.plan_room("Office", "lavish")
    assert big.w * big.h > small.w * small.h
    assert len(big.objects) > len(small.objects)


def test_zone_only_rooms_have_no_foundation() -> None:
    assert not rooms.plan_room("Forestry").building
    assert rooms.plan_room("Yard").building
    stages = rooms.stages(rooms.plan_room("Forestry"), 10, 10)
    assert [s[0]["tool"] for s in stages] == ["room"]


def test_stages_put_the_door_in_the_bottom_wall() -> None:
    plan = rooms.plan_room("Library")
    foundation, door, zone, objects = rooms.stages(plan, 20, 30)
    assert foundation[0]["width"] == plan.w + 2
    assert door[0]["y"] == 30 + plan.h + 1
    assert door[0]["x"] == 20 + 1 + plan.door
    assert zone[0]["kind"] == "Library"
    assert {j["object"] for j in objects} >= {"LibraryBookshelf", "SortingTable"}


def test_design_checks_the_rules() -> None:
    plan, errors = rooms.design("Cell", 3, 4, 2, [("Bed", 0, 0), ("Toilet", 1, 0)])
    assert errors == [] and plan.building
    _, errors = rooms.design("Cell", 3, 4, 2, [("Bed", 0, 0)])
    assert errors == ["needs Toilet"]
    _, errors = rooms.design("Cell", 3, 4, 2, [("Bed", 2, 3), ("Toilet", 1, 0)])
    assert any("leaves the room" in e for e in errors)
    _, errors = rooms.design("Cell", 3, 4, 2, [("Bed", 0, 0), ("Toilet", 0, 1)])
    assert any("overlaps" in e for e in errors)
    _, errors = rooms.design("Cell", 1, 2, 0, [("Bed", 0, 0), ("Toilet", 0, 1)])
    assert any("below the minimum" in e for e in errors)


def test_constraints_list_footprints() -> None:
    info = rooms.constraints("Library")
    assert info["min_interior"] == [5, 5]
    shelf = info["required"][0]["one_of"][0]
    assert (shelf["name"], shelf["w"], shelf["h"]) == ("LibraryBookshelf", 3, 1)


def test_room_cli_parsers() -> None:
    import pytest

    from src.bot import room_cli

    assert room_cli.parse_size("6x5") == (6, 5)
    assert room_cli.parse_objects(["Bed:0:1"]) == [("Bed", 0, 1)]
    with pytest.raises(ValueError):
        room_cli.parse_size("6")
    with pytest.raises(ValueError):
        room_cli.parse_objects(["Bed:0"])


def test_wall_runs_find_a_neighbours_wall() -> None:
    from src.bot import room_cli

    rows = ["WWWWW", "WFFFW", "WWWWW"]
    assert room_cli.wall_runs(["W..", "W..", "W.."], 10, 5) == [(10, 5, 1, 3)]
    assert room_cli.wall_runs(rows, 0, 0)[0] == (0, 0, 5, 1)
    assert room_cli.wall_runs(["..."], 0, 0) == []
