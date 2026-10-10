"""The `main.py` typer application: root callback plus every command group."""

from __future__ import annotations

import sys
from dataclasses import replace

import typer
from typing import Annotated

from src.bot.cli import app as bot_app
from src.capture.cli import app as capture_app
from src.cli.local import local, start_local
from src.cli.options import (
    CommonOptions,
    IpOpt,
    ListenOpt,
    MaxPlayersOpt,
    RegionOpt,
    TimeoutOpt,
    VerboseOpt,
)
from src.cli.proxy import proxy
from src.cli.wizard import interactive
from src.logs import default_log_level
from src.protocol.net_keys import set_raw

app = typer.Typer(
    help="Prison Architect multiplayer server.",
    rich_markup_mode="rich",
    no_args_is_help=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)
app.add_typer(bot_app, name="bot")
app.add_typer(capture_app, name="capture")
app.command()(local)
app.command()(proxy)


@app.callback(invoke_without_command=True)
def cli(
    ctx: typer.Context,
    verbose: VerboseOpt = None,
    listen: ListenOpt = None,
    ip: IpOpt = None,
    timeout: TimeoutOpt = None,
    region: RegionOpt = None,
    max_players: MaxPlayersOpt = None,
    raw_keys: Annotated[
        bool,
        typer.Option(
            "--raw-keys",
            envvar="PA_RAW_KEYS",
            help="Show snapshot keys as the game sends them (st, ci, ts...) "
            "instead of their long names.",
        ),
    ] = False,
) -> None:
    """Prison Architect multiplayer server.

    Run without a command in a terminal for an interactive setup wizard.
    """
    set_raw(raw_keys)
    if verbose is not None:
        verbose = verbose.value
    ctx.obj = replace(
        CommonOptions(verbose=default_log_level()),
        **{
            k: v
            for k, v in dict(
                verbose=verbose,
                listen=listen,
                ip=ip,
                timeout=timeout,
                region=region,
                max_players=max_players,
            ).items()
            if v is not None
        },
    )
    if ctx.invoked_subcommand is not None:
        return
    if sys.stdin.isatty() and sys.stdout.isatty():
        interactive(ctx.obj)
    else:
        # Non-interactive with no command: run the local server.
        start_local(ctx.obj)
