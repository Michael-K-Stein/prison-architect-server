"""Interactive Prison Architect bot: pick a region, a game, then send RPCs.

``python main.py bot`` connects to Photon, lists regions, lobbies and games, joins the
chosen game and opens a menu (game speed, incoming events, ...).
"""

from __future__ import annotations

from os import environ
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
from src.env import ENV_PATH, load_env

console = Console()

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
    verbose: Annotated[
        bool, typer.Option(help="Show full DirectoryData events.")
    ] = False,
    name: Annotated[str, typer.Option(help="Actor name shown in the game.")] = "Claude",
    colour: Annotated[
        str, typer.Option(help="Actor colour, RRGGBB hex.")
    ] = CLAUDE_ORANGE,
) -> None:
    """Prison Architect bot (no subcommand: interactive)."""
    load_env(ENV_PATH)
    app_id = app_id or environ.get("PHOTON_APP_ID", "")
    opts = Options(
        app_id,
        app_version,
        name_server or environ.get("PHOTON_NAME_SERVER", ""),
        region,
        speed_index,
        verbose,
        name,
        colour,
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


@app.command()
def regions(ctx: typer.Context) -> None:
    """List the Photon regions (read-only)."""
    require_app_id(ctx.obj)
    for code, address in fetch_regions(ctx.obj).items():
        console.print(format_region(code, address), markup=False)


def run(opts: Options) -> None:
    """The interactive flow: region, lobby, game, menu."""
    session: Session | None = None
    try:
        region = opts.region
        if region is None:
            found = fetch_regions(opts)
            region = pick(
                "Region", [(format_region(c, a), c) for c, a in found.items()]
            )
        session = join_flow(opts, region)
        menu(Context(session, opts))
    except KeyboardInterrupt:
        console.print("\nInterrupted, disconnecting.")
    finally:
        if session is not None:
            session.stop()
