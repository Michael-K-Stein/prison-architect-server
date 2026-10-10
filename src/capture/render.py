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
    mark = "  [injected]" if pkt.injected else ""
    header = f"#{pkt.id}  {_stamp(pkt.ts_ns)}  session {pkt.session}  {arrow}{mark}"
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


class CompactView:
    """One-to-few lines per packet; the session shows only when it changes."""

    def __init__(self) -> None:
        self._session: int | None = None

    def render(self, pkt: Packet, raw: bool = False) -> list[str]:
        arrow = "->" if pkt.direction == TO_SERVER else "<-"
        sess = ""
        if pkt.session != self._session:
            self._session = pkt.session
            sess = f" s{pkt.session}"
        mark = "[injected] " if pkt.injected else ""
        prefix = f"#{pkt.id} {_stamp(pkt.ts_ns)}{sess} {arrow} {mark}"
        if pkt.command is None:
            lines = [f"{pkt.name} {pkt.size}B {pkt.payload.hex()}"]
        elif raw:
            lines = [f"{pkt.name} {pkt.payload.hex()}"]
        else:
            from src.protocol.events import compact_lines

            try:
                lines = compact_lines(pkt.operation())
            except Exception as exc:  # show the packet anyway, as hex
                lines = [f"{pkt.name} (could not decode: {exc}) {pkt.payload.hex()}"]
        return [prefix + lines[0], *("  " + line for line in lines[1:])]
