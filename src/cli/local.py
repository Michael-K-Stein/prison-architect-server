"""`local`: run the Prison Architect server on this machine."""

from __future__ import annotations

import logging
from ipaddress import ip_address
from typing import Annotated, Optional

import typer

from src.cli.options import (
    CommonOptions,
    IpOpt,
    ListenOpt,
    MaxPlayersOpt,
    RegionOpt,
    TimeoutOpt,
    VerboseOpt,
    merge_common,
)
from src.cli.console import (
    Command,
    CommandTable,
    ConsolePane,
    loglevel_command,
    run_console,
)
from src.logs import setup_logging
from src.server.server import PrisonArchitectServer
from src.server.upstream import resolve_upstream


NEW_SPEECH = 117
"""RPC ``NewSpeechAdded(int adviser, string text)``."""


def say_command(server: PrisonArchitectServer) -> Command:
    """``say [host] SPEAKER MESSAGE``: an adviser speaks to every room's players."""
    from pyphotonrealtime.server import Role

    from src.bot.broadcast import speaker_index

    def run(args: list[str]) -> str:
        to = "all"
        if args[:1] == ["host"]:
            to, args = "host", args[1:]
        if len(args) < 2:
            raise ValueError("expected a speaker and a message")
        game = server.handlers[Role.GameServer]
        sent = game.inject_event(  # type: ignore[attr-defined]
            NEW_SPEECH, speaker_index(args[0]), " ".join(args[1:]), to=to
        )
        return f"sent to {sent} player(s)"

    return Command("say [host] SPEAKER TEXT", "an adviser speaks in the game", run)


def capacity_command(server: PrisonArchitectServer) -> Command:
    """``capacity [N]``: show or set how many players a room takes (default 4)."""
    from pyphotonrealtime.server import Role

    def run(args: list[str]) -> str:
        game = server.handlers[Role.GameServer]
        if not args:
            return f"room capacity: {game.max_players}"  # type: ignore[attr-defined]
        try:
            count = int(args[0])
        except ValueError:
            raise ValueError("capacity must be a whole number") from None
        rooms = game.set_capacity(count)  # type: ignore[attr-defined]
        return f"room capacity {count} (new rooms and {rooms} existing)"

    return Command("capacity [N]", "show or set the players per room", run)


def start_local(opts: CommonOptions, upstream: Optional[str] = None) -> None:
    if not 1 <= opts.max_players <= 16:
        raise typer.BadParameter("max_players must be between 1 and 16")
    if opts.timeout < 3:
        raise typer.BadParameter("timeout must be >= 3 seconds")
    ip_address(opts.listen)
    ip_address(opts.ip)
    setup_logging(opts.verbose)
    pane = ConsolePane("Prison Architect server")
    pane.install_logging()  # startup lines go into the pane too
    passthrough = resolve_upstream(upstream)
    server = PrisonArchitectServer(
        opts.listen,
        public_host=opts.ip,
        region=opts.region,
        max_players=opts.max_players,
        upstream=passthrough,
        # The old in-repo server's hard limit: generous, so loading screens
        # and short network stalls don't drop players.
        idle_timeout=max(opts.timeout * 4, 120),
    )
    with server:
        logging.info(
            "Prison Architect server up: name server on %s:%d, region %r; "
            "other Photon games relayed to %s:%d",
            opts.listen,
            server.name_server_port,
            opts.region,
            *passthrough,
        )
        run_console(
            CommandTable(
                {
                    "loglevel": loglevel_command(),
                    "say": say_command(server),
                    "capacity": capacity_command(server),
                }
            ),
            pane=pane,
        )
        print("\nShutting down servers...")


def local(
    ctx: typer.Context,
    upstream: Annotated[
        Optional[str],
        typer.Option(
            "--upstream",
            help="Upstream Photon name server (host or host:port) that "
            "non-Prison Architect clients are transparently proxied to. "
            "If omitted, the current IP of ns.exitgames.com is resolved "
            "automatically.",
        ),
    ] = None,
    verbose: VerboseOpt = None,
    listen: ListenOpt = None,
    ip: IpOpt = None,
    timeout: TimeoutOpt = None,
    region: RegionOpt = None,
    max_players: MaxPlayersOpt = None,
) -> None:
    """Run server locally."""
    opts = merge_common(
        ctx,
        verbose=verbose,
        listen=listen,
        ip=ip,
        timeout=timeout,
        region=region,
        max_players=max_players,
    )
    start_local(opts, upstream)
