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
from src.bot import network
from src.bot.names import ObjectNames
from src.bot.zones import Zones
from src.protocol.net_keys import label
from src.protocol.room_rules import ROOM_RULES
from src.protocol.enums import (
    STAFF_TYPES,
    ADVISERS,
    ELECTRICAL,
    OBJECT_TYPES,
    ROOM_ERRORS,
    ROOM_TYPES,
    name_of,
)
from src.protocol.game_text import TEXT
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
NEW_SPEECH = 117  # NewSpeechAdded(int, text key), e.g. help_warning_prisonerreleased
STAFF_ALERT = "StaffAlert"
TRACKED = frozenset(
    {OBJECT_ADDED, OBJECT_REMOVED, OBJECTIVE_REMOVED, TRANSACTION_ADDED}
    | {TRANSACTION_APPENDED, CREATE_ROOM, REMOVE_ROOM, NEW_SPEECH}
)
"""Event codes (besides DirectoryData) that change the state."""
OBJECTIVE_SYSTEM = "Objective"
WORLD_SYSTEM = "World"
STALL_SECONDS = 10.0
"""A ``World`` snapshot arrives about every 0.35 s, paused or not (journal2, speed
section). Silence for longer than this means the host has stopped running."""
LIST_ITEM = "[i "
GENERATORS = frozenset(
    {"PowerStation", "SolarPanels", "WindTurbine", "SolarWindHybrid"}
)
"""Object types that supply power (they have ``Capacity``, ``Switch``, ``Overloaded``)."""
OVERLOADED = 1
"""``Overloaded`` value of a generator whose network demands more than it can supply
(seen with Capacity 50 and 65 demand); 3 is also seen, see journal2."""
TIRED = 25.0
"""``EnergyLevel`` below this counts as tired (0 is exhausted; a rested person has 50-100)."""
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

    def to_dict(self, depth: int = -1, system: str | None = None) -> dict[str, Any]:
        """JSON-able ``{field: value, ..., "/child": {...}}``; bytes as hex.

        ``depth`` limits how many child levels are included (-1: all); cut
        children show as their count. With ``system``, short network keys are
        shown as ``Long name (key)`` (:mod:`src.protocol.net_keys`).
        """
        out: dict[str, Any] = {
            _labelled(system, k): _jsonable(v) for k, v in self.fields.items()
        }
        if depth == 0 and self.children:
            out["/children"] = len(self.children)
            return out
        for name, child in self.children.items():
            out["/" + _labelled(system, name)] = child.to_dict(depth - 1, system)
        return out


def _labelled(system: str | None, key: str) -> str:
    """``key``, as ``Long name (key)`` when the system's short keys are known."""
    return label(system, key)


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
    world_seen: float = 0.0
    """When the last ``World`` snapshot was merged (0 before the first one)."""
    type_names: dict[int, str] = field(default_factory=lambda: dict(OBJECT_TYPES))
    """Object type id -> name: the known table, plus pairs learned live."""
    cells: dict[tuple[int, int], dict[str, Any]] = field(default_factory=dict)
    """Map cells ``(x, y)`` -> ``Mat``, ``Ind`` (indoors), ``Room.i`` (save
    ``Cells``, then live ``CellData``)."""
    rooms: dict[int, dict[str, Any]] = field(default_factory=dict)
    """Rooms by index: ``uId``, ``type`` id, ``name`` (save ``Rooms`` / CreateRoom)."""
    alerts: deque[str] = field(default_factory=lambda: deque(maxlen=50))
    """Messages for the player (staff alerts, advisor speech), newest last."""
    staff_alerts: list[str] = field(default_factory=list)
    """The staff alerts currently shown (``StaffAlert``)."""
    save: StateNode | None = None
    """The host's full save game, once the join handshake delivered it."""
    names: ObjectNames = field(default_factory=lambda: ObjectNames(None))
    """Names the bot gave to objects/rooms (``ctl name``); not saved unless the
    session passes a file."""
    zones: Zones = field(default_factory=lambda: Zones(None))
    """Named map rectangles (``ctl zone``); not saved unless the session passes a file."""
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
            if name == STAFF_ALERT:
                self._staff_alerts(tree)
            elif name == "CellData":
                for group in tree.children:
                    for item in group.children:
                        f = dict(item.fields)
                        if "x" in f and "y" in f:
                            self.cells.setdefault((f["x"], f["y"]), {}).update(f)
            self.systems.setdefault(name, StateNode()).merge(tree)
            if name == WORLD_SYSTEM:
                self.world_seen = time.time()
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
            self.note(
                f"object added: {self.named(index, uid)}#{index} {label} (uId {uid})"
            )
        elif code == NEW_SPEECH:
            text = TEXT.get(_text(args[1]), _text(args[1]))
            who = ADVISERS.get(args[0])
            text = f"{who}: {text}" if who else text
            self.alerts.append(text)
            self.note(f"alert: {text}")
        elif code == CREATE_ROOM:
            (uid, index), type_id = args
            self.rooms[index] = {"uId": uid, "type": type_id}
            self.note(f"room created: #{index} {name_of(ROOM_TYPES, type_id)}")
        elif code == REMOVE_ROOM:
            uid, index = args[0]
            self.rooms.pop(index, None)
            self.note(f"room removed: {self.named(index, uid)}#{index}")
        elif code == OBJECT_REMOVED:
            uid, index = args[0]
            self._objects().children.pop(str(index), None)
            self.note(f"object removed: {self.named(index, uid)}#{index} (uId {uid})")
        elif code == OBJECTIVE_REMOVED:
            name = _text(args[0])
            self.objectives.pop(name, None)
            self.note(f"objective removed: {name}")
        else:  # TransactionAdded / TransactionAppended
            amount, key = int(args[0]), _text(args[1])
            self.transactions.append(Transaction(amount, key, time.time()))
            self.note(f"money {amount:+d} {key}")

    def _staff_alerts(self, tree: Node) -> None:
        """Note each new staff alert (``sa [i N] {tts=<text key>, aa=<staff type>}``)."""
        current = []
        for group in tree.children:
            for item in group.children:
                f = dict(item.fields)
                if f.get("tts"):
                    who = self.type_names.get(f.get("aa", -1), "staff")
                    current.append(f"{who}: {TEXT.get(f['tts'], f['tts'])}")
        for line in current:
            if line not in self.staff_alerts:
                self.alerts.append(line)
                self.note(f"alert: {line}")
        self.staff_alerts = current

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
            cells = self.save.children.get("Cells")
            for name, item in cells.children.items() if cells else ():
                x, _, y = name.partition(" ")
                if x.isdigit() and y.isdigit():
                    self.cells[(int(x), int(y))] = dict(item.fields)
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

    def host_stalled(
        self, limit: float = STALL_SECONDS, now: float | None = None
    ) -> bool:
        """True when the host has gone silent: no ``World`` snapshot for ``limit`` s.

        False before the first snapshot, so a bot that is still joining is not stalled.
        """
        with self.lock:
            seen = self.world_seen
        if not seen:
            return False
        return (time.time() if now is None else now) - seen > limit

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

    def room_uid(self, index: int) -> int | None:
        """The uId of room ``index`` (from the save, else ``CreateRoom``), if known."""
        with self.lock:
            rooms = self.save.children.get("Rooms") if self.save else None
            for item in rooms.children.values() if rooms else ():
                if item.fields.get("Id.i") == index:
                    return item.fields.get("Id.u")
            return (self.rooms.get(index) or {}).get("uId")

    def staff_needs(self) -> dict[str, Any]:
        """Energy / rest status of every staff member, per type and one by one.

        Live ``ObjectData`` (``el`` EnergyLevel, ``rs`` RestState, ``ca`` current Action).
        ``rs`` 1 = rest required (the save's ``RestStateRequired``): exhausted. Energy 0
        is also exhausted; below ``TIRED`` is tired. Workmen reading 0 need a Staffroom
        (``ctl rules Staffroom``).
        """
        with self.lock:
            node = self.systems.get("ObjectData")
            people = []
            for index, obj in node.children.items() if node else ():
                f = obj.fields
                kind = f.get("name") or self.type_names.get(f.get("t", -1), "")
                if kind not in STAFF_TYPES:
                    continue
                energy, rest = f.get("el"), f.get("rs")
                if rest == 1 or (energy is not None and energy <= 0):
                    status = "exhausted"
                elif energy is not None and energy < TIRED:
                    status = "tired"
                else:
                    status = "ok"
                people.append(
                    {
                        "index": int(index),
                        "uId": f.get("uId"),
                        "type": kind,
                        "name": self.names.name_of(int(index), f.get("uId")),
                        "energy": None if energy is None else round(float(energy), 1),
                        "rest_state": rest,
                        "action": f.get("ca"),
                        "status": status,
                    }
                )
            by_type: dict[str, dict[str, Any]] = {}
            for p in people:
                t = by_type.setdefault(
                    p["type"], {"count": 0, "exhausted": 0, "tired": 0, "ok": 0}
                )
                t["count"] += 1
                t[p["status"]] += 1
            return {
                "summary": dict(sorted(by_type.items())),
                "exhausted": sum(t["exhausted"] for t in by_type.values()),
                "staff": sorted(people, key=lambda p: (p["type"], p["index"])),
            }

    def named(self, index: int, uid: int | None = None) -> str:
        """``"Name "`` for a named object (note the space), else ``""``."""
        name = self.names.name_of(index, uid)
        return f"{name} " if name else ""

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

    def area(self, x: int, y: int, width: int, height: int) -> dict[str, Any]:
        """What the cells in an area are made of: counts, a grid, and rooms.

        ``rows`` has one string per row, a letter per cell (see ``key``):
        ``W`` wall, ``F`` floor, ``B`` building frame (walls still to come),
        ``.`` nothing built; lower case = indoors is not set.
        """
        with self.lock:
            counts: Counter[str] = Counter()
            rooms: set[int] = set()
            rows = []
            for cy in range(y, y + height):
                row = ""
                for cx in range(x, x + width):
                    f = self.cells.get((cx, cy), {})
                    mat = str(f.get("Mat") or "")
                    counts[mat or "nothing"] += 1
                    if f.get("Room.i", -1) not in (-1, None):
                        rooms.add(f["Room.i"])
                    row += _cell_letter(mat)
                rows.append(row)
            return {
                "materials": dict(counts),
                "rows": rows,
                "rooms": sorted(rooms),
                "key": "W wall, F floor, B frame (walls not built yet), "
                "D door/other, . nothing",
            }

    def networks(self, utility: str = "electricity") -> dict[str, Any]:
        """Networks of one utility (:data:`network.UTILITIES`) in the last save."""
        spec = network.UTILITIES.get(utility)
        if spec is None:
            return {"error": f"utilities: {', '.join(network.UTILITIES)}"}
        with self.lock:
            if self.save is None:
                return {"error": "the save is not loaded yet"}
            node = self.save.children.get(spec.node)
            cells = set()
            for key in node.children if node else ():
                parts = key.split()
                if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
                    cells.add((int(parts[0]), int(parts[1])))
            objects = self.save.children.get("Objects")
            fields = [i.fields for i in objects.children.values()] if objects else []
            return network.analyze(cells, fields, spec)

    def room_list(self) -> list[dict[str, Any]]:
        """Rooms from the last save: index, type, and the assigned prisoner (cells)."""
        with self.lock:
            rooms = self.save.children.get("Rooms") if self.save else None
            out = []
            for item in rooms.children.values() if rooms else ():
                f = item.fields
                occupant = f.get("Entity.i", -1)
                out.append(
                    {
                        "index": f.get("Id.i"),
                        "type": f.get("RoomType"),
                        "occupant": None if occupant in (-1, None) else occupant,
                    }
                )
            return out

    def problems(self) -> list[str]:
        """What the game would flag, from the last save: room errors, no power.

        Only as fresh as the save (``refresh`` to update).
        """
        with self.lock:
            if self.save is None:
                return []
            out = []
            rooms = self.save.children.get("Rooms")
            for item in rooms.children.values() if rooms else ():
                f = item.fields
                where = (
                    f"{self.named(f.get('Id.i'), f.get('Id.u'))}"
                    f"{f.get('RoomType', 'room')} #{f.get('Id.i')}"
                )
                if f.get("RoomError"):
                    key = ROOM_ERRORS.get(f["RoomError"], "")
                    text = TEXT.get(key, key) or f"error {f['RoomError']}"
                    out.append(f"{where}: {text}")
                if f.get("RequirementsFailed"):
                    out.append(f"{where}: requirements not met")
            out.extend(self._rule_problems())
            objects = self.save.children.get("Objects")
            for item in objects.children.values() if objects else ():
                f = item.fields
                if f.get("Type") in GENERATORS and f.get("Overloaded"):
                    who = self.named(f.get("Id.i"), f.get("Id.u"))
                    if f["Overloaded"] == OVERLOADED:
                        why = (
                            f"overloaded (Capacity {f.get('Capacity')}), all power "
                            "is cut: remove electrical items, add Capacitors, or add "
                            "a second PowerStation on its own cables"
                        )
                    else:
                        why = (
                            f"Overloaded={f['Overloaded']} (seen when a PowerStation "
                            "and green sources share one network, or a source is "
                            "switched off): keep stations and green sources on "
                            "separate cables (crossing lines short-circuit)"
                        )
                    out.append(f"{who}{f['Type']} #{f.get('Id.i')}: {why}")
                if f.get("Type") in ELECTRICAL and not f.get("Powered"):
                    pos = f"{f.get('Pos.x', '?')},{f.get('Pos.y', '?')}"
                    hint = (
                        ""
                        if f["Type"] == "Light"
                        else " (a cable must touch it; only lights reach over a gap)"
                    )
                    who = self.named(f.get("Id.i"), f.get("Id.u"))
                    out.append(
                        f"{who}{f['Type']} #{f.get('Id.i')} at {pos}: no power{hint}"
                    )
            return out

    def _rule_problems(self) -> list[str]:
        """Rooms short of the game's own requirements (``room_rules``): size, objects.

        Sizes use the bounding box of the room's cells; objects are matched by
        the cell under their position. Walls/roof/fence (Enclosed, Indoor,
        Secure) are not checked here; ``ctl area`` shows them.
        """
        rooms = self.save.children.get("Rooms") if self.save else None
        objects = self.save.children.get("Objects") if self.save else None
        if not rooms:
            return []
        cells: dict[int, list[tuple[int, int]]] = {}
        for xy, info in self.cells.items():
            if info.get("Room.i") not in (None, -1):
                cells.setdefault(info["Room.i"], []).append(xy)
        found: dict[int, set[str]] = {}
        for item in objects.children.values() if objects else ():
            f = item.fields
            if "Pos.x" in f and f.get("Type"):
                xy = (int(f["Pos.x"]), int(f.get("Pos.y", 0)))
                for index, room_cells in cells.items():
                    if xy in room_cells:
                        found.setdefault(index, set()).add(f["Type"])
        out = []
        for item in rooms.children.values():
            f = item.fields
            rule = ROOM_RULES.get(f.get("RoomType", ""))
            area = cells.get(f.get("Id.i"))
            if rule is None or not area:
                continue
            size, _flags, needed = rule
            missing = []
            xs, ys = [x for x, _ in area], [y for _, y in area]
            w, h = max(xs) - min(xs) + 1, max(ys) - min(ys) + 1
            if size and not (
                (w >= size[0] and h >= size[1]) or (w >= size[1] and h >= size[0])
            ):
                missing.append(f"size {w}x{h}, needs {size[0]}x{size[1]}")
            have = found.get(f.get("Id.i"), set())
            for name, alts in needed:
                if not have & {name, *alts}:
                    missing.append(name)
            if missing:
                out.append(
                    f"{self.named(f.get('Id.i'), f.get('Id.u'))}{f['RoomType']} "
                    f"#{f.get('Id.i')}: lacks " + ", ".join(missing)
                )
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
                "named": {
                    n: {"uId": u, "index": i} for n, (u, i) in self.names.all().items()
                },
                "zones": self.zones.all(),
                "host_stalled": self.host_stalled(),
                "save_loaded": self.save is not None,
                "alerts": list(self.alerts)[-10:],
                "problems": self.problems(),
                "rooms": self.room_list(),
                "systems": dict(sorted(self.updates.items())),
                "recent": list(self.feed)[-10:],
                "errors": self.errors,
            }


def _cell_letter(mat: str) -> str:
    if not mat:
        return "."
    if mat.endswith("Wall") or mat == "Fence":
        return "W"
    if mat.endswith("Floor") or mat in ("Concrete", "Tiles"):
        return "F"
    if mat == "BuildingFrame":
        return "B"
    return "D"


def _text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return "" if value == 0 else str(value)
