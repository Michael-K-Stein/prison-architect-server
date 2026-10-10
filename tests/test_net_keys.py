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


def test_finance_keys_use_the_whole_dotted_key():
    assert long_name("Finance", "v.6") == "Balance"
    assert long_name("Finance", "tr.v.22") == "PowerExport"
    assert long_name("Finance", "tr.tOO") == "OtherOutgoing"
    assert long_name("Finance", "tr.v.99") is None
    assert long_name("Finance", "pwr_Kitchen") == "PrisonerWageRate_Kitchen"
    assert long_name("Finance", "sp") == "SalePrice"


def test_to_dict_labels_short_keys():
    node = StateNode()
    node.merge(Node("0", [("st", 2), ("Type", 5)]))
    assert node.to_dict(system="ObjectData") == {"SubType (st)": 2, "Type": 5}
    assert node.to_dict() == {"st": 2, "Type": 5}


def test_demolish_is_a_flooring_job_with_the_demolition_material():
    from src.bot import build

    job = build.job_from(
        {
            "tool": "demolish",
            "x": 1,
            "y": 2,
            "width": 5,
            "height": 5,
            "material": "DemolishWalls",
        }
    )
    assert (job.type, job.material) == ("flooring", 3)


def test_child_names_are_labelled_too():
    node = StateNode()
    node.merge(Node("46", [], [Node("cr", [("Size", 1)]), Node("l", [("Size", 1)])]))
    out = node.to_dict(system="SectorSystem")
    assert out["/ContainedRooms (cr)"] == {"Size": 1}
    assert "/Targets (l)" in out
