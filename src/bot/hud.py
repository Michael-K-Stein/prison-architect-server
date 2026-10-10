"""The bot's full-screen HUD: live status, a filterable action list, input and log."""

from __future__ import annotations

import asyncio
import json
from collections import deque
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from prompt_toolkit import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.formatted_text import StyleAndTextTuples
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
from prompt_toolkit.layout import HSplit, Layout, Window
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl

from src.bot.actions import (
    ACCEPT_GRANT,
    CANCEL_GRANT,
    CEO_LETTER_OBJECTIVE,
    FIRST_GRANT,
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
from src.bot.session import Options, Session
from src.bot.speed import GAME_SPEED_CHANGE
from src.protocol import rpc
from src.protocol.enums import VEHICLES

REFRESH = 0.25  # seconds between HUD redraws
LOG_LINES = 500
BROWSE_DEPTH = 2
HELP = {
    "list": "type: filter  up/down/PgUp/PgDn: move  Enter: run  F2: state  "
    "Esc: clear  Ctrl-Q: quit",
    "args": "type: filter/raw value  up/down: pick  Tab/Enter: next field  "
    "Shift-Tab: previous  Esc: cancel",
    "browse": "type: System/child/path  up/down: scroll  F2/Esc: back  Ctrl-Q: quit",
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
    """``browse`` / ``quit`` for the non-RPC rows."""

    @property
    def blocked(self) -> str:
        """Why it can't be sent, or ''."""
        return self.action.blocked if self.action is not None else ""


def _text(value: Any) -> str:
    return value.decode("utf-8", "replace") if isinstance(value, bytes) else str(value)


def grant_names(objectives: Iterable[Any]) -> list[str]:
    """Grant names from ``Grant_<name>`` objectives (not ``Grant_<name>_<part>``)."""
    names = set()
    for objective in objectives:
        text = _text(objective)
        if text.startswith("Grant_"):
            name = text[len("Grant_") :]
            if name and "_" not in name:
                names.add(name)
    return sorted(names) or [FIRST_GRANT]


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
    items.append(
        Item("Read the CEO's letter", "quick", removed, (CEO_LETTER_OBJECTIVE, False))
    )
    for grant in grant_names(objectives):
        items.append(
            Item(f"Accept grant {grant}", "quick", ACTIONS[ACCEPT_GRANT], (grant,))
        )
        items.append(
            Item(f"Cancel grant {grant}", "quick", ACTIONS[CANCEL_GRANT], (grant,))
        )
    items.append(Item("Browse state", "view", special="browse"))
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


def hud_lines(
    summary: dict[str, Any], room: str, players: Sequence[str], connection: str
) -> list[str]:
    """The status panel as plain lines."""
    balance = summary.get("balance")
    types = summary.get("object_types") or {}
    top = sorted(types.items(), key=lambda kv: -kv[1])[:8]
    systems = summary.get("systems") or {}
    time_index = summary.get("time_index")
    by_type = ", ".join(f"type {t}: {n}" for t, n in top)
    objectives = ", ".join(map(_text, summary.get("objectives") or [])) or "-"
    return [
        f"Room: {room}   Connection: {connection}",
        f"Players: {', '.join(players) or '-'}",
        (
            f"Bank: {'?' if balance is None else balance}   "
            f"Time: {'?' if time_index is None else time_index}   "
            f"Speed: {format_speed(summary.get('speed'))}"
        ),
        f"Objectives: {objectives}",
        f"Objects: {summary.get('objects', 0)}" + (f" ({by_type})" if top else ""),
        (
            f"Systems updated: {sum(systems.values())} ({len(systems)} systems)   "
            f"Errors: {summary.get('errors', 0)}"
        ),
    ]


def browse_text(state: Any, path: str, depth: int = BROWSE_DEPTH) -> str:
    """A system's merged tree at ``System/child/...`` as JSON, or the system list."""
    system, _, rest = path.strip().strip("/").partition("/")
    with state.lock:
        if not system:
            names = sorted(state.systems)
            return "Systems (type a name):\n" + "\n".join(
                f"  {n} ({len(state.systems[n].children)} children)" for n in names
            )
        root = state.systems.get(system)
        node = root.find(rest) if root is not None else None
        if node is None:
            return f"No state at {path!r}. Systems: {', '.join(sorted(state.systems))}"
        tree = node.to_dict(depth)
    return json.dumps(tree, indent=1, default=str)


def send(session: Any, action: Action, values: Sequence[Any]) -> str:
    """Parse, build and raise ``action``; the log line for the result."""
    try:
        args = parse_args(action, list(values), session.state)
        data = rpc.build(action.code, *args)
    except (ArgError, ValueError, TypeError) as exc:
        return f"error {action.name}: {exc}"
    ok = session.raise_event(action.code, data)
    shown = ", ".join(repr(a) for a in args)
    return f"sent {action.name}({shown}) -> {'queued' if ok else 'NOT queued'}"


@dataclass
class HudState:
    """What the HUD shows besides the session: mode, selection, log, prompt."""

    mode: str = "list"
    selected: int = 0
    scroll: int = 0
    log: deque[str] = field(default_factory=lambda: deque(maxlen=LOG_LINES))
    seen_feed: int = 0
    item: Item | None = None
    values: list[str] = field(default_factory=list)
    filter: str = ""
    choice: int = 0
    """Highlighted row of the current argument's (filtered) choices."""


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
            mouse_support=False,
        )

    # data
    def items(self) -> list[Item]:
        """The current rows, filtered."""
        rows = all_items(
            self.session.objectives, self.opts.speed_index, self.session.state
        )
        return filter_items(rows, self.ui.filter)

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
        lines = hud_lines(self.session.state.summary(), room, players, connection)
        out: StyleAndTextTuples = [("bold fg:ansibrightcyan", "Prison Architect bot\n")]
        for line in lines:
            out.append(("", line + "\n"))
        return out

    def _list(self) -> StyleAndTextTuples:
        if self.ui.mode == "browse":
            text = browse_text(self.session.state, self.buffer.text)
            lines = text.splitlines()[self.ui.scroll :]
            return [("", "\n".join(lines))]
        if self.ui.mode == "args" and self.ui.item and self.ui.item.action:
            return self._arg_form()
        items = self.items()
        self.ui.selected = min(self.ui.selected, max(len(items) - 1, 0))
        out: StyleAndTextTuples = []
        for i, item in enumerate(items):
            mark = ">" if i == self.ui.selected else " "
            style = "reverse" if i == self.ui.selected else ""
            tag = f"[{item.group}]".ljust(12)
            if item.blocked:
                style += " fg:ansibrightblack"
                line = f"{mark} {tag}{item.label}  ({item.blocked})"
            else:
                line = f"{mark} {tag}{item.label}"
            out.append((style, line + "\n"))
        if not items:
            out.append(("fg:ansibrightblack", "  (nothing matches)"))
        return out

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
        dim = "fg:ansibrightblack"
        out.append(("bold", f"\n{arg.name} ({arg.type}): pick one\n"))
        if not self.all_choices():
            out.append((dim, f"  (no {source(arg)} available yet; type a value)\n"))
            return out
        shown = self.arg_choices()
        for i, choice in enumerate(shown):
            mark = ">" if i == self.ui.choice else " "
            style = "reverse" if i == self.ui.choice else ""
            out.append((style, f"{mark} {choice.label}\n"))
        if not shown:
            out.append((dim, "  (no match; Enter uses the typed value)\n"))
        return out

    def _prompt(self) -> StyleAndTextTuples:
        if self.ui.mode == "args" and self.ui.item and self.ui.item.action:
            arg = self.ui.item.action.args[len(self.ui.values)]
            return [("bold fg:ansiyellow", f"{arg.name}> ")]
        if self.ui.mode == "browse":
            return [("bold fg:ansigreen", "path> ")]
        return [("bold fg:ansicyan", "filter> ")]

    def _log(self) -> StyleAndTextTuples:
        self._pull_feed()
        return [("", "\n".join(list(self.ui.log)[-8:]))]

    def _layout(self) -> HSplit:
        dim = "fg:ansibrightblack"
        return HSplit(
            [
                Window(FormattedTextControl(self._hud), height=7),
                Window(height=1, char="─", style=dim),
                Window(FormattedTextControl(self._list), wrap_lines=False),
                Window(height=1, char="─", style=dim),
                Window(
                    BufferControl(self.buffer),
                    height=1,
                    get_line_prefix=lambda *_: self._prompt(),
                ),
                Window(height=1, char="─", style=dim),
                Window(FormattedTextControl(self._log), height=8, wrap_lines=True),
                Window(
                    FormattedTextControl(lambda: [(dim, HELP[self.ui.mode])]), height=1
                ),
            ]
        )

    # input
    def _on_text(self, _: Buffer) -> None:
        if self.ui.mode == "list":
            self.ui.filter = self.buffer.text
            self.ui.selected = 0
        elif self.ui.mode == "browse":
            self.ui.scroll = 0
        else:
            self.ui.choice = 0

    def _reset(self, mode: str = "list") -> None:
        self.ui.mode, self.ui.item, self.ui.values = mode, None, []
        self.ui.scroll, self.ui.choice = 0, 0
        self.buffer.text = self.ui.filter if mode == "list" else ""

    def move(self, delta: int) -> None:
        """Move the selection (list, argument choices) or scroll (browse)."""
        if self.ui.mode == "browse":
            self.ui.scroll = max(self.ui.scroll + delta, 0)
        elif self.ui.mode == "args":
            count = len(self.arg_choices())
            self.ui.choice = max(min(self.ui.choice + delta, count - 1), 0)
        elif self.ui.mode == "list":
            count = len(self.items())
            self.ui.selected = max(min(self.ui.selected + delta, count - 1), 0)

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
        if item.special == "quit":
            self.app.exit()
        elif item.special == "browse":
            self._reset("browse")
        elif item.blocked or item.action is None:
            self.add_log(f"blocked {item.label}: {item.blocked}")
        elif item.values is not None or not item.action.args:
            self.add_log(send(self.session, item.action, item.values or ()))
        else:
            self.ui.mode, self.ui.item, self.ui.values = "args", item, []
            self.buffer.text = ""
            self.ui.choice = 0

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
            self.add_log(send(self.session, item.action, self.ui.values))
            self._reset()

    def previous_field(self) -> None:
        """Go back to the previous argument."""
        if self.ui.mode == "args" and self.ui.values:
            self.buffer.text = self.ui.values.pop()

    def escape(self) -> None:
        """Cancel the form / leave the browser / clear the filter."""
        if self.ui.mode == "list":
            self.ui.filter = ""
            self.buffer.text = ""
        else:
            if self.ui.mode == "args":
                self.add_log("cancelled")
            self._reset()

    def toggle_browse(self) -> None:
        """F2: switch between the action list and the state browser."""
        if self.ui.mode == "browse":
            self._reset()
        else:
            self._reset("browse")

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
            await asyncio.sleep(REFRESH)

    def run(self) -> None:
        """Run until quit or disconnect."""
        self.app.run(pre_run=lambda: self.app.create_background_task(self._watch()))


def run_hud(
    session: Session, opts: Options, *, input: Any = None, output: Any = None
) -> None:
    """Show the HUD for ``session``; returns when the user quits or it disconnects."""
    Hud(session, opts, input=input, output=output).run()
