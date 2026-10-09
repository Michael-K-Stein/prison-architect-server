"""Record proxied Photon traffic to a file, read it back, or watch it live.

A capture is a SQLite database (stdlib only, any language can open it, and
every column worth filtering on is indexed). Record once against the real
servers, then analyze the file as often as you like.

Tables (all integers unless noted):

``meta(key, value)``
    ``format`` (schema version), ``created_ns``.
``sessions(id, started_ns, client TEXT, upstream TEXT)``
    One row per client connection through a proxy hop.
``packets(id, ts_ns, session, dir, command, format, code, encrypted,
protocol, return_code, size, payload BLOB)``
    One row per packet, in arrival order (``id``). ``dir`` is 0 for
    client -> server and 1 for server -> client. ``command`` is the
    ``CommandCode`` and ``code`` the operation or event code (NULL for
    packets without one, such as keep-alives). ``payload`` is the *plaintext*
    body: encrypted operations are already decrypted. For operations,
    responses and events it is the serialized payload (starting at the
    operation code byte); for anything else, the whole packet.
    Addresses are recorded as the real server sent them, before the proxy
    rewrites them.

Reading, e.g. in an ad-hoc script::

    from capture import Capture

    with Capture("captures/run1.sqlite") as cap:
        for pkt in cap.packets(direction=0, code=226):
            print(pkt.ts_ns, pkt.name, pkt.decode().params)

or straight SQL: ``cap.db.execute("SELECT code, count(*) FROM packets GROUP
BY code")``.

Live: a capture being recorded can be read by another process while it is
written (WAL mode; rows are committed within milliseconds). Use
:meth:`Capture.follow` to iterate over new packets as they arrive, or from the
shell::

    python capture.py tail captures/run1.sqlite [--from-start] [--code N ...]
    python capture.py sessions captures/run1.sqlite
"""

from __future__ import annotations

import argparse
import logging
import queue
import sqlite3
import sys
import threading
import time
import weakref
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pyphotonrealtime.protocol.command_code import CommandCode
from pyphotonrealtime.protocol.deserializer import deserialize_photon_payload
from pyphotonrealtime.protocol.enum_lookups import (
    get_command_name,
    get_event_name,
    get_operation_name,
)
from pyphotonrealtime.protocol.packet.header import PhotonDataPacketHeader
from pyphotonrealtime.protocol.packet.operation_packet import PhotonOperationPacket
from pyphotonrealtime.protocol.packet.operation_payload import PhotonPacketPayload
from pyphotonrealtime.protocol.serialization_protocol import SerializationProtocol
from pyphotonrealtime.protocol.serializer import serialize_photon_payload
from pyphotonrealtime.server import Direction

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator
    from types import TracebackType

    from pyphotonrealtime.protocol.packet.base import PhotonPacket
    from pyphotonrealtime.server import ProxySession

log = logging.getLogger(__name__)

FORMAT_VERSION = 1
TO_SERVER, TO_CLIENT = 0, 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY,
    started_ns INTEGER NOT NULL,
    client TEXT,
    upstream TEXT
);
CREATE TABLE IF NOT EXISTS packets (
    id INTEGER PRIMARY KEY,
    ts_ns INTEGER NOT NULL,
    session INTEGER NOT NULL,
    dir INTEGER NOT NULL,
    command INTEGER,
    format INTEGER NOT NULL,
    code INTEGER,
    encrypted INTEGER NOT NULL,
    protocol INTEGER NOT NULL,
    return_code INTEGER,
    size INTEGER NOT NULL,
    payload BLOB
);
CREATE INDEX IF NOT EXISTS packets_session ON packets (session, id);
CREATE INDEX IF NOT EXISTS packets_code ON packets (command, code, id);
"""

_BATCH = 512
"""Most rows per commit. A commit also happens whenever the queue runs empty."""
_STOP = object()
_BUSY_MS = 5000
"""How long a reader waits for a lock before giving up on one query."""
_TRANSIENT = ("locked", "busy", "unable to open", "no such table", "disk i/o error")
"""Errors a reader retries: the file is being created, or briefly locked."""


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
        db.executescript(_SCHEMA)
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


@dataclass(frozen=True)
class Decoded:
    """A packet's payload, parsed."""

    operation_code: int
    params: dict[Any, Any]
    """Parameter key -> typed parameter (``.value`` holds the Python value)."""
    debug: tuple[int, Any] | None
    """``(return code, debug message)`` of a response, else None."""


@dataclass(frozen=True)
class Packet:
    """One recorded packet (a row of ``packets``)."""

    id: int
    ts_ns: int
    session: int
    direction: int
    """0: client -> server, 1: server -> client."""
    command: int | None
    format: int
    code: int | None
    encrypted: bool
    protocol: int
    return_code: int | None
    size: int
    payload: bytes

    @property
    def is_operation(self) -> bool:
        """Whether this is an operation, response or event (has a code)."""
        return self.command is not None

    @property
    def is_event(self) -> bool:
        """Whether this is an event."""
        return self.command in (CommandCode.Event, CommandCode.EncryptedEvent)

    @property
    def name(self) -> str:
        """Readable command and operation/event name."""
        if self.command is None:
            return f"format 0x{self.format:02x}"
        command = get_command_name(CommandCode(self.command))
        lookup = get_event_name if self.is_event else get_operation_name
        return f"{command}: {lookup(self.code)}"

    def decode(self) -> Decoded:
        """Parse the payload (operations, responses and events only)."""
        if self.command is None:
            msg = "only operations, responses and events have a parsed payload"
            raise ValueError(msg)
        header = PhotonDataPacketHeader(command_code=CommandCode(self.command))
        code, params, debug = deserialize_photon_payload(
            header, self.payload, SerializationProtocol(self.protocol)
        )
        return Decoded(int(code), params, debug)

    def operation(self) -> PhotonOperationPacket:
        """Rebuild the packet as the proxy saw it, for ``log_lines`` and friends.

        Only for operations, responses and events. The payload is already the
        plaintext, so the header's encryption flag does not matter here.
        """
        if self.command is None:
            msg = "only operations, responses and events can be rebuilt"
            raise ValueError(msg)
        header = PhotonDataPacketHeader(command_code=CommandCode(self.command))
        payload = PhotonPacketPayload.from_bytes(
            header, self.payload, SerializationProtocol(self.protocol)
        )
        return PhotonOperationPacket(header, payload)


_COLUMNS = (
    "id, ts_ns, session, dir, command, format, code, encrypted, protocol,"
    " return_code, size, payload"
)


def _filters(
    session: int | None,
    direction: int | Direction | None,
    command: int | None,
    code: int | None,
    where: str,
    params: tuple[Any, ...],
) -> tuple[list[str], list[Any]]:
    """SQL clauses and arguments for the filters shared by packets() and follow()."""
    if isinstance(direction, Direction):
        direction = TO_SERVER if direction == Direction.ToServer else TO_CLIENT
    clauses: list[str] = []
    args: list[Any] = []
    for column, value in (
        ("session", session),
        ("dir", direction),
        ("command", command),
        ("code", code),
    ):
        if value is not None:
            clauses.append(f"{column} = ?")
            args.append(value)
    if where:
        clauses.append(f"({where})")
        args.extend(params)
    return clauses, args


def _ro_uri(path: str | Path) -> str:
    return Path(path).absolute().as_uri() + "?mode=ro"


def _connect(path: str | Path) -> sqlite3.Connection | None:
    """A read-only connection to ``path``, or None if it cannot be opened yet."""
    if not Path(path).exists():
        return None
    try:
        return sqlite3.connect(_ro_uri(path), uri=True, timeout=_BUSY_MS / 1000)
    except sqlite3.OperationalError:
        return None


def _transient(exc: sqlite3.OperationalError) -> bool:
    text = str(exc).lower()
    return any(word in text for word in _TRANSIENT)


def _stop_requested(stop: threading.Event | Callable[[], bool] | None) -> bool:
    if stop is None:
        return False
    if isinstance(stop, threading.Event):
        return stop.is_set()
    return bool(stop())


class Capture:
    """Read-only access to a capture file."""

    def __init__(self, path: str | Path) -> None:
        """Open ``path`` for reading."""
        self.db = sqlite3.connect(_ro_uri(path), uri=True)

    def packets(
        self,
        *,
        session: int | None = None,
        direction: int | Direction | None = None,
        command: int | None = None,
        code: int | None = None,
        where: str = "",
        params: tuple[Any, ...] = (),
    ) -> Iterator[Packet]:
        """Iterate packets in arrival order, optionally filtered.

        ``where`` is extra SQL (e.g. ``"size > ?"``) with ``params``.
        """
        clauses, args = _filters(session, direction, command, code, where, params)
        sql = f"SELECT {_COLUMNS} FROM packets"  # noqa: S608 -- fixed columns
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        for row in self.db.execute(sql + " ORDER BY id", args):
            yield Packet(*row[:7], bool(row[7]), *row[8:])

    @classmethod
    def follow(
        cls,
        path: str | Path,
        *,
        after: int = 0,
        from_end: bool = False,
        session: int | None = None,
        direction: int | Direction | None = None,
        command: int | None = None,
        code: int | None = None,
        where: str = "",
        params: tuple[Any, ...] = (),
        stop: threading.Event | Callable[[], bool] | None = None,
        timeout: float | None = None,
        poll: float = 0.1,
    ) -> Iterator[Packet]:
        """Yield packets as they are recorded to ``path``, in arrival order.

        Works on a capture that is still being written. Starts after packet
        id ``after`` (default 0: from the beginning), or with ``from_end=True``
        at the packets that exist when the reader first looks. Filters are
        those of :meth:`packets`.

        Waits for the file to appear. Ends when ``stop`` (an Event, or a
        callable returning true) is set, or after ``timeout`` seconds with no
        new packet (and no file). ``timeout=None`` waits forever. Busy or
        half-created files are retried, not raised.
        """
        if from_end and after:
            msg = "pass either after or from_end, not both"
            raise ValueError(msg)
        clauses, args = _filters(session, direction, command, code, where, params)
        sql = (
            f"SELECT {_COLUMNS} FROM packets WHERE "  # noqa: S608 -- fixed columns
            + " AND ".join(["id > ?", *clauses])
            + " ORDER BY id LIMIT 500"
        )
        cursor: int | None = None if from_end else after
        db: sqlite3.Connection | None = None
        idle_since = time.monotonic()
        try:
            while not _stop_requested(stop):
                if db is None:
                    db = _connect(path)
                rows: list[tuple[Any, ...]] = []
                if db is not None:
                    try:
                        if cursor is None:
                            cursor = db.execute(
                                "SELECT COALESCE(MAX(id), 0) FROM packets"
                            ).fetchone()[0]
                        rows = db.execute(sql, (cursor, *args)).fetchall()
                    except sqlite3.OperationalError as exc:
                        if not _transient(exc):
                            raise
                        db.close()
                        db = None
                if rows:
                    idle_since = time.monotonic()
                    for row in rows:
                        cursor = row[0]
                        yield Packet(*row[:7], bool(row[7]), *row[8:])
                    continue
                if timeout is not None and time.monotonic() - idle_since >= timeout:
                    return
                if isinstance(stop, threading.Event):
                    stop.wait(poll)
                else:
                    time.sleep(poll)
        finally:
            if db is not None:
                db.close()

    def sessions(self) -> list[tuple[int, int, str, str]]:
        """Return ``(id, started_ns, client, upstream)`` for every session."""
        return self.db.execute(
            "SELECT id, started_ns, client, upstream FROM sessions ORDER BY id"
        ).fetchall()

    def close(self) -> None:
        """Close the file."""
        self.db.close()

    def __enter__(self) -> Capture:
        """Return the capture."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Close the file."""
        self.close()


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
        from pa_events import log_lines  # lazy: needs the game protocol modules

        try:
            body = log_lines(pkt.operation())
        except Exception as exc:  # show the packet anyway, as hex
            body = [pkt.name, f"(could not decode: {exc})"]
            show_hex = True
    if show_hex:
        body.append(f"payload: {pkt.payload.hex()}")
    return header, body


def _tail(args: argparse.Namespace) -> int:
    from rich.console import Console

    console = Console(highlight=False, soft_wrap=True)
    codes = set(args.code or [])
    direction = {"to-server": TO_SERVER, "to-client": TO_CLIENT}.get(args.dir)
    if not args.path.exists():
        print(f"waiting for {args.path} (Ctrl-C to stop)", file=sys.stderr)
    packets = Capture.follow(
        args.path,
        from_end=not args.from_start,
        direction=direction,
        timeout=args.timeout,
    )
    try:
        for pkt in packets:
            if codes and pkt.code not in codes:
                continue
            header, body = _render(pkt, args.raw)
            style = "green" if pkt.direction == TO_SERVER else "cyan"
            console.print(header, style=style, markup=False)
            console.print(
                "\n".join("  " + line for line in body), markup=False, highlight=False
            )
    except KeyboardInterrupt:
        pass
    finally:
        packets.close()
    return 0


def _sessions(args: argparse.Namespace) -> int:
    if not args.path.exists():
        print(f"no such capture: {args.path}", file=sys.stderr)
        return 1
    with Capture(args.path) as cap:
        counts = dict(
            cap.db.execute(
                "SELECT session, count(*) FROM packets GROUP BY session"
            ).fetchall()
        )
        sessions = cap.sessions()
    print(f"{'id':>4}  {'started':<23}  {'packets':>8}  client -> upstream")
    for sid, started_ns, client, upstream in sessions:
        started = datetime.fromtimestamp(started_ns / 1e9).strftime("%Y-%m-%d %H:%M:%S")
        print(
            f"{sid:>4}  {started:<23}  {counts.get(sid, 0):>8}  "
            f"{client or '?'} -> {upstream or '?'}"
        )
    return 0


def main(argv: Iterable[str] | None = None) -> int:
    """Command line: ``tail`` a capture live, or list its ``sessions``."""
    parser = argparse.ArgumentParser(
        description="Read a capture recorded by `main.py proxy --record`."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    tail = commands.add_parser(
        "tail",
        help="print packets as they are recorded (new ones by default)",
    )
    tail.add_argument("path", type=Path, help="capture file (.sqlite)")
    tail.add_argument(
        "--from-start",
        action="store_true",
        help="print the whole capture first, then new packets",
    )
    tail.add_argument(
        "--code",
        type=int,
        nargs="+",
        action="extend",
        metavar="N",
        help="only operations/events with these codes (repeatable)",
    )
    tail.add_argument(
        "--dir",
        choices=["to-server", "to-client"],
        help="only packets in one direction",
    )
    tail.add_argument(
        "--raw",
        action="store_true",
        help="print names and hex payloads instead of decoded parameters",
    )
    tail.add_argument(
        "--timeout",
        type=float,
        metavar="SECONDS",
        help="stop after this long without a new packet (default: never)",
    )
    tail.set_defaults(run=_tail)

    sessions = commands.add_parser("sessions", help="list the sessions in a capture")
    sessions.add_argument("path", type=Path, help="capture file (.sqlite)")
    sessions.set_defaults(run=_sessions)

    args = parser.parse_args(argv)
    try:
        return args.run(args)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
