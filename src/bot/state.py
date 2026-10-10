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
from collections.abc import Collection
from dataclasses import dataclass, field
from typing import Any

from src.protocol import rpc
from src.protocol.enums import OBJECT_TYPES, ROOM_TYPES, name_of
from src.protocol.snapshot import Node, decode_args, decompress

log = logging.getLogger(__name__)

DIRECTORY_DATA = 9
OBJECT_ADDED = 13
OBJECT_REMOVED = 14
OBJECTIVE_REMOVED = 21
TRANSACTION_ADDED = 118
TRANSACTION_APPENDED = 119
CREATE_ROOM = 15
REMOVE_ROOM = 16
TRACKED = frozenset(
    {OBJECT_ADDED, OBJECT_REMOVED, OBJECTIVE_REMOVED, TRANSACTION_ADDED}
    | {TRANSACTION_APPENDED, CREATE_ROOM, REMOVE_ROOM}
)
"""Event codes (besides DirectoryData) that change the state."""
OBJECTIVE_SYSTEM = "Objective"
LIST_ITEM = "[i "
SAVE_SYSTEM = "Save"
"""Where the join handshake's full save tree is kept in ``systems``."""


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
        if any(child.name.startswith(LIST_ITEM) for child in node.children):
            # "[i N]" items are a list sent whole (CellData's changed cells), not
            # stable keys: replace the old items.
            for name in [n for n in self.children if n.startswith(LIST_ITEM)]:
                del self.children[name]
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
class GameObject:
    """An object the state knows: its ObjectId, type name and position."""

    uid: int
    index: int
    name: str
    pos: tuple[float, float] | None

    @property
    def object_id(self) -> tuple[int, int]:
        """``(uId, index)``, as an ``ObjectId`` argument."""
        return (self.uid, self.index)

    @property
    def label(self) -> str:
        """``Name #index``, plus the position when known."""
        where = f" at {self.pos[0]:g},{self.pos[1]:g}" if self.pos else ""
        return f"{self.name or '?'} #{self.index}{where}"


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
    log: deque[tuple[int, float, str]] = field(
        default_factory=lambda: deque(maxlen=2000)
    )
    """The same lines numbered: ``(seq, time, line)``, for polling."""
    seq: int = 0
    """Number of the last line added."""
    updates: Counter[str] = field(default_factory=Counter)
    """Snapshots merged per system."""
    errors: int = 0
    last_update: float = 0.0
    type_names: dict[int, str] = field(default_factory=lambda: dict(OBJECT_TYPES))
    """Object type id -> name: the known table, plus pairs learned live."""
    rooms: dict[int, dict[str, Any]] = field(default_factory=dict)
    """Rooms by index: ``uId``, ``type`` id, ``name`` (save ``Rooms`` / CreateRoom)."""
    save: StateNode | None = None
    """The host's full save game, once the join handshake delivered it."""
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
                        self.note(f"objective added: {fields['Name']}")
                return
            self.systems.setdefault(name, StateNode()).merge(tree)
            if name == "ObjectData":
                self._learn_type_names(tree)
            return
        if code not in TRACKED:
            return
        args = [value for _, value in rpc.parse(code, data).args]
        if code == OBJECT_ADDED:
            (uid, index), type_id = args
            node = StateNode({"uId": uid, "t": type_id})
            if type_id in self.type_names:
                node.fields["name"] = self.type_names[type_id]
            self._objects().children[str(index)] = node
            label = self.type_names.get(type_id, f"type {type_id}")
            self.note(f"object added: #{index} {label} (uId {uid})")
        elif code == CREATE_ROOM:
            (uid, index), type_id = args
            self.rooms[index] = {"uId": uid, "type": type_id}
            self.note(f"room created: #{index} {name_of(ROOM_TYPES, type_id)}")
        elif code == REMOVE_ROOM:
            uid, index = args[0]
            self.rooms.pop(index, None)
            self.note(f"room removed: #{index}")
        elif code == OBJECT_REMOVED:
            uid, index = args[0]
            self._objects().children.pop(str(index), None)
            self.note(f"object removed: #{index} (uId {uid})")
        elif code == OBJECTIVE_REMOVED:
            name = _text(args[0])
            self.objectives.pop(name, None)
            self.note(f"objective removed: {name}")
        else:  # TransactionAdded / TransactionAppended
            amount, key = int(args[0]), _text(args[1])
            self.transactions.append(Transaction(amount, key, time.time()))
            self.note(f"money {amount:+d} {key}")

    def _learn_type_names(self, tree: Node) -> None:
        """A full object entry (with ``t``) for an object named by the save."""
        objects = self._objects().children
        for child in tree.children:
            node = objects.get(child.name)
            if node and "t" in node.fields and node.fields.get("name"):
                self.type_names.setdefault(node.fields["t"], node.fields["name"])

    def load_save(self, tree: Node) -> None:
        """Keep the host's full save tree (the join handshake's result).

        Its sections are the save file's (``Objects``, ``Finance``,
        ``Grants``...), not the snapshots' layout, so it is kept whole as the
        ``Save`` system; its objects (``Id.i``/``Id.u``, ``Type`` name,
        ``Pos``) seed ``ObjectData`` by index.
        """
        with self.lock:
            self.save = StateNode()
            self.save.merge(tree)
            self.systems[SAVE_SYSTEM] = self.save
            objects = self.save.children.get("Objects")
            for item in objects.children.values() if objects else ():
                f = item.fields
                if "Id.i" not in f:
                    continue
                node = self._objects().children.setdefault(str(f["Id.i"]), StateNode())
                node.fields.update(
                    {"uId": f.get("Id.u"), "name": f.get("Type")}
                    | {k: f[k] for k in ("Pos.x", "Pos.y") if k in f}
                )
            rooms = self.save.children.get("Rooms")
            for item in rooms.children.values() if rooms else ():
                f = item.fields
                if "Id.i" in f:
                    self.rooms[f["Id.i"]] = {
                        "uId": f.get("Id.u"),
                        "name": f.get("RoomType"),
                    }
            self.note(f"save game loaded: {len(tree.children)} sections")

    def _save_value(self, path: str, key: str) -> Any:
        node = self.save.find(path) if self.save else None
        return node.fields.get(key) if node else None

    def _objects(self) -> StateNode:
        return self.systems.setdefault("ObjectData", StateNode())

    def note(self, text: str) -> None:
        """Add a line to :attr:`feed` and to the numbered :attr:`log`."""
        with self.lock:
            self.seq += 1
            self.feed.append(text)
            self.log.append((self.seq, time.time(), text))

    def since(self, seq: int, limit: int = 100) -> list[tuple[int, float, str]]:
        """Numbered lines after ``seq`` (oldest first, at most ``limit``)."""
        with self.lock:
            return [item for item in self.log if item[0] > seq][:limit]

    # reading
    def value(self, system: str, path: str, key: str) -> Any:
        """A field's latest value (``value("World", "WorldData", "TimeIndex")``)."""
        with self.lock:
            root = self.systems.get(system)
            node = root.find(path) if root else None
            return node.fields.get(key) if node else None

    @property
    def balance(self) -> int | None:
        """The bank balance (``Finance.v.6``, else the save's ``Finance.Balance``)."""
        live = self.value("Finance", "", "v.6")
        return live if live is not None else self._save_value("Finance", "Balance")

    @property
    def time_index(self) -> float | None:
        """Game time (``World.WorldData.TimeIndex``, else the save's)."""
        live = self.value("World", "WorldData", "TimeIndex")
        return live if live is not None else self._save_value("", "TimeIndex")

    def grants(self) -> dict[str, str]:
        """The save's grants: name -> ``Status`` (``InProgress``...)."""
        with self.lock:
            node = self.save.children.get("Grants") if self.save else None
            if node is None:
                return {}
            return {
                k: str(v.fields.get("Status", "")) for k, v in node.children.items()
            }

    def object_names(self) -> Counter[str]:
        """How many known objects there are of each type name (from the save)."""
        with self.lock:
            objects = self.systems.get("ObjectData")
            if objects is None:
                return Counter()
            return Counter(
                c.fields["name"]
                for c in objects.children.values()
                if c.fields.get("name")
            )

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

    def uid_of(self, index: int) -> int | None:
        """The uId of object ``index`` (for an ``ObjectId``), if known."""
        with self.lock:
            objects = self.systems.get("ObjectData")
            node = objects.children.get(str(index)) if objects else None
            return node.fields.get("uId") if node else None

    def objects(self, names: Collection[str] | None = None) -> list[GameObject]:
        """Known objects (optionally only those whose type name is in ``names``)."""
        with self.lock:
            objects = self.systems.get("ObjectData")
            out = []
            for index, node in objects.children.items() if objects else ():
                f = node.fields
                name = f.get("name") or self.type_names.get(f.get("t", -1), "")
                if "uId" not in f or (names is not None and name not in names):
                    continue
                pos = (f["Pos.x"], f["Pos.y"]) if "Pos.x" in f else None
                out.append(GameObject(f["uId"], int(index), name, pos))
            return sorted(out, key=lambda o: (o.name, o.index))

    def squads(self) -> list[GameObject]:
        """Called-in squads (``Squads.sqd``): their ObjectIds and ``Type``."""
        with self.lock:
            node = self.systems.get("Squads")
            sqd = node.children.get("sqd") if node else None
            items = [c.fields for c in sqd.children.values()] if sqd else []
            return [
                GameObject(f["Id.u"], f["Id.i"], str(f.get("Type", "")), None)
                for f in items
                if "Id.u" in f and "Id.i" in f
            ]

    def research(self) -> dict[int, tuple[float, bool]]:
        """Research by id: (progress 0..1, desired), from ``Research`` (``N-r``/``N-d``)."""
        with self.lock:
            node = self.systems.get("Research")
            out: dict[int, tuple[float, bool]] = {}
            for key, value in node.fields.items() if node else ():
                ident, _, kind = key.partition("-")
                if ident.isdigit() and kind in ("r", "d"):
                    progress, desired = out.get(int(ident), (0.0, False))
                    if kind == "r":
                        progress = float(value)
                    else:
                        desired = bool(value)
                    out[int(ident)] = (progress, desired)
            return out

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
                "object_names": dict(sorted(self.object_names().items())),
                "grants": self.grants(),
                "save_loaded": self.save is not None,
                "systems": dict(sorted(self.updates.items())),
                "recent": list(self.feed)[-10:],
                "errors": self.errors,
            }


def _text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return "" if value == 0 else str(value)
