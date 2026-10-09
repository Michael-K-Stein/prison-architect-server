"""Options shared by every CLI command, and how they merge with subcommand values."""

from __future__ import annotations

import time
from dataclasses import dataclass, replace
from enum import Enum
from typing import Annotated, Optional

import typer

from src.logs import LOG_LEVELS


@dataclass
class CommonOptions:
    verbose: str
    listen: str = "0.0.0.0"
    ip: str = "127.0.0.1"
    timeout: int = 60
    region: str = "local"
    max_players: int = 4


LogLevel = Enum("LogLevel", {n: n for n in LOG_LEVELS}, type=str)


# Options shared by every command. They are accepted both before and after the
# subcommand name (e.g. both `main.py -l 0.0.0.0 local` and the README's
# `main.py local -l 0.0.0.0` work); a value given after the subcommand wins.
# Defaults are None so we can tell "not given" apart from "given the default".
VerboseOpt = Annotated[
    Optional[LogLevel],
    typer.Option(
        "-v",
        "--verbose",
        case_sensitive=False,
        help="Log level.",
        show_default="$LOG_LEVEL or info",
    ),
]
ListenOpt = Annotated[
    Optional[str],
    typer.Option(
        "-l", "--listen", help="IP address to bind to.", show_default="0.0.0.0"
    ),
]
IpOpt = Annotated[
    Optional[str],
    typer.Option(
        "-i",
        "--ip",
        help="IP to redirect to. This should either be 127.0.0.1 or your public IP.",
        show_default="127.0.0.1",
    ),
]
TimeoutOpt = Annotated[
    Optional[int],
    typer.Option(
        "--timeout",
        help="Grace period between client keep alives before closing sockets "
        "(silent clients are dropped after max(4x this, 120) seconds).",
        show_default="60",
    ),
]
RegionOpt = Annotated[
    Optional[str],
    typer.Option(
        "-r",
        "--region",
        help='The name shown in the "Region" selection box.',
        show_default="local",
    ),
]
MaxPlayersOpt = Annotated[
    Optional[int],
    typer.Option(
        "--max-players",
        help="Maximum players per game room (safe test range: 4-8).",
        show_default="4",
    ),
]


def merge_common(ctx: typer.Context, **overrides) -> CommonOptions:
    """The root callback's options, with non-None subcommand values applied on top."""
    base: CommonOptions = ctx.obj
    given = {k: v for k, v in overrides.items() if v is not None}
    if isinstance(given.get("verbose"), Enum):
        given["verbose"] = given["verbose"].value
    return replace(base, **given)


def serve_forever() -> None:
    """Block until Ctrl+C, then report shutdown."""
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down servers...")
