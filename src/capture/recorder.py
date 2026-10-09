"""Writing a capture: the proxy's packet hook, and a background writer thread."""

from __future__ import annotations

import logging
import queue
import sqlite3
import threading
import time
import weakref
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pyphotonrealtime.protocol.packet.operation_packet import PhotonOperationPacket
from pyphotonrealtime.protocol.serialization_protocol import SerializationProtocol
from pyphotonrealtime.protocol.serializer import serialize_photon_payload
from pyphotonrealtime.server import Direction

from src.capture.schema import FORMAT_VERSION, SCHEMA, TO_CLIENT, TO_SERVER

if TYPE_CHECKING:
    from types import TracebackType

    from pyphotonrealtime.protocol.packet.base import PhotonPacket
    from pyphotonrealtime.server import ProxySession

log = logging.getLogger(__name__)

_BATCH = 512
"""Most rows per commit. A commit also happens whenever the queue runs empty."""
_STOP = object()


def _peer(sock: Any) -> str:
    try:
        host, port = sock.getpeername()[:2]
    except (OSError, ValueError):
        return ""
    return f"{host}:{port}"


class Recorder:
    """Writes every packet the proxy sees into a capture file.

    Use :meth:`on_packet` (or call it from your own hook) as, or inside, the
    proxy's ``on_packet``. It never alters the packet and never blocks on
    the disk: rows are queued and written in batches by a background thread.
    Call :meth:`close` (or use ``with``) to flush. An existing file is
    appended to.

    The file is in WAL mode. Each batch is one transaction, committed as soon
    as the queue has been drained (or after ``_BATCH`` rows), so another
    process reading the file sees a packet within milliseconds of it being
    recorded, and never sees part of a packet.
    """

    def __init__(self, path: str | Path) -> None:
        """Open (creating if needed) the capture at ``path``."""
        self.path = path
        self.dropped = 0
        """Packets that could not be recorded (serialization failures)."""
        self._queue: queue.SimpleQueue[Any] = queue.SimpleQueue()
        self._sessions: weakref.WeakKeyDictionary[Any, int] = (
            weakref.WeakKeyDictionary()
        )
        self._lock = threading.Lock()
        self._closed = False

        db = sqlite3.connect(path, check_same_thread=False)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=NORMAL")
        db.executescript(SCHEMA)
        row = db.execute("SELECT value FROM meta WHERE key='format'").fetchone()
        if row is None:
            db.executemany(
                "INSERT INTO meta VALUES (?, ?)",
                [("format", FORMAT_VERSION), ("created_ns", time.time_ns())],
            )
        elif row[0] != FORMAT_VERSION:
            db.close()
            msg = f"{path}: capture format {row[0]}, expected {FORMAT_VERSION}"
            raise ValueError(msg)
        db.commit()
        last = db.execute("SELECT max(id) FROM sessions").fetchone()[0]
        self._next_session = (last or 0) + 1

        self._db = db
        self._thread = threading.Thread(
            target=self._write_loop, name="CaptureWriter", daemon=True
        )
        self._thread.start()

    def on_packet(
        self, session: ProxySession, direction: Direction, packet: PhotonPacket
    ) -> PhotonPacket:
        """Record ``packet`` and return it unchanged (a ``PacketHook``)."""
        if self._closed:
            self.dropped += 1
            log.warning("packet arrived after the capture was closed; not recorded")
            return packet
        now = time.time_ns()
        try:
            row = self._row(session, direction, packet, now)
        except Exception:  # never let recording break the proxied connection
            self.dropped += 1
            log.exception("could not record a packet; skipped")
            return packet
        self._queue.put(("packet", row))
        return packet

    def _session_id(self, session: ProxySession, now: int) -> int:
        with self._lock:
            known = self._sessions.get(session)
            if known is not None:
                return known
            known = self._next_session
            self._next_session += 1
            self._sessions[session] = known
        self._queue.put(
            ("session", (known, now, _peer(session.client), _peer(session.server)))
        )
        return known

    def _row(
        self,
        session: ProxySession,
        direction: Direction,
        packet: PhotonPacket,
        now: int,
    ) -> tuple[Any, ...]:
        sid = self._session_id(session, now)
        wire_dir = TO_SERVER if direction == Direction.ToServer else TO_CLIENT
        # The protocol a stream is parsed with, which is what its payloads need.
        parser = (
            session.client_parser if wire_dir == TO_SERVER else session.server_parser
        )
        protocol = int(parser.protocol)
        command = code = return_code = None
        encrypted = 0
        if isinstance(packet, PhotonOperationPacket):
            header = packet.get_header()
            payload = packet.get_payload()
            command = int(header.get_command_code())
            code = int(payload.operation_code)
            encrypted = int(header.is_encrypted())
            return_code = payload.get_return_code()
            # Not payload.serialize(): that caches its result, which would go
            # stale if a hook then rewrites the params (the address hijack).
            body = serialize_photon_payload(
                payload.operation_code,
                payload.params,
                payload.response_debug_data,
                header=header,
                protocol=SerializationProtocol(protocol),
            )
        else:
            body = packet.serialize()
        return (
            now,
            sid,
            wire_dir,
            command,
            int(packet.get_format()),
            code,
            encrypted,
            protocol,
            return_code,
            len(body),
            body,
        )

    def _write_loop(self) -> None:
        stop = False
        while not stop:
            batch = [self._queue.get()]
            while len(batch) < _BATCH:
                try:
                    batch.append(self._queue.get_nowait())
                except queue.Empty:
                    break
            sessions, packets = [], []
            for item in batch:
                if item is _STOP:
                    stop = True
                elif item[0] == "session":
                    sessions.append(item[1])
                else:
                    packets.append(item[1])
            try:
                with self._db:
                    self._db.executemany(
                        "INSERT INTO sessions VALUES (?,?,?,?)", sessions
                    )
                    self._db.executemany(
                        "INSERT INTO packets (ts_ns, session, dir, command, format,"
                        " code, encrypted, protocol, return_code, size, payload)"
                        " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        packets,
                    )
            except sqlite3.Error:
                self.dropped += len(packets)
                log.exception("capture write failed; %d packets lost", len(packets))

    def close(self) -> None:
        """Write everything queued and close the file (idempotent)."""
        if self._closed:
            return
        self._closed = True
        if self._thread.is_alive():
            self._queue.put(_STOP)  # FIFO: everything queued before it is written
            self._thread.join()
        self._db.close()

    def __enter__(self) -> Recorder:
        """Return the recorder."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Flush and close."""
        self.close()
