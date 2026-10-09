"""Interactive Prison Architect bot: pick a region, a game, then send RPCs.

``python main.py bot`` connects to Photon, lists regions, lobbies and games, joins the
chosen game and opens a menu (game speed, incoming events, ...).

Debugging: ``--log-file PATH`` writes the bot's steps (and, at ``-v debug``, every
event and ping) to a file; the console stays the TUI. ``-o PATH`` (``--record``)
saves every packet the bot sends and receives, decrypted, into a capture file that
``python main.py capture tail PATH`` reads.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from enum import Enum
from os import environ
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from src.bot.actions import Context, menu
from src.bot.flow import join_flow, pick
from src.bot.formatting import format_region
from src.bot.session import (
    APP_VERSION,
    CLAUDE_ORANGE,
    Options,
    Session,
    fetch_regions,
)
from src.capture import Recorder
from src.env import ENV_PATH, load_env
from src.logs import LOG_LEVELS, default_log_level, setup_logging

LogLevel = Enum("LogLevel", {n: n for n in LOG_LEVELS}, type=str)
console = Console()
log = logging.getLogger(__name__)

app = typer.Typer(help=__doc__, invoke_without_command=True, no_args_is_help=False)


@app.callback()
def main(
    ctx: typer.Context,
    region: Annotated[
        str | None, typer.Option(help="Region code; skips the picker.")
    ] = None,
    app_id: Annotated[
        str | None,
        typer.Option(help="Photon App ID (env or .env: PHOTON_APP_ID)."),
    ] = None,
    app_version: Annotated[str, typer.Option(help="Photon AppVersion.")] = APP_VERSION,
    name_server: Annotated[
        str | None,
        typer.Option(
            help="Name Server host[:port], or 'auto' (resolve ns.exitgames.com over "
            "DNS-over-HTTPS) (env: PHOTON_NAME_SERVER). Needed when the hosts file "
            "points the name at 127.0.0.1 (the local proxy)."
        ),
    ] = None,
    speed_index: Annotated[
        bool,
        typer.Option(help="Send the stop index (0-4) instead of the multiplier."),
    ] = False,
    full_events: Annotated[
        bool, typer.Option(help="Show full DirectoryData events.")
    ] = False,
    name: Annotated[str, typer.Option(help="Actor name shown in the game.")] = "Claude",
    colour: Annotated[
        str, typer.Option(help="Actor colour, RRGGBB hex.")
    ] = CLAUDE_ORANGE,
    log_file: Annotated[
        Path | None,
        typer.Option(
            help="Append the bot's log to this file (nothing is logged to the "
            "console). Without it, logging is not configured."
        ),
    ] = None,
    log_level: Annotated[
        LogLevel | None,
        typer.Option(
            "-v",
            "--verbose",
            case_sensitive=False,
            help="Log level for --log-file. debug adds every event and ping.",
            show_default="$LOG_LEVEL or info",
        ),
    ] = None,
    record: Annotated[
        Path | None,
        typer.Option(
            "-o",
            "--record",
            help="Record every packet the bot sends and receives (decrypted) into "
            "this capture file, for `capture tail` and `capture sessions`.",
        ),
    ] = None,
) -> None:
    """Prison Architect bot (no subcommand: interactive)."""
    load_env(ENV_PATH)
    if log_file is not None:
        setup_logging(
            log_level.value if log_level else default_log_level(),
            log_file=log_file,
            console=False,
        )
    app_id = app_id or environ.get("PHOTON_APP_ID", "")
    opts = Options(
        app_id=app_id,
        app_version=app_version,
        name_server=name_server or environ.get("PHOTON_NAME_SERVER", ""),
        region=region,
        speed_index=speed_index,
        full_events=full_events,
        name=name,
        colour=colour,
        record=record,
    )
    ctx.obj = opts
    if ctx.invoked_subcommand is None:
        require_app_id(opts)
        run(opts)


def require_app_id(opts: Options) -> None:
    """Fail with a clear message when no Photon App ID is configured."""
    if not opts.app_id:
        raise typer.BadParameter(
            "PHOTON_APP_ID is not set; use --app-id or put it in .env "
            "(the game's id is src.server.server.PRISON_ARCHITECT_APP_ID)."
        )


@contextmanager
def recording(opts: Options) -> Iterator[Recorder | None]:
    """A :class:`Recorder` for ``opts.record`` (closed on exit), or None."""
    if opts.record is None:
        yield None
        return
    opts.record.parent.mkdir(parents=True, exist_ok=True)
    with Recorder(opts.record) as recorder:
        log.info("recording the bot's traffic to %s", opts.record)
        yield recorder


@app.command()
def regions(ctx: typer.Context) -> None:
    """List the Photon regions (read-only)."""
    require_app_id(ctx.obj)
    with recording(ctx.obj) as recorder:
        for code, address in fetch_regions(ctx.obj, recorder).items():
            console.print(format_region(code, address), markup=False)


def run(opts: Options) -> None:
    """The interactive flow: region, lobby, game, menu."""
    session: Session | None = None
    with recording(opts) as recorder:
        try:
            region = opts.region
            if region is None:
                found = fetch_regions(opts, recorder)
                region = pick(
                    "Region", [(format_region(c, a), c) for c, a in found.items()]
                )
            log.info("region: %s", region)
            session = join_flow(opts, region, recorder)
            menu(Context(session, opts))
        except KeyboardInterrupt:
            log.info("interrupted by the user")
            console.print("\nInterrupted, disconnecting.")
        except Exception:
            log.exception("bot stopped with an error")
            raise
        finally:
            if session is not None:
                session.stop()
