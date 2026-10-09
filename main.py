import sys
from dataclasses import dataclass, fields, replace
from os import environ
from pathlib import Path
from typing import Annotated, Optional

from enum import Enum

import typer

from server.consts import NAMESERVER_IP, NAMESERVER_PORT, ServerType
from server import run_local_server
from server.log import Verbosity
from server.proxy_servers.server import run_proxy
from server.settings import Settings


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
    log_level = environ.get("LOG_LEVEL", "Info").strip()
    by_lower = {name.lower(): name for name in Verbosity._member_names_}
    return by_lower.get(log_level.lower(), "Info")


@dataclass
class CommonOptions:
    verbose: str
    listen: str = "0.0.0.0"
    ip: str = "127.0.0.1"
    timeout: int = 60
    region: str = "local"
    max_players: int = 4


LogLevel = Enum(
    "LogLevel", {n.lower(): n.lower() for n in Verbosity._member_names_}, type=str
)
ServerTypeChoice = Enum(
    "ServerTypeChoice", {n: n for n in ServerType._member_names_}, type=str
)


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
        help="Grace period between client keep alives before closing sockets.",
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


def _apply_settings(opts: CommonOptions, upstream: Optional[str]) -> None:
    Settings().set(
        listen_host=opts.listen,
        verbosity=Verbosity[opts.verbose.capitalize()],
        ip=opts.ip,
        timeout=opts.timeout,
        region_name=opts.region,
        max_players=opts.max_players,
        upstream=upstream,
    )


def _start_local(opts: CommonOptions, upstream: Optional[str]) -> None:
    _apply_settings(opts, upstream)
    run_local_server()


def _start_proxy(
    opts: CommonOptions, upstream: str, port: int, server_type: ServerType
) -> None:
    # The proxy's -u/--upstream is the proxied server, not the `local`
    # passthrough upstream, so it is not stored in Settings.
    _apply_settings(opts, None)
    run_proxy(upstream, port, server_type)


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
        CommonOptions(verbose=_resolve_log_level_default().lower()),
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
        _interactive(ctx.obj)
    else:
        # Non-interactive with no command: run the local server.
        _start_local(ctx.obj, None)


@app.command()
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
    opts = _merge_common(
        ctx,
        verbose=verbose,
        listen=listen,
        ip=ip,
        timeout=timeout,
        region=region,
        max_players=max_players,
    )
    _start_local(opts, upstream)


@app.command()
def proxy(
    ctx: typer.Context,
    server_type: Annotated[
        ServerTypeChoice,
        typer.Option(
            "-t",
            "--type",
            help="Which server to proxy.",
        ),
    ],
    port: Annotated[int, typer.Option("-p", "--port")] = NAMESERVER_PORT,
    upstream: Annotated[str, typer.Option("-u", "--upstream")] = NAMESERVER_IP,
    verbose: VerboseOpt = None,
    listen: ListenOpt = None,
    ip: IpOpt = None,
    timeout: TimeoutOpt = None,
    region: RegionOpt = None,
    max_players: MaxPlayersOpt = None,
) -> None:
    """Proxy traffic, allowing reading and injecting packets."""
    opts = _merge_common(
        ctx,
        verbose=verbose,
        listen=listen,
        ip=ip,
        timeout=timeout,
        region=region,
        max_players=max_players,
    )
    _start_proxy(opts, upstream, port, ServerType[server_type.value])


def _interactive(defaults: CommonOptions) -> None:
    # Imported lazily: only needed for the wizard, and keeps --help snappy.
    from InquirerPy import inquirer
    from InquirerPy.validator import NumberValidator

    def ask_int(message: str, default: int) -> int:
        return int(
            inquirer.text(
                message=message,
                default=str(default),
                validate=NumberValidator(message="Enter a whole number"),
            ).execute()
        )

    typer.secho("Prison Architect server setup", fg=typer.colors.CYAN, bold=True)
    mode = inquirer.select(
        message="Mode:",
        choices=[
            {"name": "Local server", "value": "local"},
            {"name": "Proxy (read / inject packets)", "value": "proxy"},
        ],
        default="local",
    ).execute()

    opts = CommonOptions(
        verbose=inquirer.select(
            message="Log level:",
            choices=[name.lower() for name in Verbosity._member_names_],
            default=defaults.verbose,
        ).execute(),
        listen=inquirer.text(
            message="Listen address:", default=defaults.listen
        ).execute(),
        ip=inquirer.text(
            message="Redirect IP (127.0.0.1 or your public IP):", default=defaults.ip
        ).execute(),
        timeout=ask_int("Keep-alive timeout (seconds):", defaults.timeout),
        region=inquirer.text(message="Region name:", default=defaults.region).execute(),
        max_players=ask_int("Max players per room:", defaults.max_players),
    )

    if mode == "local":
        upstream = inquirer.text(
            message="Upstream name server (blank = auto-resolve ns.exitgames.com):",
            default="",
        ).execute()
        _print_equivalent(
            opts, ["local"] + (["--upstream", upstream] if upstream else [])
        )
        _start_local(opts, upstream or None)
    else:
        server_type = inquirer.select(
            message="Server type to proxy:", choices=ServerType._member_names_
        ).execute()
        upstream = inquirer.text(
            message="Upstream address:", default=NAMESERVER_IP
        ).execute()
        port = ask_int("Port:", NAMESERVER_PORT)
        _print_equivalent(
            opts, ["proxy", "-t", server_type, "-u", upstream, "-p", str(port)]
        )
        _start_proxy(opts, upstream, port, ServerType[server_type])


def _print_equivalent(opts: CommonOptions, command: list[str]) -> None:
    flags = {
        "verbose": "-v",
        "listen": "-l",
        "ip": "-i",
        "timeout": "--timeout",
        "region": "-r",
        "max_players": "--max-players",
    }
    args = list(command)
    for f in fields(opts):
        args += [flags[f.name], str(getattr(opts, f.name))]
    typer.secho(
        "Equivalent command: python main.py " + " ".join(args),
        fg=typer.colors.BRIGHT_BLACK,
    )


if __name__ == "__main__":
    _load_dotenv(Path(__file__).resolve().parent / ".env")
    app(prog_name="main.py")
