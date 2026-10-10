from __future__ import annotations

from src.bot.state import StateNode
from src.protocol.net_keys import long_name
from src.protocol.snapshot import Node


def test_long_names():
    assert long_name("ObjectData", "st") == "SubType"
    assert long_name("ObjectData", "sl3.i") == "Slot3.i"
    assert long_name("ObjectData", "d.x") == "Dest.x"
    assert long_name("ObjectData", "zzz") is None
    assert long_name("Finance", "st") is None


def test_to_dict_labels_short_keys():
    node = StateNode()
    node.merge(Node("0", [("st", 2), ("Type", 5)]))
    assert node.to_dict(system="ObjectData") == {"SubType (st)": 2, "Type": 5}
    assert node.to_dict() == {"st": 2, "Type": 5}
