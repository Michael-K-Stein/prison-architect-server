"""Text output for packets: the header line and body lines the proxy shows."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from src.capture.schema import TO_SERVER

if TYPE_CHECKING:
    from src.capture.reader import Packet


def _stamp(ts_ns: int) -> str:
    return datetime.fromtimestamp(ts_ns / 1e9).strftime("%H:%M:%S.%f")[:-3]


def _render(pkt: Packet, raw: bool) -> tuple[str, list[str]]:
    """Header line and body lines for one packet, as the proxy shows them."""
    arrow = "client -> server" if pkt.direction == TO_SERVER else "server -> client"
    header = f"#{pkt.id}  {_stamp(pkt.ts_ns)}  session {pkt.session}  {arrow}"
    body: list[str] = []
    show_hex = raw or pkt.command is None
    if pkt.command is None:
        body.append(f"{pkt.name} ({pkt.size} bytes)")
    elif raw:
        body.append(pkt.name)
    else:
        # Lazy: needs the game protocol modules.
        from src.protocol.events import log_lines

        try:
            body = log_lines(pkt.operation())
        except Exception as exc:  # show the packet anyway, as hex
            body = [pkt.name, f"(could not decode: {exc})"]
            show_hex = True
    if show_hex:
        body.append(f"payload: {pkt.payload.hex()}")
    return header, body
