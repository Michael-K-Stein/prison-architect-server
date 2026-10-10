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
from src.cli.console import CommandTable, ConsolePane, loglevel_command, run_console
from src.logs import setup_logging
from src.server.server import PrisonArchitectServer
from src.server.upstream import resolve_upstream


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
            CommandTable({"loglevel": loglevel_command()}),
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
