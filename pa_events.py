"""Prison Architect's own payloads inside Photon ``RaiseEvent`` / events.

The game sends everything through ``RaiseEvent`` with the event code in
``ParameterKey.Code`` (244) and a byte array in ``ParameterKey.Data`` (245).
That byte array is a list of tagged values (:func:`decode_args`):

* tag ``0x0N``: an integer in ``N - 1`` little-endian bytes (``0x00`` is 0);
* tag ``0x1N``: a byte string whose length is in ``N - 1`` little-endian
  bytes (``0x12`` = 1-byte length, ``0x13`` = 2-byte length).

Observed event codes:

* ``9`` -- a simulation system's state, ``[system name, snapshot]``. The
  snapshot is zlib-compressed and followed by the uncompressed size, written
  backwards (big-endian bytes, then their count + 1) so it can be read from
  the end. Uncompressed, it is a binary form of the save-file tree
  (:func:`decode_tree`).
* ``118`` -- ``[35, "finance_cost_cashflow", 0, 0]``: a cash-flow item of 35 added
  to the balance (the next ``Finance`` snapshot's ``v.6`` is ``tr.b + 35``).
  Sent at game start and once more mid-game; the other arguments are unknown.

Unknown tags or field types raise :class:`ValueError`; callers that only
display payloads should fall back to the raw bytes.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pyphotonrealtime.protocol.command_code import CommandCode
from pyphotonrealtime.protocol.enum_lookups import get_parameter_key_name
from pyphotonrealtime.protocol.operation_code import OperationCode
from pyphotonrealtime.protocol.param.int8_slice_param import Int8SliceParameter
from pyphotonrealtime.protocol.param.parameter_key import ParameterKey

if TYPE_CHECKING:
    from pyphotonrealtime.protocol.packet.operation_packet import (
        PhotonOperationPacket,
    )

CASHFLOW_EVENT = 118
EVENT_NAMES = {9: "SystemState", CASHFLOW_EVENT: "Cashflow"}
"""Names for event codes whose meaning is known (our own, not the game's)."""


@dataclass
class Node:
    """One ``BEGIN name ... END`` block of the save-file tree."""

    name: str
    fields: list[tuple[str, Any]] = field(default_factory=list)
    children: list[Node] = field(default_factory=list)


@dataclass
class Snapshot:
    """A decompressed blob, parsed when it is a tree."""

    compressed_size: int
    raw: bytes
    tree: Node | None


class _Reader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0

    def take(self, n: int) -> bytes:
        if self.pos + n > len(self.data):
            msg = f"truncated at {self.pos} (wanted {n} bytes)"
            raise ValueError(msg)
        chunk = self.data[self.pos : self.pos + n]
        self.pos += n
        return chunk

    def u8(self) -> int:
        return self.take(1)[0]

    def uint(self, n: int) -> int:
        return int.from_bytes(self.take(n), "little")

    def str8(self) -> str:
        return self.take(self.u8()).decode("utf-8", "replace")

    @property
    def done(self) -> bool:
        return self.pos >= len(self.data)


def decode_args(data: bytes) -> list[Any]:
    """Split a ``Data`` byte array into ints and byte strings."""
    reader = _Reader(data)
    values: list[Any] = []
    while not reader.done:
        tag = reader.u8()
        kind, size = tag >> 4, max((tag & 0xF) - 1, 0)
        if kind == 0:
            values.append(reader.uint(size))
        elif kind == 1:
            values.append(reader.take(reader.uint(size)))
        else:
            msg = f"unknown tag 0x{tag:02x} at {reader.pos - 1}"
            raise ValueError(msg)
    return values


def decompress(blob: bytes) -> Snapshot:
    """Inflate a zlib blob with its trailing size, and parse the tree in it."""
    inflater = zlib.decompressobj()
    raw = inflater.decompress(blob)
    trailer = inflater.unused_data
    if not inflater.eof or not trailer or trailer[-1] != len(trailer):
        msg = f"bad snapshot trailer {trailer.hex()}"
        raise ValueError(msg)
    if int.from_bytes(trailer[:-1], "big") != len(raw):
        msg = f"snapshot size {len(raw)} != trailer {trailer.hex()}"
        raise ValueError(msg)
    tree = decode_tree(raw) if raw.startswith(b"<") else None
    return Snapshot(len(blob), raw, tree)


def _value(reader: _Reader, kind: int) -> Any:
    if kind == 0x01:
        return struct.unpack("<i", reader.take(4))[0]
    if kind == 0x02:
        return struct.unpack("<f", reader.take(4))[0]
    if kind == 0x04:
        return reader.str8()
    if kind == 0x05:
        return bool(reader.u8())
    if kind == 0x06:
        return decode_args(reader.take(reader.uint(4)))
    if kind == 0x07:
        return struct.unpack("<d", reader.take(8))[0]
    if kind == 0x08:
        return reader.uint(2)
    msg = f"unknown field type 0x{kind:02x} at {reader.pos - 1}"
    raise ValueError(msg)


def _node(reader: _Reader) -> Node:
    if reader.u8() != ord("<"):
        msg = f"expected '<' at {reader.pos - 1}"
        raise ValueError(msg)
    node = Node(reader.str8())
    for _ in range(reader.u8()):
        name = reader.str8()
        node.fields.append((name, _value(reader, reader.u8())))
    node.children.extend(_node(reader) for _ in range(reader.u8()))
    if reader.u8() != ord(">"):
        msg = f"expected '>' at {reader.pos - 1}"
        raise ValueError(msg)
    return node


def decode_tree(raw: bytes) -> Node:
    """Parse a binary save-file tree.

    A node is ``'<'``, its name, a count of fields (each a name, a type byte
    and a value), a count of child nodes, the children, then ``'>'``. Names
    and counts are single bytes.
    """
    reader = _Reader(raw)
    node = _node(reader)
    if not reader.done:
        msg = f"{len(raw) - reader.pos} trailing bytes after the tree"
        raise ValueError(msg)
    return node


def _show(value: Any) -> str:
    if isinstance(value, bytes):
        try:
            text = value.decode("utf-8")
        except UnicodeDecodeError:
            return f"<{len(value)} bytes>"
        return repr(text) if text.isprintable() else f"<{len(value)} bytes>"
    if isinstance(value, float):
        return f"{value:g}"
    if isinstance(value, list):
        return "[" + ", ".join(_show(v) for v in value) + "]"
    return repr(value) if isinstance(value, str) else str(value)


def format_tree(node: Node, indent: str = "") -> list[str]:
    """One line per node: ``name {field=value, ...}``, children indented."""
    fields = ", ".join(f"{k}={_show(v)}" for k, v in node.fields)
    lines = [f"{indent}{node.name}" + (f" {{{fields}}}" if fields else "")]
    for child in node.children:
        lines.extend(format_tree(child, indent + "  "))
    return lines


def event_payload(packet: PhotonOperationPacket) -> tuple[int, bytes] | None:
    """``(event code, Data)`` of a ``RaiseEvent`` or an event, else None."""
    payload = packet.get_payload()
    data = payload.params.get(ParameterKey.Data)
    if not isinstance(data, Int8SliceParameter):
        return None
    if packet.get_header().get_command_code() in (
        CommandCode.Event,
        CommandCode.EncryptedEvent,
    ):
        return int(payload.operation_code), bytes(data.value)
    code = payload.params.get(ParameterKey.Code)
    if payload.operation_code == OperationCode.RaiseEvent and code is not None:
        return int(code.value), bytes(data.value)
    return None


def packet_label(packet: PhotonOperationPacket) -> str:
    """Colon-separated name for filtering, e.g. ``RaiseEvent:SystemState:World``.

    Parts: the operation, then (for game events) the event name or code and
    the first argument when it is text (a system's name for ``SystemState``).
    """
    op = packet.get_payload().operation_code
    try:
        parts = [OperationCode(op).name]
    except ValueError:
        parts = [str(op)]
    event = event_payload(packet)
    if event is not None:
        code, data = event
        parts.append(EVENT_NAMES.get(code, str(code)))
        try:
            args = decode_args(data)
        except ValueError:
            args = []
        if args and isinstance(args[0], bytes):
            parts.append(args[0].decode("utf-8", "replace"))
    return ":".join(parts)


def is_hidden(label: str, hidden: list[str]) -> bool:
    """Whether ``label`` equals, or is nested under, one of ``hidden``."""
    return any(label == h or label.startswith(h + ":") for h in hidden)


def _actor_property(key: str, value: Any) -> str:
    """Readable ``SetProperties`` entry: ``C`` is a colour, ``P`` the ping."""
    if key == "P":
        return f"ping = {value} ms"
    if key == "C" and isinstance(value, str) and value.lower().startswith("0x"):
        rgba = value[2:].rjust(8, "0")
        return f"colour = #{rgba[:6]} (alpha {rgba[6:]})"
    return f"{key} = {value!r}"


def _set_properties_lines(packet: PhotonOperationPacket) -> list[str] | None:
    """One line for an actor ``SetProperties`` request, else None."""
    params = packet.get_payload().params
    props = params.get(ParameterKey.Properties)
    actor = params.get(ParameterKey.ActorNr)
    if props is None or actor is None or not isinstance(props.value, dict):
        return None
    entries = ", ".join(
        _actor_property(str(getattr(k, "value", k)), getattr(v, "value", v))
        for k, v in props.value.items()
    )
    broadcast = params.get(ParameterKey.Broadcast)
    suffix = " (broadcast)" if broadcast is not None and broadcast.value else ""
    return [f"Actor {actor.value}: {entries}{suffix}"]


def log_lines(packet: PhotonOperationPacket) -> list[str]:
    """``packet.log()``, with a game event's ``Data`` parsed."""
    lines = packet.log()
    summary = _set_properties_lines(packet)
    if summary is not None:
        shown = {
            f"  {get_parameter_key_name(key)}: {value}"
            for key, value in packet.get_payload().params.items()
        }
        return [line for line in lines if line not in shown] + [
            "  " + line for line in summary
        ]
    event = event_payload(packet)
    if event is None:
        return lines
    data = packet.get_payload().params[ParameterKey.Data]
    raw = f"  {get_parameter_key_name(ParameterKey.Data)}: {data}"
    lines = [line for line in lines if line != raw]
    return lines + ["  " + line for line in format_event(*event)]


def format_event(code: int, data: bytes) -> list[str]:
    """Readable lines for one event's ``Data``; raw hex if it won't parse."""
    title = f"Event {code}" + (f" ({EVENT_NAMES[code]})" if code in EVENT_NAMES else "")
    try:
        args = decode_args(data)
        if code == CASHFLOW_EVENT and len(args) == 4 and isinstance(args[1], bytes):
            name = args[1].decode("utf-8", "replace")
            return [
                f"{title}:",
                f"  {name}: amount {args[0]} (unknown: {args[2]}, {args[3]})",
            ]
        lines = []
        for value in args:
            if isinstance(value, bytes) and value[:1] == b"\x78":
                snap = decompress(value)
                lines.append(
                    f"snapshot: {snap.compressed_size} B zlib -> {len(snap.raw)} B"
                )
                if snap.tree is not None:
                    lines.extend("  " + line for line in format_tree(snap.tree))
                else:
                    lines.append(f"  {snap.raw.hex(' ')}")
            else:
                lines.append(_show(value))
    except (ValueError, zlib.error) as exc:
        return [f"{title}: unparsed ({exc}): {data.hex(' ')}"]
    return [f"{title}:", *("  " + line for line in lines)]
