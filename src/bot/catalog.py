"""Every RPC the bot can send, with argument names and text parsing.

Built from :data:`src.protocol.rpc_table.RPCS`: an action per RPC id. An RPC
is *sendable* when every argument type has a known wire arity
(:data:`src.protocol.rpc.COMPOSITE_ARITY`); the others are listed with the
reason they are blocked. Argument names are ours, from the RPC and type names
(the binary has no parameter names); ``?`` marks a name that is a guess.

Kinds: ``player`` RPCs are the player's commands (the ones a joined client
would send), ``host`` ones are what the host broadcasts (state, objects,
money, sounds), ``handshake`` the join/save transfer (journal2 "The RPC
table").
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.protocol.enums import RESEARCH, ROOM_TYPES, STAFF, VEHICLES, name_of
from src.protocol.rpc import COMPONENTS, COMPOSITE_ARITY
from src.protocol.rpc_table import RPCS

HANDSHAKE = frozenset({0, 1, 2, 3, 4, 5, 6, 7, 8, 12, 143})
HOST = frozenset(
    {9, 10, 11, 13, 14, 15, 16, 17, 18, 19, 20, 22, 23, 88, 89, 90, 91, 95}
    | {113, 114, 115, 117, 118, 119, 123}
)

ARG_NAMES: dict[int, tuple[str, ...]] = {
    1: ("chunks?", "size?"),
    5: ("password?",),
    9: ("system", "snapshot"),
    11: ("index",),
    13: ("object", "type"),
    14: ("object",),
    15: ("room", "type?"),
    16: ("room",),
    21: ("objective", "flag"),
    25: ("sector", "gang?"),
    26: ("sector", "access_only"),
    27: ("sector", "job_count"),
    28: ("sector", "target"),
    29: ("sector",),
    30: ("sector?", "schedule?"),
    34: (
        "object_index",
        "on",
    ),  # ElectricalSwitch: the object index (not uId), journal2
    35: ("object", "action"),
    36: ("research",),
    37: ("research",),
    38: ("prisoner", "category"),
    39: ("prisoner", "punishment", "duration?"),
    40: ("prisoner",),
    41: ("prisoner", "flag"),
    42: ("prisoner", "flag"),
    43: ("vehicle",),
    44: ("squad",),
    45: ("staff",),
    46: ("prisoner",),
    47: ("grant",),
    48: ("grant",),
    51: ("shares",),
    52: ("shares",),
    53: ("hour?", "regime?", "category?"),
    54: ("gang",),
    55: ("crisis?", "button?", "on"),
    57: ("informant",),
    58: ("allowed", "category?"),
    59: ("category?", "on", "value?"),
    60: ("from?", "to?", "amount"),
    62: ("privilege?", "category?", "on"),
    63: ("meal?", "category?", "value?"),
    64: ("category?", "rate"),
    65: ("on",),
    66: ("modifier",),
    67: ("staff_type?", "max_break"),
    68: ("on",),
    69: ("criterion", "on"),
    70: ("criterion", "value"),
    71: ("criterion",),
    72: ("criterion", "on"),
    73: ("criterion", "value"),
    74: ("criterion",),
    75: ("on", "value?"),
    76: ("object",),
    77: ("category", "ratio"),
    78: ("type",),
    79: ("total",),
    80: ("time",),
    81: ("on",),
    82: ("program", "on"),
    83: ("program",),
    85: ("program", "day?", "hour?", "room"),
    86: ("program", "manual"),
    87: ("x?", "y?", "w?", "h?", "flag1?", "flag2?"),
    92: ("from", "to"),
    93: ("object",),
    96: ("speed",),
    97: ("tree", "age"),
    98: ("stop", "type?", "allowed"),
    99: ("stop", "type?", "allowed"),
    100: ("stop", "zone", "type?"),
    101: ("stop",),
    102: ("on", "a?", "b?", "c?", "d?", "ratio?"),
    103: ("room", "crop?"),
    104: ("room", "crop?"),
    105: ("room", "a?", "b?"),
    106: ("room", "a?", "b?", "percent"),
    107: ("room", "other"),
    108: ("object", "value"),
    109: ("room", "a?", "b?"),
    110: ("type", "x?", "y?", "a?", "b?"),
    111: ("plan", "a?", "b?"),
    116: ("category?", "wage"),
    120: ("plan?", "value?"),
    121: ("category?", "rate"),
    122: ("per_day",),
    124: ("on",),
    126: ("prisoner",),
    127: ("prisoner",),
    128: ("prisoner",),
    129: ("object", "a?", "b?"),
    130: ("object", "a", "b"),
    131: ("prisoner", "category"),
    132: ("cell", "other"),
    133: ("x?", "y?", "on"),
    135: ("prisoner",),
    136: ("staff", "rank"),
    117: (
        "adviser",
        "text_key",
    ),  # NewSpeechAdded: adviser index (ADVISERS), language key or free text
    137: ("on",),
    138: ("object",),
    139: ("on",),
    140: ("light",),
    142: ("prisoner",),
}


@dataclass(frozen=True)
class Arg:
    """One argument: our name and the game's C++ type."""

    name: str
    type: str

    @property
    def hint(self) -> str:
        """What to type for it."""
        return TYPE_HINTS.get(self.type, self.type)


TYPE_HINTS = {
    "int": "whole number",
    "signed char": "small whole number",
    "float": "number",
    "bool": "true/false",
    "string": "text",
    "MemoryBlock": "hex bytes",
    "ObjectId": "uId,index, #index (uId from state) or a name from `ctl name`",
    "SoundObjectId": "uId,index",
    "WorldPosition": "x,y (whole numbers)",
    "Vector2": "x,y",
    "Vector3": "x,y,z",
    "MisconductPolicy": "int,int,bool,bool,int",
    "CustomSectorNetworkData": "12 true/false values, comma-separated",
}


@dataclass(frozen=True)
class Action:
    """An RPC as an action: code, name, kind, arguments, and why it is blocked."""

    code: int
    name: str
    kind: str
    args: tuple[Arg, ...]

    @property
    def blocked(self) -> str:
        """Why it can't be built (an argument type of unknown arity), or ''."""
        unknown = sorted(
            {a.type for a in self.args if COMPOSITE_ARITY.get(a.type) is None}
        )
        return f"wire format unknown: {', '.join(unknown)}" if unknown else ""

    @property
    def signature(self) -> str:
        """``Name(arg: type, ...)``."""
        inner = ", ".join(f"{a.name}: {a.type}" for a in self.args)
        return f"{self.name}({inner})"


def _kind(code: int) -> str:
    if code in HANDSHAKE:
        return "handshake"
    return "host" if code in HOST else "player"


def _action(code: int) -> Action:
    name, types = RPCS[code]
    names = ARG_NAMES.get(code, ())
    args = tuple(
        Arg(names[i] if i < len(names) else f"arg{i}", t) for i, t in enumerate(types)
    )
    return Action(code, name, _kind(code), args)


ACTIONS: dict[int, Action] = {code: _action(code) for code in sorted(RPCS)}
"""Every RPC id -> its :class:`Action`."""


def find(key: str | int) -> Action:
    """The action for an RPC code or (case-insensitive) name; KeyError if none."""
    if isinstance(key, int) or str(key).isdigit():
        return ACTIONS[int(key)]
    for action in ACTIONS.values():
        if action.name.lower() == str(key).lower():
            return action
    raise KeyError(key)


class ArgError(ValueError):
    """A typed-in argument can't be read as its type."""


def parse_arg(arg: Arg, text: Any, resolve: Any = None) -> Any:
    """``text`` (str, or already a JSON value) as a value ``rpc.build`` takes.

    ``resolve(index) -> uId | None`` lets an ``ObjectId`` be given as
    ``#index`` (or a bare index) and looks the uId up in the game state.
    """
    t = arg.type
    try:
        if t == "bool":
            if isinstance(text, bool):
                return text
            word = str(text).strip().lower()
            if word in ("1", "true", "t", "yes", "y", "on"):
                return True
            if word in ("0", "false", "f", "no", "n", "off"):
                return False
            raise ArgError(f"{arg.name}: {text!r} is not true/false")
        if t in ("int", "signed char"):
            return int(text)
        if t == "float":
            return float(text)
        if t == "string":
            return str(text)
        if t == "MemoryBlock":
            return bytes.fromhex(str(text))
        if t == "ObjectId":
            return _object_id(arg, text, resolve)
        if parts := COMPONENTS.get(t):
            items = text if isinstance(text, (list, tuple)) else str(text).split(",")
            if len(items) != len(parts):
                raise ArgError(
                    f"{arg.name}: {t} takes {len(parts)} values ({arg.hint})"
                )
            return tuple(
                parse_arg(Arg(f"{arg.name}[{i}]", p), v)
                for i, (p, v) in enumerate(zip(parts, items))
            )
    except (TypeError, ValueError) as exc:
        if isinstance(exc, ArgError):
            raise
        raise ArgError(f"{arg.name}: {text!r} is not a {arg.hint}") from None
    raise ArgError(f"{arg.name}: cannot enter a {t} (wire format unknown)")


def _object_id(arg: Arg, text: Any, resolve: Any) -> tuple[int, int]:
    if isinstance(text, (list, tuple)) and len(text) == 2:
        return int(text[0]), int(text[1])
    raw = str(text).strip()
    if "," in raw:
        uid, index = raw.split(",", 1)
        return int(uid), int(index)
    index = int(raw.lstrip("#"))
    uid = resolve(index) if resolve else None
    if uid is None:
        raise ArgError(
            f"{arg.name}: object #{index} is not in the game state; give uId,index"
        )
    return int(uid), index


def parse_args(action: Action, values: list[Any], state: Any = None) -> list[Any]:
    """All of ``action``'s arguments from text/JSON values (count checked).

    With the :class:`~src.bot.state.GameState`, a value may also be one of the
    argument's :func:`choices` by label (``RiotPolice``, ``Warden #132``), and
    an ``ObjectId`` may be ``#index``.
    """
    if action.blocked:
        raise ArgError(f"{action.name}: {action.blocked}")
    if len(values) != len(action.args):
        raise ArgError(
            f"{action.signature} takes {len(action.args)} arguments, got {len(values)}"
        )
    resolve = state.uid_of if state is not None else None
    return [
        _by_name(a, v, state)
        if _is_named(a, v, state)
        else parse_arg(a, _by_label(a, v, state), resolve)
        for a, v in zip(action.args, values)
    ]


OBJECT_INDEX_ARGS = frozenset({"object_index"})
"""Int arguments that are an object index (``ElectricalSwitch``): a name works."""


def _is_named(arg: Arg, value: Any, state: Any) -> bool:
    """Whether ``value`` is a name the bot gave (``ctl name``) for an object arg."""
    if state is None or not isinstance(value, str):
        return False
    if arg.type != "ObjectId" and not (
        arg.type == "int" and arg.name in OBJECT_INDEX_ARGS
    ):
        return False
    return state.names.get(value.strip()) is not None


def _by_name(arg: Arg, value: str, state: Any) -> Any:
    uid, index = state.names.get(value.strip())
    return (uid, index) if arg.type == "ObjectId" else index


@dataclass(frozen=True)
class Choice:
    """One value an argument can take, and what the user sees."""

    value: Any
    label: str


SOURCES: dict[str, str] = {
    "vehicle": "vehicle",
    "squad": "squad",
    "staff": "staff",
    "prisoner": "prisoner",
    "informant": "prisoner",
    "research": "research",
    "grant": "grant",
    "objective": "objective",
    "room": "room",
    "cell": "room",
    "other": "room",
    "speed": "speed",
}
"""Argument name -> where its choices come from (see :func:`choices`)."""

SPEEDS = {0: "paused", 1: "1x", 2: "2x", 5: "5x", 10: "10x"}
"""``GameSpeedChange``: the multiplier (journal2, live test)."""


def source(arg: Arg) -> str:
    """The choices source of ``arg`` ('' = free input)."""
    if arg.type == "bool":
        return "bool"
    found = SOURCES.get(arg.name.rstrip("?"), "")
    if not found and arg.type == "ObjectId":
        return "object"
    return found


def choices(arg: Arg, state: Any = None) -> list[Choice]:
    """The values ``arg`` can take, named; [] when it is free input.

    Static tables (vehicles, research, speed) need no state; objects, squads,
    rooms, grants and objectives come from the live ``state``.
    """
    kind = source(arg)
    if kind == "bool":
        return [Choice(True, "true"), Choice(False, "false")]
    if kind == "speed":
        return [Choice(v, label) for v, label in SPEEDS.items()]
    if kind == "vehicle":
        return [Choice(v, n) for v, n in sorted(VEHICLES.items()) if v]
    if kind == "research":
        known = state.research() if state is not None else {}
        ids = sorted(set(RESEARCH) | set(known))
        return [Choice(i, _research_label(i, known.get(i))) for i in ids]
    if state is None:
        return []
    if kind == "squad":
        return [Choice(o.object_id, o.label) for o in state.squads()]
    if kind in ("staff", "prisoner", "object"):
        names = {"staff": STAFF, "prisoner": {"Prisoner"}}.get(kind)
        return [Choice(o.object_id, o.label) for o in state.objects(names)]
    if kind == "room":
        return [
            Choice(
                (r["uId"], i),
                f"{r.get('name') or name_of(ROOM_TYPES, r.get('type', -1))} #{i}",
            )
            for i, r in sorted(state.rooms.items())
            if r.get("uId") is not None
        ]
    if kind == "grant":
        names = set(state.grants()) | {
            n.removeprefix("Grant_") for n in state.objectives if n.startswith("Grant_")
        }
        return [Choice(n, n) for n in sorted(names)]
    if kind == "objective":
        return [Choice(n, n) for n in sorted(state.objectives)]
    return []


def _research_label(ident: int, progress: tuple[float, bool] | None) -> str:
    label = name_of(RESEARCH, ident)
    if progress is not None:
        done, desired = progress
        label += f" ({done:.0%}{', researching' if desired else ''})"
    return label


def _by_label(arg: Arg, value: Any, state: Any) -> Any:
    """``value`` swapped for a choice's value when it names one."""
    if not isinstance(value, str) or not source(arg) or source(arg) == "bool":
        return value
    wanted = value.strip().lower()
    for choice in choices(arg, state):
        label = choice.label.lower()
        if wanted in (label, label.split(" (")[0], label.split(" at ")[0]):
            return choice.value
    return value
