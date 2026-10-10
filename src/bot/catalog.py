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

from src.protocol.rpc import COMPOSITE_ARITY
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
    34: ("switch?", "on"),
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
    "ObjectId": "uId,index (or #index: uId from state)",
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


def parse_args(action: Action, values: list[Any], resolve: Any = None) -> list[Any]:
    """All of ``action``'s arguments from text/JSON values (count checked)."""
    if action.blocked:
        raise ArgError(f"{action.name}: {action.blocked}")
    if len(values) != len(action.args):
        raise ArgError(
            f"{action.signature} takes {len(action.args)} arguments, got {len(values)}"
        )
    return [parse_arg(a, v, resolve) for a, v in zip(action.args, values)]
