"""The ``--compact`` packet view: few lines per packet, default view untouched."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from test_pa_events import (  # noqa: E402
    CASHFLOW,
    COLOUR,
    FINANCE,
    FOUNDATIONS,
    SPAWN,
    decode_and_get,
    packet,
)

from src.protocol.events import (  # noqa: E402
    COMPACT_WIDTH,
    compact_event,
    compact_lines,
    log_lines,
)
from src.protocol.snapshot import Node  # noqa: E402


def test_cashflow_is_one_line() -> None:
    assert compact_lines(packet(CASHFLOW)) == [
        "Operation:RaiseEvent Event 118 TransactionAdded finance_cost_cashflow +35"
    ]
    assert compact_event(118, decode_and_get(FOUNDATIONS)) == [
        "Event 118 TransactionAdded finance_cost_foundations -5280"
    ]
    assert compact_event(13, decode_and_get(SPAWN)) == [
        "Event 13 ObjectAdded uId 8427316 object 17 type 139"
    ]


def test_snapshot_fits_on_one_line() -> None:
    assert compact_lines(packet(FINANCE)) == [
        "Operation:RaiseEvent DirectoryData:Finance {tr.b=30075, v.6=30110}"
    ]


def test_set_properties_summary() -> None:
    (line,) = compact_lines(packet(COLOUR))
    assert line.endswith("Actor 1: colour = #8479f4 (alpha ff) (broadcast)"), line
    assert "Broadcast" not in line


def test_compact_is_shorter_than_default() -> None:
    for body in (CASHFLOW, FINANCE, COLOUR, SPAWN):
        assert len(compact_lines(packet(body))) <= len(log_lines(packet(body)))


def test_big_tree_is_summarised_not_spilled() -> None:
    from src.protocol import events

    tree = Node("T", [("a", 1)], [Node(f"c{i}", [("x", i)]) for i in range(60)])
    lines = events._compact_snapshot(None, tree)
    assert lines[0] == "DirectoryData:T {a=1}"
    assert len(lines) == 8 and lines[1] == "  c0 {x=0}"
    assert lines[-1] == "  …+54 more children"
    small = events._compact_snapshot(None, Node("T", [], [Node("c", [("x", 1)])]))
    assert small == ["DirectoryData:T [c {x=1}]"]
    assert COMPACT_WIDTH >= 100


def test_undecodable_event_shows_hex() -> None:
    (line,) = compact_event(9, b"\xff")
    assert "unparsed" in line and "ff" in line


def test_compact_snapshot_with_a_huge_node_stays_short():
    from src.protocol.events import COMPACT_MAX_CHILDREN, _compact_snapshot
    from src.protocol.snapshot import Node

    sectors = Node(
        "CrisisSectorData", [], [Node(str(i), [("x", i)]) for i in range(154)]
    )
    tree = Node("World", [("a", 1)], [sectors, Node("ClientData", [("gt", 10.0)])])
    lines = _compact_snapshot("World", tree)
    assert len(lines) <= COMPACT_MAX_CHILDREN + 2
    assert all(len(line) <= 162 for line in lines)
    assert any("154" in line or "more" in line for line in lines)
