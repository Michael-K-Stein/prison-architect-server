"""The join handshake: ask the host for the save game and reassemble it.

From the binary (journal2 "Join handshake and composite types"): the joiner
sends ``AuthoriseConnection(password)`` to the host; the host answers
``ProcessingStarted``, ``SendingSaveGame``, ``SetNumSaveDataChunks(count,
check)`` and then one ``SaveDataChunk`` at a time, each of which the joiner
acks with ``SaveDataChunkAck``. The joined chunks are a compressed save tree,
in the same format as a ``DirectoryData`` snapshot.
"""

from __future__ import annotations

import logging
import zlib
from collections.abc import Callable
from dataclasses import dataclass, field

from src.protocol import rpc
from src.protocol.snapshot import Node, decompress

log = logging.getLogger(__name__)

SET_NUM_CHUNKS = 1
CHUNK_ACK = 2
CHUNK = 3
PROCESSING_STARTED = 4
AUTHORISE = 5
KICKED = 6
INCORRECT_PASSWORD = 7
SENDING_SAVE = 8
HANDSHAKE_CODES = frozenset({1, 3, 4, 6, 7, 8})
"""Codes the host sends a joiner during the handshake."""


@dataclass
class SaveTransfer:
    """Receives the save game in chunks; ``send(code, data)`` reaches the host."""

    send: Callable[[int, bytes], object]
    status: str = "not requested"
    expected: int = 0
    chunks: list[bytes] = field(default_factory=list)
    tree: Node | None = None
    raw_size: int = 0

    def request(self, password: str = "") -> None:
        """Send ``AuthoriseConnection(password)``: the host then sends the save."""
        self.status = "requested"
        self.tree = None
        self.send(AUTHORISE, rpc.build(AUTHORISE, password))

    def on_event(self, code: int, data: object) -> str | None:
        """Handle a handshake event; returns a line worth showing, or None."""
        if code not in HANDSHAKE_CODES:
            return None
        payload = data if isinstance(data, bytes) else b""
        if code == PROCESSING_STARTED:
            self.status = "host preparing the save"
        elif code == SENDING_SAVE:
            self.status = "save transfer starting"
        elif code == KICKED:
            self.status = "kicked by the host"
        elif code == INCORRECT_PASSWORD:
            self.status = "incorrect password"
        elif code == SET_NUM_CHUNKS:
            count, _check = (v for _, v in rpc.parse(code, payload).args)
            self.expected, self.chunks = int(count), []
            self.status = f"receiving save: 0/{self.expected} chunks"
        elif code == CHUNK:
            ((_, chunk),) = rpc.parse(code, payload).args
            self.chunks.append(chunk if isinstance(chunk, bytes) else b"")
            self.send(CHUNK_ACK, rpc.build(CHUNK_ACK))
            self.status = f"receiving save: {len(self.chunks)}/{self.expected} chunks"
            if self.expected and len(self.chunks) >= self.expected:
                self._finish()
        return self.status

    def _finish(self) -> None:
        blob = b"".join(self.chunks)
        try:
            snapshot = decompress(blob)
        except (ValueError, zlib.error) as exc:
            self.status = f"save received ({len(blob)} B) but not readable: {exc}"
            log.warning("save game: %s", self.status)
            return
        self.tree, self.raw_size = snapshot.tree, len(snapshot.raw)
        self.status = f"save loaded ({len(blob)} B, {self.raw_size} B raw)"
        log.info("save game: %s", self.status)
