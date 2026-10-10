"""Reading a capture back, including one that is still being written.

Reading, e.g. in an ad-hoc script::

    from src.capture import Capture

    with Capture("captures/run1.sqlite") as cap:
        for pkt in cap.packets(direction=0, code=226):
            print(pkt.ts_ns, pkt.name, pkt.decode().params)

or straight SQL: ``cap.db.execute("SELECT code, count(*) FROM packets GROUP
BY code")``.

Live: a capture being recorded can be read by another process while it is
written (WAL mode; rows are committed within milliseconds). Use
:meth:`Capture.follow` to iterate over new packets as they arrive.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass
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
from pyphotonrealtime.server import Direction

from src.capture.schema import TO_CLIENT, TO_SERVER
from src.protocol.rpc import rpc_name

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from types import TracebackType

_BUSY_MS = 5000
"""How long a reader waits for a lock before giving up on one query."""
_TRANSIENT = ("locked", "busy", "unable to open", "no such table", "disk i/o error")
"""Errors a reader retries: the file is being created, or briefly locked."""


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
    injected: bool = False
    """True for a packet the proxy made up and sent (the console's ``say``)."""

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
        name = lookup(self.code)
        if self.is_event and name.startswith("UNKNOWN["):
            name = rpc_name(self.code)  # the game's RPC / DirectoryData / spawn codes
        return f"{command}: {name}"

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


def _columns(db: sqlite3.Connection) -> str:
    """``_COLUMNS`` plus ``injected`` (0 for captures made before that column)."""
    have = {r[1] for r in db.execute("PRAGMA table_info(packets)")}
    return _COLUMNS + (", injected" if "injected" in have else ", 0")


def _packet(row: tuple[Any, ...]) -> Packet:
    return Packet(*row[:7], bool(row[7]), *row[8:12], bool(row[12]))


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
        sql = f"SELECT {_columns(self.db)} FROM packets"  # noqa: S608 -- fixed columns
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        for row in self.db.execute(sql + " ORDER BY id", args):
            yield _packet(row)

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
        where_sql = " AND ".join(["id > ?", *clauses]) + " ORDER BY id LIMIT 500"
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
                        sql = (  # noqa: S608 -- fixed columns
                            f"SELECT {_columns(db)} FROM packets WHERE " + where_sql
                        )
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
                        yield _packet(row)
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
