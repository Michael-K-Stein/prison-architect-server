"""Planning the cables and pipes that connect unserved objects."""

from __future__ import annotations

from src.bot import connect

AC_ROW = {(x, 5) for x in range(0, 6)}
TRANSFORMER = {"Type": "Transformer", "Pos.x": 0.0, "Pos.y": 4.0, "Id.i": 1}
LIGHT = {"Type": "Light", "Pos.x": 10.5, "Pos.y": 5.5, "Id.i": 2, "Powered": False}


def test_a_cable_runs_from_the_nearest_fed_cell() -> None:
    plan = connect.plan("electricity", AC_ROW, [TRANSFORMER, LIGHT], 20, 20)
    assert plan["targets"] == 1 and plan["skipped"] == []
    cells = {
        (j["x"] + i, j["y"] + k)
        for j in plan["jobs"]
        for i in range(j["width"])
        for k in range(j["height"])
    }
    assert (9, 5) in cells and (6, 5) in cells  # up to the light's neighbour
    assert all(j["object"] == "ElectricalCable" for j in plan["jobs"])


def test_powered_objects_are_left_alone() -> None:
    lit = {**LIGHT, "Powered": True}
    assert (
        connect.plan("electricity", AC_ROW, [TRANSFORMER, lit], 20, 20)["targets"] == 0
    )


def test_a_cable_never_touches_the_raw_network() -> None:
    raw = {(x, 6) for x in range(6, 12)}  # a raw green line beside the way
    gen = {"Type": "SolarPanels", "Pos.x": 12.5, "Pos.y": 6.0, "Id.i": 3}
    plan = connect.plan("electricity", AC_ROW | raw, [TRANSFORMER, gen, LIGHT], 20, 20)
    touched = {
        (j["x"] + i, j["y"] + k)
        for j in plan["jobs"]
        for i in range(j["width"])
        for k in range(j["height"])
    }
    assert not any(abs(x - rx) + abs(y - ry) <= 1 for x, y in touched for rx, ry in raw)


def test_a_pipe_ends_on_the_appliance_cell() -> None:
    pump = {"Type": "WaterPumpStation", "Pos.x": 1.5, "Pos.y": 4.5, "Id.i": 1}
    sink = {"Type": "Toilet", "Pos.x": 8.5, "Pos.y": 7.5, "Id.i": 2}
    pipes = {(x, 6) for x in range(0, 4)}
    plan = connect.plan("water", pipes, [pump, sink], 20, 20)
    assert plan["targets"] == 1
    cells = {
        (j["x"] + i, j["y"] + k)
        for j in plan["jobs"]
        for i in range(j["width"])
        for k in range(j["height"])
    }
    assert (8, 7) in cells and all(j["object"] == "PipeSmall" for j in plan["jobs"])


def test_runs_are_straight_segments() -> None:
    assert connect._runs([(0, 0), (1, 0), (2, 0), (2, 1), (2, 2)]) == [
        (0, 0, 3, 1),
        (2, 1, 1, 2),
    ]
