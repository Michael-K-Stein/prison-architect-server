"""`proxy`: forward traffic to a Photon server, logging every packet both ways."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated, Optional

import typer

from src.cli.options import (
    IpOpt,
    ListenOpt,
    VerboseOpt,
    CommonOptions,
    merge_common,
)
from src.logs import setup_logging
from src.server.upstream import NAME_SERVER_PORT, resolve_upstream


DIRECTORY_DATA = 9

RECORD_HELP = "show or change the capture file (record off stops)"


def start_proxy(
    opts: CommonOptions,
    upstream: Optional[str],
    port: int,
    follow: bool = True,
    record: Optional[Path] = None,
    hide: Optional[list[str]] = None,
    compact: bool = False,
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

    from src.capture.recorder import SwitchableRecorder
    from src.cli.console import (
        Command,
        CommandTable,
        ConsolePane,
        loglevel_command,
        run_console,
    )
    from src.cli.attach import GameTracker
    from src.cli.balance import BalanceOverride
    from src.cli.inject_commands import inject_commands
    from src.cli.packet_view import PlainPacket, packet_view
    from pyphotonrealtime.realtime._convert import to_param

    from src.protocol.events import (
        event_payload,
        compact_lines,
        is_hidden,
        log_lines,
        packet_label,
    )

    setup_logging(opts.verbose)
    pane = ConsolePane("Prison Architect proxy")
    pane.install_logging()  # startup lines go into the pane too

    stack = ExitStack()
    recorder = stack.enter_context(SwitchableRecorder(record))
    if record is not None:
        logging.info("Recording traffic to %s", record)
    hops: dict[tuple[str, int], int] = {}
    proxies: list = []  # every PhotonProxy (the tunnel and each followed hop)
    balance = BalanceOverride()
    tracker = GameTracker(lambda s: any(s in p.sessions for p in proxies))

    def local_port_for(address: str) -> str:
        """Proxy ``address`` (a Master/Game Server) and return our own."""
        host, _, raw_port = address.rpartition(":")
        target = (host, int(raw_port))
        if target not in hops:
            hop = stack.enter_context(
                PhotonProxy(target, opts.listen, 0, on_packet=on_packet)
            )
            proxies.append(hop)
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
        # Before the address rewrite: keep what the real server said.
        packet_id = recorder.record(session, direction, packet)
        tracker.observe(session, direction, packet)
        if isinstance(packet, PhotonOperationPacket):
            injected = False
            if direction == Direction.ToClient and override_balance(session, packet):
                # The client sees our number; record that copy next to the real one.
                packet_id = recorder.record(session, direction, packet, injected=True)
                injected = True
            if follow and direction == Direction.ToClient:
                hijack_addresses(packet)
            return show(packet_id, direction, packet, injected)
        return packet

    def override_balance(session, packet) -> bool:
        """Rewrite a Finance/World snapshot for the overridden client; True if changed."""
        event = event_payload(packet)
        if event is None or event[0] != DIRECTORY_DATA:
            return False
        data = balance.rewrite(session, event[1])
        if data is None:
            return False
        packet.get_payload().params[ParameterKey.Data] = to_param(data)
        return True

    def show(packet_id, direction, packet, injected=False):
        if isinstance(packet, PhotonOperationPacket):
            if not injected and hide and is_hidden(packet_label(packet), hide):
                return packet
            to_server = direction == Direction.ToServer
            lines = compact_lines(packet) if compact else [packet_label(packet)]
            view = packet_view(
                packet_id,
                to_server,
                lines,
                detail=lambda: log_lines(packet),  # rendered when expanded
                expanded=not compact,
                injected=injected,
            )
            # The text is for plain terminals and files; the pane draws ``view``.
            plain = PlainPacket(packet_id, to_server, lines, packet, compact, injected)
            logging.info("%s", plain, extra={"pane": view})
        return packet

    with (
        stack,
        PhotonProxy(
            resolve_upstream(upstream), opts.listen, port, on_packet=on_packet
        ) as tunnel,
    ):
        proxies.append(tunnel)
        logging.info(
            "Proxying %s:%d -> %s:%d", opts.listen, tunnel.port, *tunnel.upstream
        )

        def record_command(args: list[str]) -> str:
            if not args:
                if recorder.path is None:
                    return "not recording (record PATH starts a capture)"
                return f"recording to {recorder.path}"
            if args == ["off"]:
                recorder.close()
                return "recording stopped"
            if len(args) != 1:
                raise ValueError("expected one path or off")
            recorder.open(args[0])
            logging.info("Recording traffic to %s", recorder.path)
            return f"recording to {recorder.path}"

        commands = CommandTable(
            {
                "record": Command("record [PATH|off]", RECORD_HELP, record_command),
                "loglevel": loglevel_command(),
                **inject_commands(tracker, balance, recorder.record, show),
            }
        )
        pane.attached = lambda: (tracker.status(), tracker.current() is not None)

        run_console(commands, pane=pane)
        print("\nShutting down servers...")


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
            "SQLite database for offline analysis (see `main.py capture`). An "
            "existing file is appended to.",
            dir_okay=False,
        ),
    ] = None,
    hide: Annotated[
        Optional[list[str]],
        typer.Option(
            "--hide",
            help="Don't print packets whose label starts with this (repeatable), "
            "e.g. RaiseEvent:SystemState:World or RaiseEvent:SystemState. "
            "Labels are OPERATION[:EVENT[:SYSTEM]]. Hidden packets are still "
            "forwarded and recorded.",
        ),
    ] = None,
    compact: Annotated[
        bool,
        typer.Option(
            "--compact",
            help="Log each packet on as few lines as possible.",
        ),
    ] = False,
    verbose: VerboseOpt = None,
    listen: ListenOpt = None,
    ip: IpOpt = None,
) -> None:
    """Proxy traffic to a Photon server, logging every packet both ways."""
    opts = merge_common(ctx, verbose=verbose, listen=listen, ip=ip)
    start_proxy(opts, upstream, port, follow, record, hide, compact)
