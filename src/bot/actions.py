"""The in-game menu and the actions it offers (each one sends or shows something)."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from rich.console import Console

from src.bot.flow import pick
from src.bot.formatting import format_event_lines
from src.bot.session import Options, Session
from src.bot.slider import pick_speed
from src.bot.speed import GAME_SPEED_CHANGE, SPEED_STOPS, speed_wire_value
from src.protocol import rpc

OBJECTIVE_REMOVED = 21  # RPC code, ``ObjectiveRemoved(string, bool)``
CEO_LETTER_OBJECTIVE = "ReadCeosLetter"  # captures/ad-hoc/read-ceo-letter.sqlite

console = Console()
log = logging.getLogger(__name__)


@dataclass
class Context:
    """What an action handler gets."""

    session: Session
    opts: Options
    log: list[str] = field(default_factory=list)


def action_speed(ctx: Context) -> None:
    """Pick a speed on the slider and send ``GameSpeedChange``."""
    index = pick_speed()
    if index is None:
        log.info("speed: cancelled")
        return
    value = speed_wire_value(index, speed_index=ctx.opts.speed_index)
    log.info("speed: %s chosen, wire value %d", SPEED_STOPS[index][0], value)
    data = rpc.build(GAME_SPEED_CHANGE, value)
    ok = ctx.session.raise_event(GAME_SPEED_CHANGE, data)
    mode = "index" if ctx.opts.speed_index else "multiplier"
    console.print(
        f"{'sent' if ok else 'NOT sent'} GameSpeedChange({value}) [{mode}] "
        f"event {GAME_SPEED_CHANGE}, Data={data.hex(' ')}  (unverified)",
        markup=False,
    )
    ctx.log.append(f"speed {SPEED_STOPS[index][0]} -> {value}")


def action_read_ceo_letter(ctx: Context) -> None:
    """Send ``ObjectiveRemoved("ReadCeosLetter", False)``, as the client does."""
    data = rpc.build(OBJECTIVE_REMOVED, CEO_LETTER_OBJECTIVE, False)
    ok = ctx.session.raise_event(OBJECTIVE_REMOVED, data)
    console.print(
        f"{'sent' if ok else 'NOT sent'} ObjectiveRemoved({CEO_LETTER_OBJECTIVE!r}, "
        f"False) event {OBJECTIVE_REMOVED}, Data={data.hex(' ')}",
        markup=False,
    )
    ctx.log.append(f"objective removed {CEO_LETTER_OBJECTIVE}")


def action_events(ctx: Context) -> None:
    """Stream incoming game events until Ctrl-C."""
    console.print("[dim]Streaming events, Ctrl-C to stop.[/dim]")
    try:
        while True:
            while ctx.session.events:
                sender, code, data = ctx.session.events.popleft()
                for line in format_event_lines(
                    sender, code, data, verbose=ctx.opts.full_events
                ):
                    console.print(line, markup=False, highlight=False)
            if ctx.session.disconnected is not None:
                console.print("[red]Disconnected.[/red]")
                return
            time.sleep(0.1)
    except KeyboardInterrupt:
        console.print()


# Add new RPC actions here: (menu label, handler taking a Context).
ACTIONS: list[tuple[str, Callable[[Context], None]]] = [
    ("Change game speed", action_speed),
    ("Read the CEO's letter", action_read_ceo_letter),
    ("Show incoming events", action_events),
]


def _menu_title(session: Session) -> str:
    """The menu heading, with the current objectives under it."""
    title = "Prison Architect bot"
    if session.objectives:
        title += "\nObjectives: " + ", ".join(sorted(session.objectives))
    return title


def menu(ctx: Context) -> None:
    """The in-game main menu; returns when the user leaves."""
    while ctx.session.disconnected is None:
        choice = pick(
            _menu_title(ctx.session),
            [*[(label, fn) for label, fn in ACTIONS], ("Leave / quit", None)],
        )
        if choice is None:
            log.info("menu: leave")
            return
        name = choice.__name__
        log.info("action %s: start", name)
        try:
            choice(ctx)
        except Exception:
            log.exception("action %s failed", name)
            raise
        log.info("action %s: end", name)
