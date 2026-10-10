"""The game's prefabs as building specs."""

from __future__ import annotations

from src.bot import building, prefabs


def test_a_prefab_becomes_a_valid_single_room_building() -> None:
    spec = prefabs.to_spec("Library", 10, 20)
    assert (spec["x"], spec["y"]) == (10, 20)
    b = building.parse(spec)
    assert building.validate(b) == []
    assert b.rooms[0].type == "Library" and b.entrances


def test_facing_comes_from_the_prefab_orientation() -> None:
    spec = (
        prefabs.to_spec("Cinema", 0, 0)
        if not prefabs.PREFABS["Cinema"]["custom"]
        else None
    )
    assert spec is None  # the cinema prefab is an outdoor area (fences), not a room
    chairs = [o for o in prefabs.PREFABS["Cinema"]["objects"] if o[0] == "DeckChair"]
    assert chairs and all((o[3], o[4]) == (0, -1) for o in chairs)
    assert prefabs.FACING[(0, -1)] == "up"


def test_room_prefabs_are_listed_largest_first() -> None:
    names = prefabs.for_room("Cell")
    sizes = [prefabs.PREFABS[n]["w"] * prefabs.PREFABS[n]["h"] for n in names]
    assert sizes == sorted(sizes, reverse=True) and "LuxuryCell" in names
