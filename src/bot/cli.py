"""Interactive Prison Architect bot: pick a region, a game, then send RPCs.

``python main.py bot`` connects to Photon, lists regions, lobbies and games, joins the
chosen game and opens a live HUD: game state, and every known action.

Debugging: ``--log-file PATH`` writes the bot's steps (and, at ``-v debug``, every
event and ping) to a file; the console stays the TUI. ``-o PATH`` (``--record``)
saves every packet the bot sends and receives, decrypted, into a capture file that
``python main.py capture tail PATH`` reads.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from enum import Enum
from os import environ
from pathlib import Path
from typing import Annotated
from urllib.parse import quote

import typer
from rich.console import Console

from src.bot.control import DEFAULT_PORT, ControlServer, call
from src.bot.flow import join_flow, join_room, pick
from src.bot.formatting import format_region
from src.bot.hud import run_hud
from src.bot.session import (
    APP_VERSION,
    CLAUDE_ORANGE,
    ConnectError,
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
            run_hud(session, opts)
        except KeyboardInterrupt:
            log.info("interrupted by the user")
            console.print("\nInterrupted, disconnecting.")
        except ConnectError as exc:
            log.error("bot stopped: %s", exc)
            console.print(f"[red]Error:[/red] {exc}", markup=True, highlight=False)
            raise typer.Exit(1) from None
        except Exception:
            log.exception("bot stopped with an error")
            raise
        finally:
            if session is not None:
                session.stop()


@app.command()
def serve(
    ctx: typer.Context,
    room: Annotated[
        str | None, typer.Option(help="Game (room) name; default: the first open one.")
    ] = None,
    port: Annotated[int, typer.Option(help="Control server port.")] = DEFAULT_PORT,
) -> None:
    """Join a game headless and serve the JSON control API (see `bot ctl`)."""
    opts: Options = ctx.obj
    require_app_id(opts)
    if opts.region is None:
        raise typer.BadParameter(
            "serve needs a region: pass --region before `serve` "
            "(`bot regions` lists them)."
        )
    session: Session | None = None
    server: ControlServer | None = None
    with recording(opts) as recorder:
        try:
            session = join_room(opts, opts.region, room, recorder)
            server = ControlServer(session, port)
            server.start()
            console.print(f"control server: {server.url}", markup=False)
            reason = server.wait()
            log.info("serve stopped: %s", reason)
            if reason == "disconnected":
                console.print(f"Disconnected: {session.disconnected}", markup=False)
        except KeyboardInterrupt:
            log.info("interrupted by the user")
            console.print("\nInterrupted, disconnecting.")
        except ConnectError as exc:
            log.error("bot stopped: %s", exc)
            console.print(f"[red]Error:[/red] {exc}", markup=True, highlight=False)
            raise typer.Exit(1) from None
        finally:
            if server is not None:
                server.stop()
            if session is not None:
                session.stop()


ctl = typer.Typer(help="Talk to a running `bot serve` (prints JSON).")
app.add_typer(ctl, name="ctl")


@ctl.callback()
def ctl_main(
    ctx: typer.Context,
    port: Annotated[int, typer.Option(help="Control server port.")] = DEFAULT_PORT,
) -> None:
    """Client for the control server on 127.0.0.1."""
    ctx.obj = port


def _show(ctx: typer.Context, method: str, path: str, body: dict | None = None) -> None:
    try:
        status, data = call(method, path, body, port=ctx.obj)
    except OSError as exc:
        typer.echo(json.dumps({"error": f"no control server: {exc}"}, indent=1))
        raise typer.Exit(1) from None
    typer.echo(json.dumps(data, indent=1))
    if status >= 400:
        raise typer.Exit(1)


@ctl.command("state")
def ctl_state(
    ctx: typer.Context,
    system: Annotated[str | None, typer.Argument(help="System, e.g. World.")] = None,
    path: Annotated[str | None, typer.Argument(help="Child path, a/b.")] = None,
    depth: Annotated[int, typer.Option(help="Child levels (-1: all).")] = -1,
) -> None:
    """The game state summary, or one system/node."""
    if system is None:
        _show(ctx, "GET", "/state")
        return
    node = "/".join(x.strip("/") for x in (system, path or "") if x.strip("/"))
    _show(ctx, "GET", f"/state/{quote(node)}?depth={depth}")


@ctl.command("actions")
def ctl_actions(
    ctx: typer.Context,
    kind: Annotated[
        str | None, typer.Option(help="player, host or handshake (default: all).")
    ] = None,
    show_all: Annotated[
        bool, typer.Option("--all", help="Include blocked actions.")
    ] = False,
) -> None:
    """The RPC actions and their arguments."""
    query = f"?all={int(show_all)}" + (f"&kind={quote(kind)}" if kind else "")
    _show(ctx, "GET", "/actions" + query)


@ctl.command("send")
def ctl_send(
    ctx: typer.Context,
    action: Annotated[str, typer.Argument(help="Action name or RPC code.")],
    args: Annotated[list[str] | None, typer.Argument(help="Arguments as text.")] = None,
) -> None:
    """Send one RPC."""
    _show(ctx, "POST", "/send", {"action": action, "args": args or []})


@ctl.command("events")
def ctl_events(
    ctx: typer.Context,
    since: Annotated[int, typer.Option(help="Only events after this seq.")] = 0,
    limit: Annotated[int, typer.Option(help="At most this many.")] = 100,
) -> None:
    """Numbered notable game events."""
    _show(ctx, "GET", f"/events?since={since}&limit={limit}")


@ctl.command("wait")
def ctl_wait(
    ctx: typer.Context,
    seconds: Annotated[float, typer.Argument(help="Seconds (max 30).")],
) -> None:
    """Let game time pass, then print the state."""
    _show(ctx, "POST", "/wait", {"seconds": seconds})


@ctl.command("quit")
def ctl_quit(ctx: typer.Context) -> None:
    """Disconnect the bot and stop the server."""
    _show(ctx, "POST", "/quit", {})
