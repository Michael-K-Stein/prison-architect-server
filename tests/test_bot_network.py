"""Electricity network validation (src/bot/network.py)."""

from __future__ import annotations

from src.bot.network import ELECTRICITY, analyze, components


def _line(x0: int, x1: int, y: int) -> set[tuple[int, int]]:
    return {(x, y) for x in range(x0, x1 + 1)}


def test_components_split_on_gaps() -> None:
    cells = _line(0, 3, 0) | _line(6, 8, 0)
    assert [len(c) for c in components(cells)] == [4, 3]


def test_raw_line_with_consumer_is_flagged() -> None:
    cells = _line(0, 6, 5)
    objs = [
        {"Type": "WindTurbine", "Id.i": 1, "Pos.x": 1.0, "Pos.y": 3.5, "Powered": True},
        {"Type": "Light", "Id.i": 2, "Pos.x": 5.5, "Pos.y": 4.5, "Powered": False},
    ]
    out = analyze(cells, objs, ELECTRICITY)
    net = out["networks"][0]
    assert net["kind"] == "raw-green"
    assert (net["roles"]["raw"], net["consumers"], net["unpowered"]) == (1, 1, 1)
    assert not out["ok"] and "raw green energy" in out["problems"][0]


def test_transformer_separates_input_and_output() -> None:
    cells = _line(0, 3, 5) | _line(6, 9, 5)  # gap at x=4,5: the Transformer (2x2)
    objs = [
        {"Type": "SolarPanels", "Id.i": 1, "Pos.x": 1.5, "Pos.y": 4.0, "Powered": True},
        {"Type": "Transformer", "Id.i": 2, "Pos.x": 5.0, "Pos.y": 5.0, "Powered": True},
        {"Type": "Light", "Id.i": 3, "Pos.x": 8.5, "Pos.y": 4.5, "Powered": True},
    ]
    out = analyze(cells, objs, ELECTRICITY)
    assert [n["kind"] for n in out["networks"]] == ["raw-green", "ac"]
    assert out["ok"], out["problems"]


def test_any_utility_spec_works() -> None:
    from src.bot.network import Utility

    water = Utility(
        name="water",
        node="Water",
        sources={"cold": frozenset({"Pump"}), "hot": frozenset({"Boiler"})},
        classify=lambda net: "hot" if net["roles"]["hot"] else "cold",
    )
    objs = [{"Type": "Boiler", "Id.i": 1, "Pos.x": 1.5, "Pos.y": 1.5}]
    out = analyze({(1, 2), (2, 2)}, objs, water)
    assert out["utility"] == "water" and out["networks"][0]["kind"] == "hot"


def test_water_appliance_without_a_pump_is_unserved() -> None:
    from src.bot import network

    pipes = {(5, 16), (6, 16), (7, 16)}
    sink = {"Type": "Sink", "Pos.x": 6.5, "Pos.y": 16.5, "Id.i": 1}
    beside = {"Type": "Toilet", "Pos.x": 6.5, "Pos.y": 17.5, "Id.i": 4}
    far = {"Type": "Toilet", "Pos.x": 30.5, "Pos.y": 17.5, "Id.i": 2}
    pump = {"Type": "WaterPumpStation", "Pos.x": 6.5, "Pos.y": 14.5, "Id.i": 3}
    objects = [sink, far, beside]
    unserved = network.unserved(pipes, objects, network.WATER)
    assert [o["Id.i"] for o in unserved] == [1, 2, 4]
    # a pump next to the pipes feeds them; only a pipe ON the appliance's cell serves it
    unserved = network.unserved(pipes, [*objects, pump], network.WATER)
    assert [o["Id.i"] for o in unserved] == [2, 4]
