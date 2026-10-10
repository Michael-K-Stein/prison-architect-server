"""``WireDataRequested`` (94): ask the host for the wiring links of wired objects.

The host answers inside its normal ``ObjectData`` stream (journal2, "WireDataRequested"):
while its flag is set, every wired object (e.g. the PowerExportMeter) adds ``wirec``
(its outgoing connections) and ``wirei`` (the objects wired into it) to its entry.
These are the links made by ``WiredObjectConnect`` (92), not the cable cells in
``Save Electricity``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

from src.protocol import rpc

if TYPE_CHECKING:
    from src.bot.state import GameState, StateNode
    from src.protocol.snapshot import Node

WIRE_DATA_REQUESTED = 94
CONNECTIONS = "wirec"
INPUTS = "wirei"


@dataclass(frozen=True)
class WireLink:
    """One entry of ``wirec``: a connection from a wired object to another."""

    index: int
    uid: int
    triggered: bool = False
    time_index: float = 0.0
    via: tuple[dict[str, Any], ...] = ()
    """The ``Via`` list (extra waypoints; elements kept as raw fields)."""


@dataclass(frozen=True)
class WireData:
    """The wiring of one object."""

    index: int
    connections: tuple[WireLink, ...] = ()
    inputs: tuple[tuple[int, int], ...] = ()
    """``(index, uId)`` of each object wired into this one (``wirei``)."""
    extra: dict[str, Any] = field(default_factory=dict)


def _fields(node: Node | StateNode) -> dict[str, Any]:
    return dict(node.fields)


def _children(node: Node | StateNode) -> list[tuple[str, Any]]:
    kids = node.children
    if isinstance(kids, dict):
        return list(kids.items())
    return [(c.name, c) for c in kids]


def _items(node: Node | StateNode | None) -> list[Node | StateNode]:
    """The ``[i N]`` elements of a list node, in order."""
    if node is None:
        return []
    items = [(n, c) for n, c in _children(node) if n.startswith("[i ")]
    items.sort(key=lambda it: int(it[0][3:-1]) if it[0][3:-1].isdigit() else 0)
    return [c for _, c in items]


def _link(node: Node | StateNode) -> WireLink:
    f = _fields(node)
    via = tuple(_fields(v) for v in _items(dict(_children(node)).get("Via")))
    return WireLink(
        int(f.get("To.i", -1)),
        int(f.get("To.u", 0)),
        bool(f.get("Triggered", False)),
        float(f.get("TimeIndex", 0.0)),
        via,
    )


def parse_object(index: int, node: Node | StateNode) -> WireData | None:
    """The wiring in one ``ObjectData`` object entry, None if it has no ``wirec``."""
    kids = dict(_children(node))
    if CONNECTIONS not in kids and INPUTS not in kids:
        return None
    links = tuple(_link(n) for n in _items(kids.get(CONNECTIONS)))
    inputs = tuple(
        (int(_fields(n).get("Id.i", -1)), int(_fields(n).get("Id.u", 0)))
        for n in _items(kids.get(INPUTS))
    )
    return WireData(index, links, inputs)


def parse_objects(objects: Node | StateNode) -> dict[int, WireData]:
    """Wiring by object index from an ``ObjectData`` tree or merged node."""
    out: dict[int, WireData] = {}
    for name, child in _children(objects):
        if not name.isdigit():
            continue
        data = parse_object(int(name), child)
        if data is not None:
            out[int(name)] = data
    return out


def wire_data(state: GameState) -> dict[int, WireData]:
    """The latest wiring the host sent, by object index."""
    with state.lock:
        node = state.systems.get("ObjectData")
        return parse_objects(node) if node is not None else {}


def connected_pairs(wires: dict[int, WireData]) -> set[tuple[int, int]]:
    """Every ``(from index, to index)`` connection."""
    return {(w.index, link.index) for w in wires.values() for link in w.connections}


def request_bytes() -> bytes:
    """The ``Data`` of a ``WireDataRequested`` call (no arguments)."""
    return rpc.build(WIRE_DATA_REQUESTED)


class _Session(Protocol):
    def raise_event(
        self, code: int, data: bytes, *, broadcast: bool = False
    ) -> bool: ...

    def wait_for(self, done: Any, timeout: float = 20) -> bool: ...


def request(
    session: _Session, state: GameState, timeout: float = 3.0
) -> dict[int, WireData]:
    """Send 94, wait for the next ``ObjectData`` updates, return the wiring.

    The host replies with its next server tick (about 0.3 s each), so wait for
    a few updates. With no wired object there is nothing to wait for and the
    call returns after ``timeout`` with an empty result.
    """
    before = state.updates["ObjectData"]
    if not session.raise_event(WIRE_DATA_REQUESTED, request_bytes()):
        return wire_data(state)
    session.wait_for(lambda: state.updates["ObjectData"] >= before + 3, timeout)
    return wire_data(state)
