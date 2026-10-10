"""Proxy mode: show the attached client a bank balance of our choosing.

The balance is ``Finance.v.6`` and ``World.WorldData.Balance`` in the host's
``DirectoryData`` snapshots (journal2: they are equal, and a ``TransactionAdded``
moves them by its amount). An override is an *offset*: every ``Finance`` / ``World``
snapshot on its way to the attached client gets the offset added to its balance,
so the client sees our number and still tracks the real spending on top of it.
The host never hears of it; its own balance is unchanged.
"""

from __future__ import annotations

import zlib
from typing import Any

from src.protocol.rpc import build
from src.protocol.snapshot import (
    Node,
    compress,
    decode_args,
    decompress,
    encode_tree,
)

DIRECTORY_DATA = 9
FINANCE_FIELD = "v.6"
BALANCE_FIELD = "Balance"


def _slot(name: str, tree: Node) -> tuple[Node, int] | None:
    """The node and field index holding the balance in a ``Finance``/``World`` tree."""
    if name == "Finance":
        node = tree
        key = FINANCE_FIELD
    elif name == "World":
        node = next((c for c in tree.children if c.name == "WorldData"), None)
        key = BALANCE_FIELD
        if node is None:
            return None
    else:
        return None
    for i, (field, value) in enumerate(node.fields):
        if field == key and isinstance(value, int) and not isinstance(value, bool):
            return node, i
    return None


def snapshot_data(name: str, balance: int) -> bytes:
    """``Data`` of a delta snapshot that sets just the balance of ``name``."""
    if name == "Finance":
        tree = Node("Finance", [(FINANCE_FIELD, balance)])
    else:
        tree = Node("World", [], [Node("WorldData", [(BALANCE_FIELD, balance)])])
    return build(DIRECTORY_DATA, name, compress(encode_tree(tree)))


class BalanceOverride:
    """Tracks each client's real balance and rewrites snapshots for one of them."""

    def __init__(self) -> None:
        self.real: dict[Any, int] = {}
        """Session -> the balance the host last reported to that client."""
        self.session: Any = None
        """The client being overridden, or None."""
        self.offset = 0
        self.unsafe = 0
        """Snapshots left alone because re-encoding them would not be exact."""

    @property
    def active(self) -> bool:
        return self.session is not None

    def pin(self, session: Any, target: int) -> int:
        """Show ``session``'s client ``target``; returns the offset from the real balance."""
        real = self.real.get(session)
        if real is None:
            raise ValueError(
                "no balance seen for this game yet: wait for a Finance update"
            )
        self.session, self.offset = session, target - real
        return self.offset

    def release(self) -> None:
        self.session, self.offset = None, 0

    def shown(self, session: Any) -> int | None:
        """What ``session``'s client sees now."""
        real = self.real.get(session)
        if real is None:
            return None
        return real + self.offset if session is self.session else real

    def rewrite(self, session: Any, data: bytes) -> bytes | None:
        """Learn the real balance from a snapshot; new ``Data`` if it must change."""
        try:
            args = decode_args(data)
            name = args[0].decode("utf-8", "replace")
            snap = decompress(args[1])
        except (ValueError, IndexError, AttributeError, TypeError, zlib.error):
            return None
        if snap.tree is None:
            return None
        slot = _slot(name, snap.tree)
        if slot is None:
            return None
        node, i = slot
        key, real = node.fields[i]
        self.real[session] = real
        if session is not self.session or not self.offset:
            return None
        if encode_tree(snap.tree) != snap.raw:  # would corrupt the rest of the tree
            self.unsafe += 1
            return None
        node.fields[i] = (key, real + self.offset)
        return build(DIRECTORY_DATA, name, compress(encode_tree(snap.tree)))

    def status(self, session: Any) -> str:
        real, shown = self.real.get(session), self.shown(session)
        if real is None:
            return "balance not seen yet"
        if not self.active or session is not self.session:
            return f"balance {real} (no override)"
        return f"balance shown {shown}, real {real} (offset {self.offset:+d})"
