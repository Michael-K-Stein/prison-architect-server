"""The bot's full-screen HUD: live status, a filterable action list, input and log."""

from __future__ import annotations

import asyncio
import re
import time
from collections import Counter, deque
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from prompt_toolkit import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import StyleAndTextTuples
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
from prompt_toolkit.data_structures import Point
from prompt_toolkit.layout import (
    ConditionalContainer,
    Float,
    FloatContainer,
    HSplit,
    Layout,
    VSplit,
    Window,
)
from prompt_toolkit.mouse_events import MouseEvent, MouseEventType
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.processors import AfterInput, ConditionalProcessor
from prompt_toolkit.widgets import Frame

from src.bot.actions import (
    ACCEPT_GRANT,
    CANCEL_GRANT,
    CEO_LETTER_OBJECTIVE,
    OBJECTIVE_REMOVED,
)
from src.bot.catalog import (
    ACTIONS,
    SPEEDS,
    Action,
    Arg,
    ArgError,
    Choice,
    choices,
    parse_args,
    source,
)
from src.bot import build, inmate_actions, inmate_fields
from src.bot.broadcast import SPEAKERS
from src.bot.session import Options, Session
from src.bot.speed import GAME_SPEED_CHANGE
from src.bot.state import NEW_SPEECH
from src.cli.frame import DIM, RULE
from src.protocol import rpc
from src.protocol.enums import STAFF, VEHICLES
from src.protocol.grants import GRANTS

REFRESH = 0.25  # seconds between HUD redraws
LOG_LINES = 500
LOG_VIEW = 8  # message lines shown above the input
HELP = {
    "list": "type: search all  up/down/PgUp/PgDn: move  Enter/Right: open/run  "
    "Left/Esc: back  F2: state  Ctrl-Q: quit",
    "args": "type: filter/raw value  up/down: pick  Tab/Enter: next field  "
    "Shift-Tab: previous  Esc: cancel",
}


@dataclass(frozen=True)
class Item:
    """One row of the action list: a quick action, an RPC, or a view."""

    label: str
    group: str
    action: Action | None = None
    values: tuple[Any, ...] | None = None
    """Fixed argument values (quick actions); None = prompt for them."""
    special: str = ""
    """``group`` / ``info`` (a state field) / ``quit`` for the non-RPC rows."""
    children: tuple[Item, ...] = ()
    """The rows inside a ``group``."""
    job: Callable[[Sequence[Any]], list[dict[str, Any]]] | None = None
    """A build command: the typed values -> build job specs (``action`` only
    describes its arguments)."""

    locked: str = ""
    """Why the game won't allow it yet (a locked grant); such rows are skipped."""
    lazy: Callable[[], tuple[Item, ...]] | None = None
    """Builds the rows of a ``group`` when it is opened (the live state tree)."""
    note: str = ""
    """Dim text after the label (a count)."""
    key: str = ""
    """For a field row: its readable name, drawn bold (``label`` is ``key: value``)."""
    shown: str = ""
    """For a field row: its readable value, drawn in ``shown_style``."""
    shown_style: str = ""

    @property
    def rows(self) -> tuple[Item, ...]:
        """The rows inside a ``group``."""
        return self.lazy() if self.lazy is not None else self.children

    @property
    def blocked(self) -> str:
        """Why it can't be sent, or ''."""
        if self.locked:
            return self.locked
        if self.job is not None or self.action is None:
            return ""
        return self.action.blocked


class _FloatBelow(Float):
    """A float whose top row is computed on every redraw (``Float.top`` is an int)."""

    def __init__(self, content: Any, row: Callable[[], int], **kwargs: Any) -> None:
        self._row = row
        super().__init__(content, **kwargs)

    @property
    def top(self) -> int:
        """The row under the status area."""
        return self._row()

    @top.setter
    def top(self, _: Any) -> None:
        pass  # Float.__init__ assigns it; the row callable decides


def _rule() -> Window:
    """A one-line separator across the screen."""
    return Window(height=1, char=RULE, style=DIM)


def _text(value: Any) -> str:
    return value.decode("utf-8", "replace") if isinstance(value, bytes) else str(value)


def grant_items(objectives: Iterable[Any], state: Any = None) -> list[Item]:
    """One folder per grant (every known one): Accept, and Cancel while it is in progress."""
    names = set(GRANTS)
    streamed = {_text(o) for o in objectives if _text(o).startswith("Grant_")}
    names |= streamed
    status: dict[str, str] = state.grants() if state is not None else {}
    names |= set(status)
    names = {n for n in names if n.count("_") == 1}  # not Grant_<name>_<task>
    accept, cancel = ACTIONS[ACCEPT_GRANT], ACTIONS[CANCEL_GRANT]
    out: list[Item] = []
    for name in sorted(names, key=lambda n: str(GRANTS.get(n, {}).get("title") or n)):
        title = str(GRANTS.get(name, {}).get("title") or name)
        rows = [Item(f"Accept {title}", "grant", accept, (name,))]
        # The save's Grants status lags behind: right after Accept only the streamed
        # Grant_x objective exists (journal2 "Accepting the first grant").
        active = status.get(name) == "InProgress" or name in streamed
        if active:
            rows.append(Item(f"Cancel {title}", "grant", cancel, (name,)))
        locked = "" if name in status or active else grant_lock(name, status, state)
        out.append(
            Item(title, "grant", special="group", children=tuple(rows), locked=locked)
        )
    return out


def grant_lock(name: str, status: dict[str, str], state: Any) -> str:
    """What a grant still needs (``locked: ...``), or '' when nothing known blocks it.

    Checks the ``Completed`` prerequisites and the ``Prisoners AtLeast`` count; the
    other kinds (``Unlocked``) can't be read from the state, so they never lock."""
    needs: list[str] = []
    for kind, what, amount in GRANTS.get(name, {}).get("requires", []):
        if kind == "Completed" and status.get(what, "").lower() != "completed":
            needs.append(str(GRANTS.get(what, {}).get("title") or what))
        elif kind == "Prisoners" and what == "AtLeast" and state is not None:
            if len(state.objects({"Prisoner"})) < amount:
                needs.append(f"{amount} prisoners")
    return f"locked: needs {', '.join(needs)}" if needs else ""


def format_speed(gt: Any) -> str:
    """``gt`` as shown: paused, ``Nx``, or ``?`` when unknown."""
    if gt is None:
        return "?"
    return "paused" if gt == 0 else f"{gt}x"


CALL_VEHICLE = 43  # NewVehicleCallout(vehicle)
DISMISS_SQUAD = 44  # SquadDismissal(squad: ObjectId)


def quick_items(
    objectives: Iterable[Any], speed_index: bool = False, state: Any = None
) -> list[Item]:
    """Quick actions: speeds, vehicles, squads, the CEO letter, grants."""
    speed, removed = ACTIONS[GAME_SPEED_CHANGE], ACTIONS[OBJECTIVE_REMOVED]
    items = [
        Item(f"Set speed {label}", "quick", speed, (i if speed_index else value,))
        for i, (value, label) in enumerate(SPEEDS.items())
    ]
    items += [
        Item(f"Call vehicle {name}", "quick", ACTIONS[CALL_VEHICLE], (value,))
        for value, name in sorted(VEHICLES.items())
        if value  # 0 is "None"
    ]
    if state is not None:
        with state.lock:
            squads = state.squads()
        items += [
            Item(
                f"Dismiss squad {o.label}",
                "quick",
                ACTIONS[DISMISS_SQUAD],
                (o.object_id,),
            )
            for o in squads
        ]
    # Adviser speech: the index is fixed, the message is typed in the form.
    items += [
        Item(f"{name} calls everyone", "speech", ACTIONS[NEW_SPEECH], (index,))
        for name, index in SPEAKERS.items()
    ]
    items.append(
        Item("Read the CEO's letter", "quick", removed, (CEO_LETTER_OBJECTIVE, False))
    )
    return items


def catalog_items() -> list[Item]:
    """Every catalog RPC as a row: player ones first, then host, then handshake."""
    order = {"player": 0, "host": 1, "handshake": 2}
    actions = sorted(ACTIONS.values(), key=lambda a: (order.get(a.kind, 3), a.code))
    return [Item(a.signature, a.kind, a) for a in actions]


def all_items(
    objectives: Iterable[Any], speed_index: bool = False, state: Any = None
) -> list[Item]:
    """Quick actions, the catalog, and quit."""
    return [
        *quick_items(objectives, speed_index, state),
        *catalog_items(),
        Item("Leave / quit", "view", special="quit"),
    ]


def _group(label: str, children: Sequence[Item]) -> list[Item]:
    """A folder row holding ``children`` (nothing when it would be empty)."""
    return (
        [Item(label, "group", special="group", children=tuple(children))]
        if children
        else []
    )


def _command(name: str, args: str, job: Callable[[Sequence[Any]], list[dict]]) -> Item:
    """A build command row; ``args`` are space-separated names of whole numbers."""
    typed = tuple(Arg(a, "int") for a in args.split())
    return Item(name, "build", Action(0, name, "build", typed), job=job)


def _rect(v: Sequence[Any]) -> dict[str, int]:
    x, y, w, h = (int(n) for n in v)
    return {"x": x, "y": y, "width": w, "height": h}


def hire_items() -> list[Item]:
    """One "Hire <role>" row per staff role (the ``ctl hire`` command)."""
    return [
        Item(
            f"Hire {role}",
            "staff",
            Action(0, "hire", "build", ()),
            values=(),
            job=lambda _, role=role: [{"tool": "hire", "role": role}],
        )
        for role in ("Guard", "Cook", "Doctor", "Warden", "Workman")
    ]


def build_items() -> list[Item]:
    """The ``ctl`` build commands (demolish, priority, dismantle, wire)."""
    return [
        _command(
            "Demolish area",
            "x y width height",
            lambda v: [{"tool": "demolish", "material": "Demolish", **_rect(v)}],
        ),
        _command(
            "Clear building (walls, then indoor area)",
            "x y width height",
            lambda v: [
                {"tool": "demolish", "material": m, **_rect(v)}
                for m in ("DemolishWalls", "ClearIndoorArea")
            ],
        ),
        _command(
            "High priority for area",
            "x y width height",
            lambda v: [{"tool": "priority", **_rect(v)}],
        ),
        _command(
            "Dismantle cables and pipes",
            "x y width height",
            lambda v: [{"tool": "dismantle", "kind": "DismantleUtility", **_rect(v)}],
        ),
        _command("Lay cable", "x1 y1 x2 y2", lambda v: _wire(*(int(n) for n in v))),
    ]


def _wire(x1: int, y1: int, x2: int, y2: int) -> list[dict]:
    """Cable along x, then along y (as ``ctl wire``)."""
    line = {"tool": "line", "object": "ElectricalCable", "height": 1}
    return [
        {**line, "x": min(x1, x2), "y": y1, "width": abs(x2 - x1) + 1},
        {
            **line,
            "x": x2,
            "y": min(y1, y2),
            "width": 1,
            "height": abs(y2 - y1) + 1,
        },
    ]


STAFF_FOLDER = "Staff"
FIRE_FOLDER = "Fire staff"
SACK_STAFF = 45  # SackStaff(staff: ObjectId)


def fire_items(state: Any) -> list[Item]:
    """ "Fire staff": a folder per staff type that has people, one row per person."""
    if state is None:
        return []
    sack = ACTIONS[SACK_STAFF]
    by_type: dict[str, list[Item]] = {}
    for o in state.objects(STAFF):
        by_type.setdefault(o.name, []).append(
            Item(f"Fire {o.label}", "staff", sack, (o.object_id,))
        )
    return _group(
        FIRE_FOLDER,
        [row for kind in sorted(by_type) for row in _group(kind, by_type[kind])],
    )


def _by_character(speakers: Sequence[Item]) -> list[Item]:
    """Advisers with several looks ("Don Palermo", "Don Palermo (angry)") share a folder."""
    groups: dict[str, list[Item]] = {}
    for item in speakers:
        base = item.label.removesuffix(" calls everyone").partition(" (")[0]
        groups.setdefault(base, []).append(item)
    out: list[Item] = []
    for base, rows in groups.items():
        out += rows if len(rows) == 1 else _group(base, rows)
    return out


def menu_tree(
    objectives: Iterable[Any], speed_index: bool = False, state: Any = None
) -> list[Item]:
    """The top level of the nested menu; folders hold the rest."""
    quick = quick_items(objectives, speed_index, state)

    def of(*codes: int) -> list[Item]:
        return [i for i in quick if i.action and i.action.code in codes]

    letter = [i for i in quick if i.label.startswith("Read the CEO")]
    rpcs = catalog_items()
    raw = [
        row
        for kind in ("player", "host", "handshake")
        for row in _group(kind.capitalize(), [i for i in rpcs if i.group == kind])
    ]
    return [
        *_group("Game speed", of(GAME_SPEED_CHANGE)),
        *_group(STAFF_FOLDER, [*hire_items(), *fire_items(state)]),
        *(
            [
                Item(
                    INMATES_FOLDER,
                    "inmate",
                    special="group",
                    lazy=lambda: tuple(inmate_items(state)),
                )
            ]
            if state is not None
            else []
        ),
        *_group("Build", build_items()),
        *_group(
            "Squads",
            [*_group("Call vehicle", of(CALL_VEHICLE)), *of(DISMISS_SQUAD)],
        ),
        *_group("Adviser speech", _by_character(of(NEW_SPEECH))),
        *_group("Grants", [*letter, *grant_items(objectives, state)]),
        *_group("All RPCs", raw),
        *([state_item(state)] if state is not None else []),
        Item("Leave / quit", "view", special="quit"),
    ]


def _unlocked(items: Sequence[Item], index: int, step: int, fallback: int) -> int:
    """The nearest row from ``index`` going ``step`` that isn't locked (then the other
    way); ``fallback`` when every row is locked."""
    for direction in (step, -step):
        i = index
        while 0 <= i < len(items):
            if not items[i].locked:
                return i
            i += direction
    return fallback


def _leaves(items: Iterable[Item]) -> list[Item]:
    """The runnable rows under ``items``, folders opened."""
    out: list[Item] = []
    for item in items:
        out += _leaves(item.children) if item.special == "group" else [item]
    return out


def _fuzzy(query: str, text: str) -> bool:
    it = iter(text)
    return all(ch in it for ch in query)


def filter_choices(found: Sequence[Choice], query: str) -> list[Choice]:
    """Choices whose label matches ``query``: substring first, then fuzzy."""
    q = query.strip().lower()
    if not q:
        return list(found)
    exact = [c for c in found if q in c.label.lower()]
    fuzzy = [c for c in found if c not in exact and _fuzzy(q, c.label.lower())]
    return exact + fuzzy


def filter_items(items: Sequence[Item], query: str) -> list[Item]:
    """Rows matching ``query``: substring matches first, then fuzzy (in order)."""
    q = query.strip().lower()
    if not q:
        return list(items)
    exact = [i for i in items if q in i.label.lower()]
    fuzzy = [i for i in items if i not in exact and _fuzzy(q, i.label.lower())]
    return exact + fuzzy


def room_info(session: Any) -> tuple[str, list[str], str]:
    """Room name, ``name #actor`` per player, and the connection state."""
    client = getattr(session, "client", None)
    room = getattr(client, "current_room", None)
    name = _text(getattr(room, "name", "") or "-") if room is not None else "-"
    players: list[str] = []
    found = getattr(room, "players", None) if room is not None else None
    if isinstance(found, dict):
        for number, player in sorted(found.items(), key=lambda kv: str(kv[0])):
            nick = getattr(player, "nick_name", "") or "?"
            players.append(f"{nick} #{getattr(player, 'actor_number', number)}")
    if getattr(session, "disconnected", None) is not None:
        state = f"disconnected ({session.disconnected})"
    elif getattr(session, "joined", room is not None):
        state = "in room"
    else:
        state = "connected"
    return name, players, state


def _whole(value: Any, sep: str = "") -> str:
    """``value`` rounded to a whole number (``sep``: thousands separator), ``?`` if unknown."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return "?" if value is None else str(value)
    return format(round(value), f"{sep}d")


def hud_lines(
    summary: dict[str, Any],
    room: str,
    players: Sequence[str],
    connection: str,
    titles: dict[str, str] | None = None,
    type_names: dict[int, str] | None = None,
) -> list[str]:
    """The status panel as plain lines. ``titles``: objective id -> the game's text
    (only these are listed; sub-requirements of a grant are left out).
    ``type_names``: object type id -> name."""
    balance = summary.get("balance")
    types = summary.get("object_types") or {}
    top = sorted(types.items(), key=lambda kv: -kv[1])[:8]
    systems = summary.get("systems") or {}
    time_index = summary.get("time_index")
    known = type_names or {}
    by_type = ", ".join(f"{known.get(t) or f'type {t}'}: {n}" for t, n in top)
    names = summary.get("objectives") or []
    if titles is not None:
        names = [titles[n] for n in names if n in titles]
    objectives = ", ".join(map(_text, names)) or "-"
    return [
        f"Room: {room}   Connection: {connection}",
        f"Players: {', '.join(players) or '-'}",
        (
            f"Bank: {_whole(balance, ',')}   "
            f"Time: {_whole(time_index)}   "
            f"Speed: {format_speed(summary.get('speed'))}"
        ),
        f"Objectives: {objectives}",
        f"Objects: {summary.get('objects', 0)}" + (f" ({by_type})" if top else ""),
        (
            f"Systems updated: {sum(systems.values())} ({len(systems)} systems)   "
            f"Errors: {summary.get('errors', 0)}"
        ),
    ]


STATE_FOLDER = "Browse state"
STATE_ROWS = 500  # rows shown per node; the rest is summarised in one line


def _node_item(label: str, node: Any, state: Any) -> Item:
    """A state node as a folder whose rows are read when it is opened."""
    note = f"{len(node.children)}" if node.children else f"{len(node.fields)} fields"
    return Item(
        label,
        "state",
        special="group",
        note=note,
        lazy=lambda: node_rows(node, state),
    )


def _key_order(key: str) -> tuple[bool, int, str]:
    """Numeric keys first, in numeric order, then the rest alphabetically."""
    return (not key.isdigit(), int(key) if key.isdigit() else 0, key)


def node_rows(node: Any, state: Any) -> tuple[Item, ...]:
    """A state node's fields (plain rows) and then its children (folders)."""
    with state.lock:
        rows = [
            Item(f"{key}: {_round_floats(value)}", "state", special="info")
            for key, value in sorted(node.fields.items())
        ]
        keys = sorted(node.children, key=_key_order)
        rows += [_node_item(k, node.children[k], state) for k in keys[:STATE_ROWS]]
    if len(keys) > STATE_ROWS:
        rows.append(Item(f"... {len(keys) - STATE_ROWS} more", "state", special="info"))
    return tuple(rows)


CELL_TYPES = frozenset(
    {
        "Cell",
        "FamilyCell",
        "HoldingCell",
        "PaddedCell",
        "PaddedHoldingCell",
        "SuperiorCell",
    }
)
"""Rooms that house one assigned prisoner (``Entity.i``)."""
SECURITY_GROUPS = (
    "MinSec",
    "Normal",
    "MaxSec",
    "Protected",
    "SuperMax",
    "DeathRow",
    "Insane",
)


def inmate_stats(
    state: Any,
) -> tuple[dict[str, int], tuple[int, int], int] | None:
    """Living prisoners per security group, ``(occupied, total)`` cells, and the number of
    prisoners; None until the save is loaded."""
    with state.lock:
        objects = state.save.children.get("Objects") if state.save else None
        if objects is None:
            return None
        groups = dict.fromkeys(SECURITY_GROUPS, 0)
        for node in objects.children.values():
            f = node.fields
            if _plain(f.get("Type", "")) != "Prisoner":
                continue
            if float(f.get("Damage", 0.0) or 0.0) >= 1.0:
                continue  # a dead body
            group = _plain(f.get("Category") or "MinSec")
            groups[group] = groups.get(group, 0) + 1
        cells = [r for r in state.room_list() if _plain(r["type"]) in CELL_TYPES]
    occupied = sum(1 for r in cells if r["occupant"] is not None)
    return groups, (occupied, len(cells)), sum(groups.values())


INMATES_FOLDER = "Inmates"
SEARCHABLE = (STATE_FOLDER, INMATES_FOLDER)
"""Folders read live: typing filters the rows of the folder you are in."""


def _plain(value: Any) -> str:
    return value.decode("utf-8", "replace") if isinstance(value, bytes) else str(value)


def _inmate_name(key: str, node: Any) -> str:
    bio = node.children.get("Bio")
    fields = bio.fields if bio is not None else {}
    name = f"{_plain(fields.get('Forname', ''))} {_plain(fields.get('Surname', ''))}"
    return name.strip() or key


def _index_order(key: str) -> tuple[bool, int, str]:
    """``[i N]`` entries by N (so 2 comes before 10), then the rest alphabetically."""
    match = re.fullmatch(r"\[i (\d+)\]", key)
    return (match is None, int(match.group(1)) if match else 0, key)


def _inline_needs(children: dict[str, Any]) -> dict[str, Any]:
    """Replace a ``Needs`` folder that holds a ``Needs`` list with that list's entries."""
    for key, node in children.items():
        if key.lstrip("/") != "Needs":
            continue
        for inner_key, inner in node.children.items():
            if inner_key.lstrip("/") == "Needs":
                rest = {k: v for k, v in children.items() if k != key}
                return {**rest, **inner.children}
    return children


def _inmate_commands(key: str) -> list[Item]:
    """The inmate panel's commands (security group, search, guard) for inmate ``key``."""
    who = f"#{key[3:-1]}"
    security = [
        Item(
            f"Security: {label}",
            "inmate",
            ACTIONS[38],
            (who, inmate_actions.SECURITY_CODES[group]),
        )
        for group, label in inmate_actions.SECURITY_NAMES.items()
    ]
    return [
        Item("Change security", "inmate", special="group", children=tuple(security)),
        Item("Search", "inmate", ACTIONS[35], (who, inmate_actions.PERFORM["search"])),
        Item(
            "Search cell",
            "inmate",
            ACTIONS[35],
            (who, inmate_actions.PERFORM["search-cell"]),
        ),
        Item(
            "Search cell block",
            "inmate",
            ACTIONS[35],
            (who, inmate_actions.PERFORM["search-block"]),
        ),
        Item("Lockdown 1h", "inmate", ACTIONS[39], (who, inmate_actions.LOCKDOWN, 60)),
        Item("Lockdown 6h", "inmate", ACTIONS[39], (who, inmate_actions.LOCKDOWN, 360)),
        Item(
            "Solitary 6h",
            "inmate",
            ACTIONS[39],
            (who, 2, 6 * inmate_actions.PUNISHMENTS["solitary"][1]),
        ),
        Item(
            "Solitary permanently",
            "inmate",
            ACTIONS[39],
            (who, 2, inmate_actions.PERMANENT),
        ),
        Item("End punishments", "inmate", ACTIONS[40], (who,)),
        Item("Assign guard", "inmate", ACTIONS[127], (who,)),
        Item("Unassign guard", "inmate", ACTIONS[128], (who,)),
    ]


def _inmate_rows(node: Any, state: Any, key: str = "") -> tuple[Item, ...]:
    """One inmate: its commands, the ``Bio`` fields (name, age, sentence ...) inline,
    then the rest."""
    with state.lock:
        bio = node.children.get("Bio")
        bio_fields = bio.fields if bio is not None else {}
        rows = _inmate_commands(key) if key.startswith("[i ") else []
        rows += [
            _inmate_field(k, v, bio_fields)
            for k, v in sorted(bio_fields.items(), key=_by_name)
        ]
        rows += [
            _inmate_field(k, v, node.fields)
            for k, v in sorted(node.fields.items(), key=_by_name)
        ]
        children = _inline_needs(node.children)
        keys = sorted(children, key=_index_order)
        rows += [
            _inmate_node(k, children[k], state) for k in keys[:STATE_ROWS] if k != "Bio"
        ]
    return tuple(rows)


def _inmate_node(key: str, node: Any, state: Any) -> Item:
    """A child of a prisoner (``Convictions`` and each conviction by its crime) as a folder."""
    crime = node.fields.get("Crime")
    label = (
        inmate_fields.value_of("Crime", crime)[0] if crime else inmate_fields.title(key)
    )
    if not crime and key.startswith("[i "):
        # a need is titled by its kind (Type, e.g. Bladder); anything else keeps #N
        kind = node.fields.get("Type")
        label = _plain(kind) if kind is not None else f"#{key[3:-1]}"
    note = f"{len(node.children)}" if node.children else f"{len(node.fields)} fields"

    def rows() -> tuple[Item, ...]:
        with state.lock:
            out = [
                _inmate_field(k, v, node.fields)
                for k, v in sorted(node.fields.items(), key=_by_name)
            ]
            kids = sorted(node.children, key=_key_order)
            out += [_inmate_node(k, node.children[k], state) for k in kids[:STATE_ROWS]]
        return tuple(out)

    return Item(label, "inmate", special="group", note=note, lazy=rows)


def _by_name(pair: tuple[str, Any]) -> tuple[int, str]:
    return inmate_fields.order(pair[0])


def _inmate_field(key: str, value: Any, fields: dict[str, Any]) -> Item:
    """A field as ``Readable name: readable value`` (searchable text in ``label``)."""
    name = inmate_fields.title(key)
    text, style = inmate_fields.value_of(key, value, fields)
    return Item(
        f"{name}: {text}",
        "inmate",
        special="info",
        key=name,
        shown=text,
        shown_style=style,
    )


def inmate_items(state: Any) -> list[Item]:
    """ "Inmates": a folder per prisoner in the save, holding that inmate's data."""
    with state.lock:
        objects = state.save.children.get("Objects") if state.save else None
        found = [
            (key, node)
            for key, node in (objects.children.items() if objects else ())
            if _plain(node.fields.get("Type", "")) == "Prisoner"
        ]
        names = [(_inmate_name(key, node), key, node) for key, node in found]
    seen = Counter(name for name, _, _ in names)
    rows = [
        Item(
            name if seen[name] == 1 else f"{name} {key}",
            "inmate",
            special="group",
            lazy=lambda node=node, key=key: _inmate_rows(node, state, key),
        )
        for name, key, node in sorted(names, key=lambda t: (t[0].lower(), t[1]))
    ]
    return rows or [
        Item("(no inmates known yet; `ctl refresh`)", "inmate", special="info")
    ]


def state_item(state: Any) -> Item:
    """ "Browse state": a folder per system, then nodes, then fields."""

    def systems() -> tuple[Item, ...]:
        with state.lock:
            return tuple(
                _node_item(n, state.systems[n], state) for n in sorted(state.systems)
            )

    return Item(STATE_FOLDER, "view", special="group", lazy=systems)


def field_fragments(item: Item, mark: str, style: str = "") -> StyleAndTextTuples:
    """A field row: the name in bold white, then ``: `` and the value in its colour."""
    return [
        (style, f"{mark} "),
        (f"{style} bold fg:ansiwhite".strip(), item.key),
        (f"{style} fg:ansibrightblack".strip(), ": "),
        (f"{style} {item.shown_style}".strip(), item.shown),
    ]


def _round_floats(value: Any) -> Any:
    """``value`` with every float rounded to 2 decimals (lists, tuples, dicts too)."""
    if isinstance(value, float):
        return round(value, 2)
    if isinstance(value, dict):
        return {k: _round_floats(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_round_floats(v) for v in value]
    return value


def send(session: Any, action: Action, values: Sequence[Any]) -> str:
    """Parse, build and raise ``action``; the log line for the result."""
    try:
        args = parse_args(action, list(values), session.state)
        data = rpc.build(action.code, *args)
    except (ArgError, ValueError, TypeError) as exc:
        return f"error {action.name}: {exc}"
    # Adviser speech is for every player (the host also shows it); the rest go to the host.
    ok = session.raise_event(action.code, data, broadcast=action.code == NEW_SPEECH)
    shown = ", ".join(repr(_round_floats(a)) for a in args)
    return f"sent {action.name}({shown}) -> {'queued' if ok else 'NOT queued'}"


@dataclass
class HudState:
    """What the HUD shows besides the session: mode, selection, log, prompt."""

    mode: str = "list"
    selected: int = 0
    log: deque[str] = field(default_factory=lambda: deque(maxlen=LOG_LINES))
    seen_feed: int = 0
    item: Item | None = None
    values: list[str] = field(default_factory=list)
    filter: str = ""
    choice: int = 0
    """Highlighted row of the current argument's (filtered) choices."""
    path: list[str] = field(default_factory=list)
    """Labels of the folders entered, outermost first."""
    came_from: list[int] = field(default_factory=list)
    """The selected row in each folder above, to return to on leaving."""


class Hud:
    """The HUD application around a session."""

    def __init__(
        self, session: Session, opts: Options, *, input: Any = None, output: Any = None
    ) -> None:
        """Build the layout and key bindings."""
        self.session, self.opts = session, opts
        self.ui = HudState()
        self.buffer = Buffer(multiline=False, on_text_changed=self._on_text)
        self.app: Application[None] = Application(
            layout=Layout(self._layout(), focused_element=self.buffer),
            key_bindings=self._keys(),
            full_screen=True,
            input=input,
            output=output,
            refresh_interval=REFRESH,
            mouse_support=True,
        )

    # data
    def items(self) -> list[Item]:
        """The rows of the current folder; with a filter, every runnable row matching it."""
        rows = menu_tree(
            self.session.objectives, self.opts.speed_index, self.session.state
        )
        in_state = bool(self.ui.path) and self.ui.path[0] in SEARCHABLE
        if self.ui.filter.strip() and not in_state:
            return filter_items(_leaves(rows), self.ui.filter)
        for label in self.ui.path:
            rows = next((r.rows for r in rows if r.label == label), rows)
        return filter_items(rows, self.ui.filter) if in_state else rows

    def current_arg(self) -> Arg | None:
        """The argument being entered in the form, or None."""
        item = self.ui.item
        if self.ui.mode != "args" or item is None or item.action is None:
            return None
        args = item.action.args
        return args[len(self.ui.values)] if len(self.ui.values) < len(args) else None

    def all_choices(self) -> list[Choice]:
        """The current argument's choices from the live state (unfiltered)."""
        arg = self.current_arg()
        if arg is None:
            return []
        state = self.session.state
        with state.lock:
            return choices(arg, state)

    def arg_choices(self) -> list[Choice]:
        """The current argument's choices, filtered by the typed text."""
        shown = filter_choices(self.all_choices(), self.buffer.text)
        self.ui.choice = min(self.ui.choice, max(len(shown) - 1, 0))
        return shown

    def _pull_feed(self) -> None:
        state = self.session.state
        with state.lock:
            feed = list(state.feed)
        # The feed is a bounded deque: if it rolled over, show its tail.
        new = feed[self.ui.seen_feed :] if self.ui.seen_feed <= len(feed) else feed
        self.ui.log.extend(new)
        self.ui.seen_feed = len(feed)

    def add_log(self, line: str) -> None:
        """Append a line to the log."""
        self.ui.log.append(line)

    # rendering
    def _hud(self) -> StyleAndTextTuples:
        room, players, connection = room_info(self.session)
        state = self.session.state
        titles = {
            i["id"]: i["title"]
            for i in state.todo()
            if i.get("kind") in ("objective", "advice")
        }
        lines = hud_lines(
            state.summary(), room, players, connection, titles, state.type_names
        )
        out: StyleAndTextTuples = [("bold fg:ansibrightcyan", "Prison Architect bot\n")]
        for line in lines:
            out.append(("", line + "\n"))
        return out

    def staff_counts(self) -> dict[str, int]:
        """Staff currently in the prison, per type."""
        counts = dict.fromkeys(sorted(STAFF), 0)
        for o in self.session.state.objects(STAFF):
            counts[o.name] += 1
        return counts

    def _staff(self) -> StyleAndTextTuples:
        """The staff panel; clicking a type opens the fire menu for it."""
        out: StyleAndTextTuples = [("bold fg:ansibrightcyan", " Staff (click: fire)\n")]
        for kind, count in self.staff_counts().items():

            def click(event: MouseEvent, kind: str = kind) -> None:
                if event.event_type == MouseEventType.MOUSE_UP:
                    self.open_fire(kind)

            style = "" if count else "fg:ansibrightblack"
            out.append((style, f" {kind:<10}{count:>4}", click))
            out.append(("", "\n"))
        return out

    def _inmates(self) -> StyleAndTextTuples:
        """Inmates per security group, then how many cells are occupied."""
        return [(style, text + "\n") for style, text in self._inmate_lines()]

    def _inmate_lines(self) -> list[tuple[str, str]]:
        head = "bold fg:ansibrightcyan"
        stats = inmate_stats(self.session.state)
        if stats is None:
            dots = "." * (int(time.monotonic() * 2) % 3 + 1)  # Loading. / .. / ...
            return [(head, " Inmates"), ("fg:ansibrightblack", f" Loading{dots}")]
        by_group, cells, total = stats
        lines = [(head, f" Inmates ({sum(by_group.values())})")]
        lines += [("", f" {group:<10}{n:>4}") for group, n in by_group.items() if n]
        free = cells[1] - cells[0]
        lines.append((head, " Cells"))
        lines.append(("", f" {'occupied':<10}{cells[0]:>4}/{cells[1]}"))
        lines.append(
            ("fg:ansibrightblack" if not free else "", f" {'free':<10}{free:>4}")
        )
        return lines

    def _squads_row(self) -> int:
        """First row below the header and the inmates panel (where the squads float goes)."""
        return 8 + len(self._inmate_lines())

    def open_fire(self, kind: str) -> None:
        """Jump the action menu to the people of one staff type, to fire them."""
        if not self.staff_counts().get(kind):
            self.add_log(f"no {kind} to fire")
            return
        self.ui.filter = ""
        self._reset()
        self.ui.path = [STAFF_FOLDER, FIRE_FOLDER, kind]
        self.ui.came_from = [0, 0, 0]
        self.ui.selected = 0

    def _list(self) -> StyleAndTextTuples:
        if self.ui.mode == "args" and self.ui.item and self.ui.item.action:
            return self._arg_form()
        items = self.items()
        self.ui.selected = _unlocked(
            items, min(self.ui.selected, max(len(items) - 1, 0)), 1, 0
        )
        out: StyleAndTextTuples = []
        if self._header_rows():
            out.append(("bold fg:ansicyan", "  " + " > ".join(self.ui.path) + "\n"))
        for i, item in enumerate(items):
            mark = "❯" if i == self.ui.selected else " "
            style = "reverse" if i == self.ui.selected else ""
            if item.blocked:
                style += " fg:ansibrightblack"
                line = f"{mark} {item.label}  ({item.blocked})"
            elif item.key:
                out += field_fragments(item, mark, style)
                line = ""
            else:
                line = f"{mark} {item.label}" + (
                    " >" if item.special == "group" else ""
                )
            if line:
                out.append((style, line))
            if item.note:
                out.append(("fg:ansibrightblack", f"  {item.note}"))
            out.append(("", "\n"))
        if not items:
            out.append(("fg:ansibrightblack", "  (nothing matches)"))
        return out

    def _cursor_row(self) -> int:
        """Row of the action list to keep in view (0 outside the list)."""
        if self.ui.mode != "list":
            return 0
        return self.ui.selected + self._header_rows()

    def _header_rows(self) -> int:
        """1 when the list starts with the folder breadcrumb (inside a folder; a search
        across all folders has none, except inside the state browser)."""
        if self.ui.mode != "list" or not self.ui.path:
            return 0
        in_state = self.ui.path[0] in SEARCHABLE
        return 1 if in_state or not self.ui.filter.strip() else 0

    def _arg_form(self) -> StyleAndTextTuples:
        action = self.ui.item.action if self.ui.item else None
        assert action is not None
        out: StyleAndTextTuples = [("bold", f"{action.signature}\n\n")]
        current = len(self.ui.values)
        for i, arg in enumerate(action.args):
            value = (
                self.ui.values[i]
                if i < current
                else self.buffer.text
                if i == current
                else ""
            )
            style = "reverse" if i == current else ""
            out.append((style, f"  {arg.name} ({arg.type}, {arg.hint}): {value}\n"))
        arg = self.current_arg()
        if arg is None or not source(arg):
            return out
        dim = DIM
        out.append(("bold", f"\n{arg.name} ({arg.type}): pick one\n"))
        if not self.all_choices():
            out.append((dim, f"  (no {source(arg)} available yet; type a value)\n"))
            return out
        shown = self.arg_choices()
        for i, choice in enumerate(shown):
            mark = "❯" if i == self.ui.choice else " "
            style = "reverse" if i == self.ui.choice else ""
            out.append((style, f"{mark} {choice.label}\n"))
        if not shown:
            out.append((dim, "  (no match; Enter uses the typed value)\n"))
        return out

    def _prompt(self) -> StyleAndTextTuples:
        if self.ui.mode == "args" and self.ui.item and self.ui.item.action:
            arg = self.ui.item.action.args[len(self.ui.values)]
            return [("bold fg:ansiyellow", f"{arg.name}> ")]
        return [("bold fg:ansicyan", "filter> ")]

    def _log(self) -> StyleAndTextTuples:
        # Read-only: the feed is pulled in _watch, never during a redraw.
        return [("", "\n".join(list(self.ui.log)[-LOG_VIEW:]))]

    def _title(self) -> str:
        """The name of the input box's top rule: what the input is for."""
        if self.ui.mode == "args" and self.ui.item and self.ui.item.action:
            return self.ui.item.action.signature
        if self.ui.mode == "args":
            return "args"
        return " > ".join(["actions", *self.ui.path])

    def _placeholder(self) -> str:
        """Dim hint shown in the empty input line."""
        if self.ui.mode == "args":
            return "type a value, or pick one above"
        return "type to filter the actions"

    def squad_rows(self) -> list[str]:
        """One line per called-in squad (vehicle name and index)."""
        with self.session.state.lock:
            squads = self.session.state.squads()
        rows = []
        for s in squads:
            kind = int(s.name) if s.name.lstrip("-").isdigit() else None
            rows.append(f" {VEHICLES.get(kind, s.name)} #{s.index}")
        return rows

    def _squads(self) -> StyleAndTextTuples:
        rows = self.squad_rows()
        out: StyleAndTextTuples = [
            ("bold fg:ansibrightcyan", f" Squads ({len(rows)})\n")
        ]
        out += [("", row + "\n") for row in rows]
        return out

    def _layout(self) -> FloatContainer:
        """Status, actions, then messages and instructions pinned above the input box.

        The squads panel floats over the action list, under the staff panel, and
        only shows while a squad is out."""
        dim = DIM
        empty = Condition(lambda: not self.buffer.text)
        many = Condition(lambda: bool(self.squad_rows()))
        squads = Window(
            FormattedTextControl(self._squads),
            width=22,
            height=lambda: min(len(self.squad_rows()) + 1, 7),
            style="bg:#202020",
        )
        base = HSplit(
            [
                VSplit(
                    [
                        Window(FormattedTextControl(self._hud)),
                        Window(width=1, char="│", style=dim),
                        Window(FormattedTextControl(self._staff), width=22),
                    ],
                    height=7,
                ),
                Window(height=1, char=RULE, style=dim),
                # The cursor position (the selected row) makes the window scroll
                # to keep the selection in view.
                VSplit(
                    [
                        Window(
                            FormattedTextControl(
                                self._list,
                                get_cursor_position=lambda: Point(
                                    0, self._cursor_row()
                                ),
                            ),
                            wrap_lines=False,
                            always_hide_cursor=True,
                        ),
                        Window(width=1, char="│", style=dim),
                        Window(FormattedTextControl(self._inmates), width=22),
                    ]
                ),
                Window(height=1, char=RULE, style=dim),
                # Fixed-height pane: new messages scroll in at the bottom and
                # nothing above it moves. Lines are not wrapped, so the height
                # never changes with message length.
                Window(
                    FormattedTextControl(self._log),
                    height=LOG_VIEW,
                    wrap_lines=False,
                    dont_extend_height=True,
                    always_hide_cursor=True,
                ),
                Window(
                    FormattedTextControl(lambda: [(dim, HELP[self.ui.mode])]), height=1
                ),
                # The input in a full box; the frame's title says what it is for.
                Frame(
                    Window(
                        BufferControl(
                            self.buffer,
                            input_processors=[
                                ConditionalProcessor(
                                    AfterInput(lambda: [(dim, self._placeholder())]),
                                    filter=empty,
                                )
                            ],
                        ),
                        height=1,
                        get_line_prefix=lambda *_: [("", " ")] + self._prompt(),
                    ),
                    title=self._title,
                    style=dim,
                ),
            ]
        )
        return FloatContainer(
            base,
            floats=[
                _FloatBelow(
                    ConditionalContainer(squads, filter=many),
                    self._squads_row,
                    right=0,
                )
            ],
        )

    # input
    def _on_text(self, _: Buffer) -> None:
        if self.ui.mode == "list":
            self.ui.filter = self.buffer.text
            self.ui.selected = 0
        else:
            self.ui.choice = 0

    def _reset(self, mode: str = "list") -> None:
        self.ui.mode, self.ui.item, self.ui.values = mode, None, []
        self.ui.choice = 0
        self.buffer.text = self.ui.filter if mode == "list" else ""

    def move(self, delta: int) -> None:
        """Move the selection (list, argument choices)."""
        if self.ui.mode == "args":
            count = len(self.arg_choices())
            self.ui.choice = max(min(self.ui.choice + delta, count - 1), 0)
        elif self.ui.mode == "list":
            items = self.items()
            target = max(min(self.ui.selected + delta, len(items) - 1), 0)
            self.ui.selected = _unlocked(
                items, target, 1 if delta > 0 else -1, self.ui.selected
            )

    def activate(self) -> None:
        """Enter: run the selected row, or advance the argument form."""
        if self.ui.mode == "args":
            self.next_field()
            return
        if self.ui.mode != "list":
            return
        items = self.items()
        if not items:
            return
        item = items[self.ui.selected]
        if item.locked:
            self.add_log(f"{item.label} {item.locked}")
        elif item.special == "group":
            self.ui.path.append(item.label)
            self.ui.came_from.append(self.ui.selected)
            self.ui.selected = 0
        elif item.special == "quit":
            self.app.exit()
        elif item.special == "info":
            pass  # a state field: just something to read
        elif item.blocked or item.action is None:
            self.add_log(f"blocked {item.label}: {item.blocked}")
        elif not item.action.args or (
            item.values is not None and len(item.values) >= len(item.action.args)
        ):
            self._run(item, item.values or ())
        else:
            # Fixed leading values (a speaker) are filled in; the form asks for the rest.
            prefilled = [str(v) for v in item.values or ()]
            self.ui.mode, self.ui.item, self.ui.values = "args", item, prefilled
            self.buffer.text = ""
            self.ui.choice = 0

    def _run(self, item: Item, values: Sequence[Any]) -> None:
        """Send an RPC row, or queue a build command's jobs."""
        assert item.action is not None
        if item.job is None:
            self.add_log(send(self.session, item.action, values))
            return
        try:
            jobs = [build.job_from(s) for s in item.job(values)]
        except (build.BuildError, ValueError) as exc:
            self.add_log(f"error {item.label}: {exc}")
            return
        ok = self.session.build(jobs)
        self.add_log(
            f"{item.label} {list(values)} -> {'queued' if ok else 'NOT queued'}"
        )

    def next_field(self) -> None:
        """Keep the highlighted choice's label (or the typed text); send at the end."""
        item = self.ui.item
        if item is None or item.action is None:
            return
        shown = self.arg_choices()
        value = shown[self.ui.choice].label if shown else self.buffer.text
        self.ui.values.append(value)
        self.buffer.text = ""
        self.ui.choice = 0
        if len(self.ui.values) >= len(item.action.args):
            self._run(item, self.ui.values)
            self._reset()

    def previous_field(self) -> None:
        """Go back to the previous argument."""
        if self.ui.mode == "args" and self.ui.values:
            self.buffer.text = self.ui.values.pop()

    def escape(self) -> None:
        """Cancel the form / leave the browser / clear the filter / leave a folder."""
        if self.ui.mode == "list":
            if self.ui.filter or self.buffer.text:
                self.ui.filter = ""
                self.buffer.text = ""
                self.ui.selected = 0
            elif self.ui.path:
                self.ui.path.pop()
                self.ui.selected = self.ui.came_from.pop()
        else:
            if self.ui.mode == "args":
                self.add_log("cancelled")
            self._reset()

    def toggle_browse(self) -> None:
        """F2: switch between the action menu and the "Browse state" folder."""
        if self.ui.mode == "list" and self.ui.path[:1] == [STATE_FOLDER]:
            self.ui.selected = self.ui.came_from[0]
            self.ui.path, self.ui.came_from = [], []
            return
        origin = self.ui.selected if not self.ui.path else 0
        self.ui.filter = ""
        self._reset()
        self.ui.path, self.ui.came_from = [STATE_FOLDER], [origin]
        self.ui.selected = 0

    def _on_group(self) -> bool:
        """True when the hovered row is a folder (Right opens it)."""
        if self.ui.mode != "list":
            return False
        items = self.items()
        return bool(items) and items[self.ui.selected].special == "group"

    def _keys(self) -> KeyBindings:
        keys = KeyBindings()

        def bind(*names: str, fn: Any) -> None:
            @keys.add(*names, eager=True)
            def _(event: KeyPressEvent) -> None:
                fn()

        bind("up", fn=lambda: self.move(-1))
        bind("down", fn=lambda: self.move(1))
        bind("pageup", fn=lambda: self.move(-10))
        bind("pagedown", fn=lambda: self.move(10))
        bind("enter", fn=self.activate)
        on_group = Condition(self._on_group)
        keys.add("right", filter=on_group, eager=True)(lambda event: self.activate())
        can_back = Condition(
            lambda: (
                self.ui.mode == "list" and bool(self.ui.path) and not self.buffer.text
            )
        )
        keys.add("left", filter=can_back, eager=True)(lambda event: self.escape())
        bind("escape", fn=self.escape)
        bind("f2", fn=self.toggle_browse)
        bind("s-tab", fn=self.previous_field)

        @keys.add("tab", eager=True)
        def _(event: KeyPressEvent) -> None:
            if self.ui.mode == "args":
                self.next_field()

        @keys.add("c-c", eager=True)
        @keys.add("c-q", eager=True)
        def _(event: KeyPressEvent) -> None:
            event.app.exit()

        return keys

    # running
    async def _watch(self) -> None:
        while True:
            if getattr(self.session, "disconnected", None) is not None:
                self.add_log(f"disconnected: {self.session.disconnected}")
                self.app.exit()
                return
            self._pull_feed()
            await asyncio.sleep(REFRESH)

    def run(self) -> None:
        """Run until quit or disconnect."""
        self.app.run(pre_run=lambda: self.app.create_background_task(self._watch()))


def run_hud(
    session: Session, opts: Options, *, input: Any = None, output: Any = None
) -> None:
    """Show the HUD for ``session``; returns when the user quits or it disconnects."""
    Hud(session, opts, input=input, output=output).run()
