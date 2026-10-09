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

from prison_architect import (
    NAME_SERVER_PORT,
    PrisonArchitectServer,
    resolve_upstream,
)

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


def _setup_logging(opts: CommonOptions) -> None:
    logging.basicConfig(
        level=opts.verbose.upper(),
        format="%(message)s",
        datefmt="%H:%M:%S",
        handlers=[RichHandler(markup=False, rich_tracebacks=True)],
    )


def _serve_forever() -> None:
    try:
        while True:
            sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down servers...")


def _start_local(opts: CommonOptions, upstream: Optional[str] = None) -> None:
    if not 1 <= opts.max_players <= 16:
        raise typer.BadParameter("max_players must be between 1 and 16")
    if opts.timeout < 3:
        raise typer.BadParameter("timeout must be >= 3 seconds")
    ip_address(opts.listen)
    ip_address(opts.ip)
    _setup_logging(opts)
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
        _serve_forever()


def _start_proxy(
    opts: CommonOptions,
    upstream: Optional[str],
    port: int,
    follow: bool = True,
    record: Optional[Path] = None,
) -> None:
    # Imported here: only the proxy command needs them.
    from contextlib import ExitStack

    from pyphotonrealtime.protocol.packet.operation_packet import (
        PhotonOperationPacket,
    )
    from pyphotonrealtime.protocol.param.parameter_key import ParameterKey
    from pyphotonrealtime.protocol.param.slice_param import SliceParameter
    from pyphotonrealtime.protocol.param.string_param import StringParameter
    from pyphotonrealtime.server import Direction, PhotonProxy

    from pa_events import log_lines

    _setup_logging(opts)

    stack = ExitStack()
    recorder = None
    if record is not None:
        from capture import Recorder

        record.parent.mkdir(parents=True, exist_ok=True)
        recorder = stack.enter_context(Recorder(record))
        logging.info("Recording traffic to %s", record)
    hops: dict[tuple[str, int], int] = {}

    def local_port_for(address: str) -> str:
        """Proxy ``address`` (a Master/Game Server) and return our own."""
        host, _, raw_port = address.rpartition(":")
        target = (host, int(raw_port))
        if target not in hops:
            hop = stack.enter_context(
                PhotonProxy(target, opts.listen, 0, on_packet=on_packet)
            )
            hops[target] = hop.port
            logging.info(
                "Proxying %s:%d -> %s:%d", opts.listen, hop.port, host, target[1]
            )
        return f"{opts.ip}:{hops[target]}"

    def hijack_addresses(packet: PhotonOperationPacket) -> None:
        # Name/Master/Game Server addresses travel in responses; point them
        # at ourselves so the client's next hop is proxied too.
        params = packet.get_payload().params
        value = params.get(ParameterKey.Address)
        if isinstance(value, StringParameter) and value.value:
            params[ParameterKey.Address] = StringParameter(local_port_for(value.value))
        elif isinstance(value, SliceParameter):
            value.value[:] = [
                StringParameter(local_port_for(a.value)) if a.value else a
                for a in value.value
            ]

    def on_packet(session, direction, packet):
        if recorder is not None:
            # Before the address rewrite: keep what the real server said.
            recorder.on_packet(session, direction, packet)
        if isinstance(packet, PhotonOperationPacket):
            if follow and direction == Direction.ToClient:
                hijack_addresses(packet)
            return show(session, direction, packet)
        return packet

    def show(_session, direction, packet):
        if isinstance(packet, PhotonOperationPacket):
            arrow = (
                "client -> server"
                if direction == Direction.ToServer
                else "server -> client"
            )
            logging.info("%s\n  %s", arrow, "\n  ".join(log_lines(packet)))
        return packet

    with (
        stack,
        PhotonProxy(
            resolve_upstream(upstream), opts.listen, port, on_packet=on_packet
        ) as tunnel,
    ):
        logging.info(
            "Proxying %s:%d -> %s:%d", opts.listen, tunnel.port, *tunnel.upstream
        )
        _serve_forever()


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
        _start_local(ctx.obj)


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
    port: Annotated[
        int, typer.Option("-p", "--port", help="Port to listen on.")
    ] = NAME_SERVER_PORT,
    upstream: Annotated[
        Optional[str],
        typer.Option(
            "-u",
            "--upstream",
            help="Server to proxy (host or host:port). If omitted, the real "
            "Photon name server.",
        ),
    ] = None,
    follow: Annotated[
        bool,
        typer.Option(
            "--follow/--no-follow",
            help="Also proxy the Master and Game Server traffic, by rewriting "
            "the addresses in the server's responses to point at this proxy "
            "(so --ip must be reachable by the client). Use --no-follow to "
            "proxy only the name server.",
        ),
    ] = True,
    record: Annotated[
        Optional[Path],
        typer.Option(
            "-o",
            "--record",
            help="Also save every packet (decrypted) to this capture file, a "
            "SQLite database for offline analysis (see capture.py). An "
            "existing file is appended to.",
            dir_okay=False,
        ),
    ] = None,
    verbose: VerboseOpt = None,
    listen: ListenOpt = None,
    ip: IpOpt = None,
) -> None:
    """Proxy traffic to a Photon server, logging every packet both ways."""
    opts = _merge_common(ctx, verbose=verbose, listen=listen, ip=ip)
    _start_proxy(opts, upstream, port, follow, record)


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
        timeout=ask_int("Keep-alive timeout (seconds):", defaults.timeout),
        region=inquirer.text(message="Region name:", default=defaults.region).execute(),
        max_players=ask_int("Max players per room:", defaults.max_players),
    )
    _print_equivalent(opts)
    _start_local(opts)


def _print_equivalent(opts: CommonOptions) -> None:
    flags = {
        "verbose": "-v",
        "listen": "-l",
        "ip": "-i",
        "timeout": "--timeout",
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
