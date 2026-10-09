import logging
import sys
from dataclasses import dataclass, fields, replace
from enum import Enum
from ipaddress import ip_address
from os import environ
from pathlib import Path
from time import sleep
from typing import Annotated, Optional

import typer
from rich.logging import RichHandler

from prison_architect import PrisonArchitectServer

LOG_LEVELS = ("debug", "info", "warning", "error", "critical")


def _load_dotenv(dotenv_path: Path) -> None:
    if not dotenv_path.exists():
        return

    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")

        if key == "":
            continue

        if key not in environ:
            environ[key] = value


def _resolve_log_level_default() -> str:
    log_level = environ.get("LOG_LEVEL", "info").strip().lower()
    return log_level if log_level in LOG_LEVELS else "info"


@dataclass
class CommonOptions:
    verbose: str
    listen: str = "0.0.0.0"
    ip: str = "127.0.0.1"
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
# Still accepted so existing Docker/Pterodactyl start commands keep working,
# but ignored: pyPhotonRealtime's server has no keep-alive timeout setting.
TimeoutOpt = Annotated[Optional[int], typer.Option("--timeout", hidden=True)]
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

app = typer.Typer(
    help="Prison Architect multiplayer server.",
    rich_markup_mode="rich",
    no_args_is_help=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)


def _merge_common(ctx: typer.Context, **overrides) -> CommonOptions:
    base: CommonOptions = ctx.obj
    given = {k: v for k, v in overrides.items() if v is not None}
    if isinstance(given.get("verbose"), Enum):
        given["verbose"] = given["verbose"].value
    return replace(base, **given)


def _start_local(opts: CommonOptions) -> None:
    if not 1 <= opts.max_players <= 16:
        raise typer.BadParameter("max_players must be between 1 and 16")
    ip_address(opts.listen)
    ip_address(opts.ip)
    logging.basicConfig(
        level=opts.verbose.upper(),
        format="%(message)s",
        datefmt="%H:%M:%S",
        handlers=[RichHandler(markup=False, rich_tracebacks=True)],
    )
    server = PrisonArchitectServer(
        opts.listen,
        public_host=opts.ip,
        region=opts.region,
        max_players=opts.max_players,
    )
    with server:
        logging.info(
            "Prison Architect server up: name server on %s:%d, region %r",
            opts.listen,
            server.name_server_port,
            opts.region,
        )
        try:
            while True:
                sleep(1)
        except KeyboardInterrupt:
            print("\nShutting down servers...")


@app.callback(invoke_without_command=True)
def cli(
    ctx: typer.Context,
    verbose: VerboseOpt = None,
    listen: ListenOpt = None,
    ip: IpOpt = None,
    timeout: TimeoutOpt = None,
    region: RegionOpt = None,
    max_players: MaxPlayersOpt = None,
) -> None:
    """Prison Architect multiplayer server.

    Run without a command in a terminal for an interactive setup wizard.
    """
    if verbose is not None:
        verbose = verbose.value
    ctx.obj = replace(
        CommonOptions(verbose=_resolve_log_level_default()),
        **{
            k: v
            for k, v in dict(
                verbose=verbose,
                listen=listen,
                ip=ip,
                region=region,
                max_players=max_players,
            ).items()
            if v is not None
        },
    )
    if ctx.invoked_subcommand is not None:
        return
    if sys.stdin.isatty() and sys.stdout.isatty():
        _interactive(ctx.obj)
    else:
        # Non-interactive with no command: run the local server.
        _start_local(ctx.obj)


@app.command()
def local(
    ctx: typer.Context,
    verbose: VerboseOpt = None,
    listen: ListenOpt = None,
    ip: IpOpt = None,
    timeout: TimeoutOpt = None,
    region: RegionOpt = None,
    max_players: MaxPlayersOpt = None,
) -> None:
    """Run server locally."""
    opts = _merge_common(
        ctx,
        verbose=verbose,
        listen=listen,
        ip=ip,
        region=region,
        max_players=max_players,
    )
    _start_local(opts)


def _interactive(defaults: CommonOptions) -> None:
    # Imported lazily: only needed for the wizard, and keeps --help snappy.
    from InquirerPy import inquirer
    from InquirerPy.validator import NumberValidator

    typer.secho("Prison Architect server setup", fg=typer.colors.CYAN, bold=True)
    opts = CommonOptions(
        verbose=inquirer.select(
            message="Log level:", choices=list(LOG_LEVELS), default=defaults.verbose
        ).execute(),
        listen=inquirer.text(
            message="Listen address:", default=defaults.listen
        ).execute(),
        ip=inquirer.text(
            message="Redirect IP (127.0.0.1 or your public IP):", default=defaults.ip
        ).execute(),
        region=inquirer.text(message="Region name:", default=defaults.region).execute(),
        max_players=int(
            inquirer.text(
                message="Max players per room:",
                default=str(defaults.max_players),
                validate=NumberValidator(message="Enter a whole number"),
            ).execute()
        ),
    )
    _print_equivalent(opts)
    _start_local(opts)


def _print_equivalent(opts: CommonOptions) -> None:
    flags = {
        "verbose": "-v",
        "listen": "-l",
        "ip": "-i",
        "region": "-r",
        "max_players": "--max-players",
    }
    args = ["local"]
    for f in fields(opts):
        args += [flags[f.name], str(getattr(opts, f.name))]
    typer.secho(
        "Equivalent command: python main.py " + " ".join(args),
        fg=typer.colors.BRIGHT_BLACK,
    )


if __name__ == "__main__":
    _load_dotenv(Path(__file__).resolve().parent / ".env")
    app(prog_name="main.py")
