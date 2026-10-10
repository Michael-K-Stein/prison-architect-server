"""WireDataRequested helpers (src/bot/wiredata.py)."""

from __future__ import annotations

from typing import Any

from src.bot.state import GameState, StateNode
from src.bot.wiredata import (
    WIRE_DATA_REQUESTED,
    WireLink,
    connected_pairs,
    parse_objects,
    request,
    request_bytes,
    wire_data,
)
from src.protocol.snapshot import Node


def _tree() -> Node:
    link = Node(
        "[i 0]",
        [("To.i", 105), ("To.u", 324697), ("Triggered", False), ("TimeIndex", 0.0)],
    )
    meter = Node(
        "165",
        [("sablpwr", 500)],
        [
            Node("wirec", [("Size", 1)], [link]),
            Node("wirei", [("Size", 1)], [Node("[i 0]", [("Id.i", 7), ("Id.u", 9)])]),
        ],
    )
    other = Node("9", [("v", 0)])
    return Node("ObjectData", [], [other, meter])


def test_request_is_empty_rpc_94() -> None:
    assert WIRE_DATA_REQUESTED == 94
    assert request_bytes() == b""


def test_parse_objects_reads_links_and_inputs() -> None:
    wires = parse_objects(_tree())
    assert list(wires) == [165]
    meter = wires[165]
    assert meter.connections == (WireLink(105, 324697),)
    assert meter.inputs == ((7, 9),)
    assert connected_pairs(wires) == {(165, 105)}


def test_empty_wirec_is_kept() -> None:
    node = Node("165", [], [Node("wirec", [("Size", 0)]), Node("wirei", [("Size", 0)])])
    wires = parse_objects(Node("ObjectData", [], [node]))
    assert wires[165].connections == () and wires[165].inputs == ()


def test_state_merge_and_request() -> None:
    state = GameState()
    state.systems["ObjectData"] = StateNode()
    state.systems["ObjectData"].merge(_tree())
    assert wire_data(state)[165].connections[0].index == 105

    class Fake:
        sent: list[int] = []

        def raise_event(
            self, code: int, data: bytes, *, broadcast: bool = False
        ) -> bool:
            self.sent.append(code)
            state.updates["ObjectData"] += 3
            return True

        def wait_for(self, done: Any, timeout: float = 20) -> bool:
            return bool(done())

    fake = Fake()
    assert 165 in request(fake, state)
    assert fake.sent == [94]
