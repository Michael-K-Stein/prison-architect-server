"""Read a capture recorded by ``main.py proxy --record``.

``tail`` it live, or list its sessions.

Usage::

    python main.py capture tail captures/run1.sqlite [--from-start] [--code N ...]
    python main.py capture sessions captures/run1.sqlite
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Annotated, Optional

import typer

from src.capture.reader import Capture
from src.capture.render import _render
from src.capture.schema import TO_CLIENT, TO_SERVER


class Direction(str, Enum):
    """Which way packets must travel to be shown."""

    to_server = "to-server"
    to_client = "to-client"


PathArg = Annotated[Path, typer.Argument(help="Capture file (.sqlite).")]

app = typer.Typer(
    help="Read a capture recorded by `main.py proxy --record`.",
    rich_markup_mode="rich",
    no_args_is_help=True,
)


@app.command()
def tail(
    path: PathArg,
    from_start: Annotated[
        bool,
        typer.Option(
            "--from-start",
            help="Print the whole capture first, then new packets.",
        ),
    ] = False,
    code: Annotated[
        Optional[list[int]],
        typer.Option(
            "--code",
            metavar="N",
            help="Only operations/events with these codes (repeatable).",
        ),
    ] = None,
    dir: Annotated[
        Optional[Direction],
        typer.Option(help="Only packets in one direction."),
    ] = None,
    raw: Annotated[
        bool,
        typer.Option(
            "--raw",
            help="Print names and hex payloads instead of decoded parameters.",
        ),
    ] = False,
    timeout: Annotated[
        Optional[float],
        typer.Option(
            metavar="SECONDS",
            help="Stop after this long without a new packet (default: never).",
        ),
    ] = None,
) -> None:
    """Print packets as they are recorded (new ones by default)."""
    from rich.console import Console

    console = Console(highlight=False, soft_wrap=True)
    codes = set(code or [])
    direction = None
    if dir is not None:
        direction = TO_SERVER if dir is Direction.to_server else TO_CLIENT
    if not path.exists():
        typer.echo(f"waiting for {path} (Ctrl-C to stop)", err=True)
    packets = Capture.follow(
        path,
        from_end=not from_start,
        direction=direction,
        timeout=timeout,
    )
    try:
        for pkt in packets:
            if codes and pkt.code not in codes:
                continue
            header, body = _render(pkt, raw)
            style = "green" if pkt.direction == TO_SERVER else "cyan"
            console.print(header, style=style, markup=False)
            console.print(
                "\n".join("  " + line for line in body), markup=False, highlight=False
            )
    except KeyboardInterrupt:
        pass
    finally:
        packets.close()


@app.command()
def sessions(path: PathArg) -> None:
    """List the sessions in a capture."""
    if not path.exists():
        typer.echo(f"no such capture: {path}", err=True)
        raise typer.Exit(code=1)
    with Capture(path) as cap:
        counts = dict(
            cap.db.execute(
                "SELECT session, count(*) FROM packets GROUP BY session"
            ).fetchall()
        )
        rows = cap.sessions()
    typer.echo(f"{'id':>4}  {'started':<23}  {'packets':>8}  client -> upstream")
    for sid, started_ns, client, upstream in rows:
        started = datetime.fromtimestamp(started_ns / 1e9).strftime("%Y-%m-%d %H:%M:%S")
        typer.echo(
            f"{sid:>4}  {started:<23}  {counts.get(sid, 0):>8}  "
            f"{client or '?'} -> {upstream or '?'}"
        )
