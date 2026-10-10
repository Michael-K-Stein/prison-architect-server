"""Named map zones: set / resolve / persistence (src/bot/zones.py)."""

from __future__ import annotations

import pytest

from src.bot.names import NameError_
from src.bot.zones import Zones, bounds, mask_rows


def test_set_resolve_and_overlap(tmp_path) -> None:
    zones = Zones(tmp_path / "z.json")
    zones.bind("MKS2")
    zones.set("Food_Zone", 20, 66, 12, 7)
    spec = zones.resolve({"tool": "foundation", "zone": "Food_Zone"})
    assert spec == [{"tool": "foundation", "x": 20, "y": 66, "width": 12, "height": 7}]
    assert zones.overlapping(30, 70, 5, 5) == ["Food_Zone"]
    assert zones.overlapping(0, 0, 5, 5) == []
    assert zones.resolve({"x": 1}) == [{"x": 1}]


def test_saved_per_game(tmp_path) -> None:
    path = tmp_path / "z.json"
    zones = Zones(path)
    zones.bind("A")
    zones.set("Yard", 1, 2, 5, 5)
    zones.bind("B")
    assert zones.all() == {}
    again = Zones(path)
    again.bind("A")
    assert again.rects("Yard") == [(1, 2, 5, 5)]


def test_rejects_bad_input() -> None:
    zones = Zones(None)
    with pytest.raises(NameError_):
        zones.set("52", 0, 0, 1, 1)
    with pytest.raises(NameError_):
        zones.set("Ok", 0, 0, 0, 1)
    with pytest.raises(NameError_):
        zones.resolve({"zone": "Missing"})


def test_nested_groups() -> None:
    zones = Zones(None)
    zones.set("CellBlock:Min:Showers", 0, 0, 3, 3)
    zones.set("CellBlock:Min:Cells", 3, 0, 3, 3)
    zones.set("CellBlock:Max", 0, 5, 6, 2)
    assert zones.groups() == ["CellBlock", "CellBlock:Min"]
    assert len(zones.rects("CellBlock")) == 3
    assert zones.rects("CellBlock:Min") == [(0, 0, 3, 3), (3, 0, 3, 3)]
    jobs = zones.resolve({"tool": "demolish", "zone": "CellBlock:Min"})
    assert [(j["x"], j["width"]) for j in jobs] == [(0, 3), (3, 3)]
    with pytest.raises(NameError_):
        zones.set("CellBlock:Min", 0, 0, 1, 1)  # a group
    with pytest.raises(NameError_):
        zones.set("CellBlock:Max:Hall", 0, 0, 1, 1)  # under a rectangle
    assert zones.remove("CellBlock:Min")
    assert zones.all().keys() == {"CellBlock:Max"}


def test_mask_rows_blanks_outside_cells() -> None:
    assert bounds([(0, 0, 1, 1), (2, 1, 1, 1)]) == (0, 0, 3, 2)
    rows = ["WWW", "FFF"]
    assert mask_rows(rows, 0, 0, [(0, 0, 1, 1), (2, 1, 1, 1)]) == ["W  ", "  F"]
