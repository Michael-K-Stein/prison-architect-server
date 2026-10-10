"""Coloured pane rows for a packet: direction, capture id, and a styled summary."""

from __future__ import annotations

import re

from src.cli.frame import DIM
from src.cli.pane import DetailSource, PacketView, Row

INJECTED_STYLE = "bold fg:ansiblack bg:ansiyellow"
TO_SERVER = ("→ ", "bold fg:ansicyan")
TO_CLIENT = ("← ", "bold fg:ansimagenta")

_TOKEN = re.compile(
    r"""
    (?P<event>\bEvent\ \d+\ \w+)
  | (?P<system>\bDirectoryData:\w*)
  | (?P<op>\b(?:Operation|Request|Response|Event|Command):\w+)
  | (?P<dim>\[enc\])
  | (?P<key>[\w.\-]+)(?==)
  | (?P<text>'[^']*'|"[^"]*")
  | (?P<plus>(?<![\w.])\+\d[\d.]*)
  | (?P<minus>(?<![\w.])-\d[\d.]*)
  | (?P<num>(?<![\w.])\d+(?:\.\d+)?(?![\w.]))
    """,
    re.VERBOSE,
)

_STYLES = {
    "event": "bold fg:ansiyellow",
    "system": "bold fg:ansiblue",
    "op": "bold",
    "dim": DIM,
    "key": "fg:ansicyan",
    "text": "fg:ansigreen",
    "plus": "fg:ansigreen",
    "minus": "fg:ansired",
    "num": "fg:ansibrightyellow",
}


def style_summary(text: str) -> Row:
    """``text`` split into styled pieces: names bold, ``key=`` cyan, signs green/red."""
    row: Row = []
    last = 0
    for match in _TOKEN.finditer(text):
        if match.start() > last:
            row.append(("", text[last : match.start()]))
        row.append((_STYLES[match.lastgroup or ""], match.group()))
        last = match.end()
    if last < len(text):
        row.append(("", text[last:]))
    return row


def packet_view(
    packet_id: int | None,
    to_server: bool,
    lines: list[str],
    detail: DetailSource | None = None,
    expanded: bool = False,
    injected: bool = False,
) -> PacketView:
    """Rows for one packet: an arrow and id, then ``lines`` styled.

    ``detail`` (the full dump) is shown when the entry is expanded.
    """
    arrow, style = TO_SERVER if to_server else TO_CLIENT
    tag = f"#{packet_id} " if packet_id is not None else ""
    mark: Row = [(INJECTED_STYLE, "[injected] ")] if injected else []
    head: list[Row] = [[(style, arrow), (DIM, tag), *mark, *style_summary(lines[0])]]
    pad = " " * (len(arrow) + len(tag) + sum(len(t) for _, t in mark))
    head.extend([("", pad), *style_summary(line)] for line in lines[1:])
    return PacketView(head, detail, expanded)


class PlainPacket:
    """A packet as plain log text, built only if a handler formats it."""

    def __init__(  # noqa: ANN001
        self, packet_id, to_server, lines, packet, compact, injected=False
    ) -> None:
        self.args = (packet_id, to_server, lines, packet, compact)
        self.injected = injected

    def __str__(self) -> str:
        from src.protocol.events import log_lines

        packet_id, to_server, lines, packet, compact = self.args
        mark = "[injected] " if self.injected else ""
        if compact:
            arrow = "->" if to_server else "<-"
            tag = f"#{packet_id} " if packet_id is not None else ""
            return f"{tag}{arrow} {mark}" + "\n  ".join(lines)
        arrow = "client -> server" if to_server else "server -> client"
        tag = f"#{packet_id}  " if packet_id is not None else ""
        return f"{tag}{arrow} {mark}\n  " + "\n  ".join(log_lines(packet))
