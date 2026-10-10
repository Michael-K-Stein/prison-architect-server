"""What the bot knows about the game: the host's ``DirectoryData`` trees, merged.

The host streams each system (``World``, ``Finance``, ``ObjectData``...) as a
save-file tree. Most snapshots are deltas: only the fields that changed, under
the nodes that hold them (journal2, run3 "Speed is `gt`"). :class:`GameState`
merges them into one tree per system, by node name, so it holds the latest
value of every field seen so far. A field is never removed; whole objects are
removed by ``ObjectRemoved``.

Known meanings (journal2): ``World.WorldData.TimeIndex`` (game time),
``World.ClientData.gt`` (speed: 0 paused, else 1/2/5/10), ``Finance.v.6``
(bank balance), ``ObjectData.<index>.t`` (object type), ``Objective`` (one
objective per snapshot, keyed by ``Name``).
"""

from __future__ import annotations

import logging
import threading
import time
import zlib
from collections import Counter, deque
from dataclasses import dataclass, field
from typing import Any

from src.protocol import rpc
from src.protocol.snapshot import Node, decode_args, decompress

log = logging.getLogger(__name__)

DIRECTORY_DATA = 9
OBJECT_ADDED = 13
OBJECT_REMOVED = 14
OBJECTIVE_REMOVED = 21
TRANSACTION_ADDED = 118
OBJECTIVE_SYSTEM = "Objective"


@dataclass
class StateNode:
    """A merged tree node: latest field values and children by name.

    A field repeated inside one snapshot node (``Traits`` in a ``Bio``) is kept
    as a list of its values.
    """

    fields: dict[str, Any] = field(default_factory=dict)
    children: dict[str, StateNode] = field(default_factory=dict)

    def merge(self, node: Node) -> None:
        """Overwrite with ``node``'s fields and merge its children by name."""
        counts = Counter(key for key, _ in node.fields)
        repeated: dict[str, list[Any]] = {}
        for key, value in node.fields:
            if counts[key] > 1:
                repeated.setdefault(key, []).append(value)
            else:
                self.fields[key] = value
        self.fields.update(repeated)
        for child in node.children:
            self.children.setdefault(child.name, StateNode()).merge(child)

    def find(self, path: str) -> StateNode | None:
        """The node at a ``/``-separated path of child names, or None."""
        node: StateNode | None = self
        for part in filter(None, path.split("/")):
            node = node.children.get(part) if node else None
        return node

    def to_dict(self, depth: int = -1) -> dict[str, Any]:
        """JSON-able ``{field: value, ..., "/child": {...}}``; bytes as hex.

        ``depth`` limits how many child levels are included (-1: all); cut
        children show as their count.
        """
        out: dict[str, Any] = {k: _jsonable(v) for k, v in self.fields.items()}
        if depth == 0 and self.children:
            out["/children"] = len(self.children)
            return out
        for name, child in self.children.items():
            out["/" + name] = child.to_dict(depth - 1)
        return out


def _jsonable(value: Any) -> Any:
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return value.hex()
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    return value


@dataclass(frozen=True)
class Transaction:
    """One ``TransactionAdded``: signed amount and ledger key."""

    amount: int
    key: str
    at: float


@dataclass
class GameState:
    """Everything the bot has learned from the host's events (thread-safe)."""

    systems: dict[str, StateNode] = field(default_factory=dict)
    objectives: dict[str, dict[str, Any]] = field(default_factory=dict)
    """Current objectives: ``Name`` -> the objective's fields."""
    transactions: deque[Transaction] = field(default_factory=lambda: deque(maxlen=200))
    feed: deque[str] = field(default_factory=lambda: deque(maxlen=200))
    """Readable notable happenings (objects, objectives, money), newest last."""
    updates: Counter[str] = field(default_factory=Counter)
    """Snapshots merged per system."""
    errors: int = 0
    last_update: float = 0.0
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    # feeding
    def apply(self, code: int, data: Any) -> None:
        """Merge one game event (``RaiseEvent`` code and ``Data``)."""
        if not isinstance(data, bytes):
            return
        try:
            with self.lock:
                self._apply(code, data)
                self.last_update = time.time()
        except (ValueError, IndexError, AttributeError, zlib.error) as exc:
            self.errors += 1
            log.debug("state: could not apply event %d: %s", code, exc)

    def _apply(self, code: int, data: bytes) -> None:
        if code == DIRECTORY_DATA:
            args = decode_args(data)
            name = args[0].decode("utf-8", "replace")
            tree = decompress(args[1]).tree
            if tree is None:
                return
            self.updates[name] += 1
            if name == OBJECTIVE_SYSTEM:
                fields = dict(tree.fields)
                if "Name" in fields:
                    known = fields["Name"] in self.objectives
                    self.objectives.setdefault(fields["Name"], {}).update(fields)
                    if not known:
                        self._note(f"objective added: {fields['Name']}")
                return
            self.systems.setdefault(name, StateNode()).merge(tree)
            return
        if code not in (
            OBJECT_ADDED,
            OBJECT_REMOVED,
            OBJECTIVE_REMOVED,
            TRANSACTION_ADDED,
        ):
            return
        args = [value for _, value in rpc.parse(code, data).args]
        if code == OBJECT_ADDED:
            (uid, index), type_id = args
            node = self._objects().children.setdefault(str(index), StateNode())
            node.fields.update({"uId": uid, "t": type_id})
            self._note(f"object added: #{index} type {type_id} (uId {uid})")
        elif code == OBJECT_REMOVED:
            uid, index = args[0]
            self._objects().children.pop(str(index), None)
            self._note(f"object removed: #{index} (uId {uid})")
        elif code == OBJECTIVE_REMOVED:
            name = _text(args[0])
            self.objectives.pop(name, None)
            self._note(f"objective removed: {name}")
        else:
            amount, key = int(args[0]), _text(args[1])
            self.transactions.append(Transaction(amount, key, time.time()))
            self._note(f"money {amount:+d} {key}")

    def _objects(self) -> StateNode:
        return self.systems.setdefault("ObjectData", StateNode())

    def _note(self, text: str) -> None:
        self.feed.append(text)

    # reading
    def value(self, system: str, path: str, key: str) -> Any:
        """A field's latest value (``value("World", "WorldData", "TimeIndex")``)."""
        with self.lock:
            root = self.systems.get(system)
            node = root.find(path) if root else None
            return node.fields.get(key) if node else None

    @property
    def balance(self) -> int | None:
        """The bank balance (``Finance.v.6``)."""
        return self.value("Finance", "", "v.6")

    @property
    def time_index(self) -> float | None:
        """Game time (``World.WorldData.TimeIndex``)."""
        return self.value("World", "WorldData", "TimeIndex")

    @property
    def speed(self) -> int | None:
        """Game speed (``World.ClientData.gt``): 0 paused, else the multiplier.

        None until the host has sent a change (it starts at 1x, *guess*).
        """
        return self.value("World", "ClientData", "gt")

    def object_types(self) -> Counter[int]:
        """How many known objects there are of each type id."""
        with self.lock:
            objects = self.systems.get("ObjectData")
            if objects is None:
                return Counter()
            return Counter(
                c.fields["t"] for c in objects.children.values() if "t" in c.fields
            )

    def objects_of_type(self, type_id: int) -> list[tuple[int, int]]:
        """``(uId, index)`` ObjectIds of the known objects of ``type_id``."""
        with self.lock:
            objects = self.systems.get("ObjectData")
            if objects is None:
                return []
            return [
                (c.fields["uId"], int(i))
                for i, c in objects.children.items()
                if c.fields.get("t") == type_id and "uId" in c.fields
            ]

    def summary(self) -> dict[str, Any]:
        """A JSON-able overview: money, time, speed, objectives, counts."""
        with self.lock:
            return {
                "balance": self.balance,
                "time_index": self.time_index,
                "speed": self.speed,
                "objectives": sorted(self.objectives),
                "objects": len(self.systems.get("ObjectData", StateNode()).children),
                "object_types": dict(sorted(self.object_types().items())),
                "systems": dict(sorted(self.updates.items())),
                "recent": list(self.feed)[-10:],
                "errors": self.errors,
            }


def _text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return "" if value == 0 else str(value)
