from __future__ import annotations

import pytest

from src.bot import catalog
from src.bot.names import NameError_, ObjectNames
from src.bot.state import GameState, StateNode


def test_set_get_and_one_name_per_object(tmp_path):
    names = ObjectNames(tmp_path / "n.json")
    names.bind("MKS")
    names.set("Main_Power_Station", 8444868, 52)
    assert names.get("Main_Power_Station") == (8444868, 52)
    assert names.name_of(52, 8444868) == "Main_Power_Station"
    names.set("Power", 8444868, 52)  # renames
    assert names.get("Main_Power_Station") is None
    assert names.all() == {"Power": (8444868, 52)}


def test_names_are_saved_per_game(tmp_path):
    path = tmp_path / "n.json"
    a = ObjectNames(path)
    a.bind("MKS")
    a.set("Pump", 1, 2)
    b = ObjectNames(path)
    b.bind("MKS")
    assert b.get("Pump") == (1, 2)
    b.bind("Other")
    assert b.get("Pump") is None


@pytest.mark.parametrize("bad", ["52", "#52", "1,2", "has space", "", "-x"])
def test_bad_names(bad):
    with pytest.raises(NameError_):
        ObjectNames(None).set(bad, 1, 2)


def _state_with_station():
    state = GameState(names=ObjectNames(None))
    state.systems["ObjectData"] = StateNode(
        children={"52": StateNode({"uId": 8444868, "t": 241})}
    )
    state.names.set("Main_Power_Station", 8444868, 52)
    return state


def test_names_replace_ids_in_arguments():
    state = _state_with_station()
    switch = catalog.find("ElectricalSwitch")
    assert catalog.parse_args(switch, ["Main_Power_Station", "off"], state) == [
        52,
        False,
    ]
    remove = catalog.find("RemoveRoom")
    assert catalog.parse_args(remove, ["Main_Power_Station"], state) == [(8444868, 52)]
    assert catalog.parse_args(remove, ["#52"], state) == [(8444868, 52)]


def test_named_objects_show_in_notes_and_summary():
    state = _state_with_station()
    assert state.named(52, 8444868) == "Main_Power_Station "
    assert state.named(53) == ""
    assert state.summary()["named"] == {
        "Main_Power_Station": {"uId": 8444868, "index": 52}
    }
