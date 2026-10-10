"""Recording the bot's own traffic: a transport wrapper that feeds a :class:`Recorder`.

``RealtimeClient`` writes and reads TCP-framed bytes through its peer's transport.
:class:`RecordingTransport` wraps that transport, parses the same bytes into
packets (one parser per direction, like the proxy does) and hands each packet to
the recorder. It never changes what is sent or received. Each ``connect`` starts a
new capture session, so the Name, Master and Game Server hops are separate
sessions, as they are for the proxy.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from pyphotonrealtime.protocol.packet.packet_stream import PhotonStreamParser
from pyphotonrealtime.protocol.serialization_protocol import SerializationProtocol
from pyphotonrealtime.server import Direction

if TYPE_CHECKING:
    from pyphotonrealtime.peer import PhotonPeer

    from src.capture import Recorder

log = logging.getLogger(__name__)

LOCAL_NAME = "bot"


class _Endpoint:
    """Just enough of a socket for ``Recorder`` to name an address."""

    def __init__(self, host: str, port: int) -> None:
        self.address = (host, port)

    def getpeername(self) -> tuple[str, int]:
        """The address, as ``socket.getpeername`` would report it."""
        return self.address


class BotSession:
    """One connection of the bot: the attributes ``Recorder`` reads from a ProxySession.

    ``client_parser`` parses what the bot sends, ``server_parser`` what it receives.
    """

    def __init__(self, host: str, port: int, protocol: SerializationProtocol) -> None:
        """A session to ``host:port`` whose payloads use ``protocol``."""
        self.client = _Endpoint(LOCAL_NAME, 0)
        self.server = _Endpoint(host, port)
        self.client_parser = PhotonStreamParser(protocol)
        self.server_parser = PhotonStreamParser(protocol)


class RecordingTransport:
    """Wraps a peer's transport; records every packet sent and received through it.

    Attribute reads and writes that are not ours go to the wrapped transport, so
    the peer cannot tell the difference (``path``, ``secure``, ``connected``, ...).
    """

    def __init__(self, inner: Any, recorder: Recorder, peer: PhotonPeer) -> None:
        """Wrap ``inner``; ``peer`` supplies the protocol and the AES key."""
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "_recorder", recorder)
        object.__setattr__(self, "_peer", peer)
        object.__setattr__(self, "_session", None)

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(self._inner, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name.startswith("_"):
            object.__setattr__(self, name, value)
        else:
            setattr(self._inner, name, value)

    def connect(self, host: str, port: int, timeout: float) -> None:
        """Connect, then start a new capture session for this hop."""
        self._inner.connect(host, port, timeout)
        protocol = self._peer.serialization_protocol
        self._session = BotSession(host, port, protocol)
        log.info("recording session to %s:%d", host, port)

    def send(self, data: bytes) -> None:
        """Send ``data`` and record the packets in it."""
        self._inner.send(data)
        self._record(Direction.ToServer, data)

    def receive(self) -> bytes:
        """Return what the server sent and record the packets in it."""
        data = self._inner.receive()
        if data:
            self._record(Direction.ToClient, data)
        return data

    def _record(self, direction: Direction, data: bytes) -> None:
        session = self._session
        if session is None:
            return
        if direction == Direction.ToServer:
            parser, expect_responses = session.client_parser, False
        else:
            parser, expect_responses = session.server_parser, True
        parser.feed(data)
        try:
            # The peer's AES key is private; the parser needs it to decrypt
            # encrypted operations, and it is None until the key exchange is done.
            key = getattr(self._peer, "_aes_key", None)
            for packet in parser.parse(expect_responses=expect_responses, aes_key=key):
                self._recorder.on_packet(session, direction, packet)
        except (ValueError, TypeError):
            log.exception("could not parse traffic for recording; dropping it")
            parser.buffer.clear()


def record_traffic(peer: PhotonPeer, recorder: Recorder) -> None:
    """Make ``peer`` record its traffic into ``recorder`` (call before connecting)."""
    peer.transport = RecordingTransport(peer.transport, recorder, peer)


__all__ = ["BotSession", "RecordingTransport", "record_traffic"]
