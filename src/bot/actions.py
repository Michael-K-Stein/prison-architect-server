"""The in-game menu and the actions it offers (each one sends or shows something)."""

from __future__ import annotations

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

console = Console()


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
        return
    value = speed_wire_value(index, speed_index=ctx.opts.speed_index)
    data = rpc.build(GAME_SPEED_CHANGE, value)
    ok = ctx.session.raise_event(GAME_SPEED_CHANGE, data)
    mode = "index" if ctx.opts.speed_index else "multiplier"
    console.print(
        f"{'sent' if ok else 'NOT sent'} GameSpeedChange({value}) [{mode}] "
        f"event {GAME_SPEED_CHANGE}, Data={data.hex(' ')}  (unverified)",
        markup=False,
    )
    ctx.log.append(f"speed {SPEED_STOPS[index][0]} -> {value}")


def action_events(ctx: Context) -> None:
    """Stream incoming game events until Ctrl-C."""
    console.print("[dim]Streaming events, Ctrl-C to stop.[/dim]")
    try:
        while True:
            while ctx.session.events:
                sender, code, data = ctx.session.events.popleft()
                for line in format_event_lines(
                    sender, code, data, verbose=ctx.opts.verbose
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
    ("Show incoming events", action_events),
]


def menu(ctx: Context) -> None:
    """The in-game main menu; returns when the user leaves."""
    while ctx.session.disconnected is None:
        choice = pick(
            "Prison Architect bot",
            [*[(label, fn) for label, fn in ACTIONS], ("Leave / quit", None)],
        )
        if choice is None:
            return
        choice(ctx)
