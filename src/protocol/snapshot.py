"""Tagged values and save-file trees inside a ``RaiseEvent`` ``Data`` array.

The game sends everything through ``RaiseEvent`` with the event code in
``ParameterKey.Code`` (244) and a byte array in ``ParameterKey.Data`` (245).
That byte array is a list of tagged values (:func:`decode_args`):

* tag ``0x0N`` (N 1-4): a whole number in ``N - 1`` little-endian bytes
  (``0x00`` is 0); ``0x08`` set means negative (``0x0b a0 14`` = -5280);
* tag ``0x1a``: a float32;
* tag ``0x1N``: a byte string whose length is in ``N - 1`` little-endian
  bytes (``0x12`` = 1-byte length, ``0x13`` = 2-byte length).

A ``DirectoryData`` snapshot is zlib-compressed and followed by its
uncompressed size, written backwards (see :func:`decompress`). Uncompressed,
it is a binary form of the save-file tree (:func:`decode_tree`).
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass, field
from typing import Any

FLOAT_TAG = 0x1A


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

    def str8(self) -> str | None:
        """A u8-length string; length ``0xff`` escapes to an int32 (-1: null)."""
        size = self.u8()
        if size == 0xFF:
            size = struct.unpack("<i", self.take(4))[0]
            if size < 0:
                return None
        return self.take(size).decode("utf-8", "replace")

    def count(self) -> int:
        """A u8 field/child count; ``0xff`` escapes to an int32 (``CellData``)."""
        size = self.u8()
        return struct.unpack("<i", self.take(4))[0] if size == 0xFF else size

    @property
    def done(self) -> bool:
        return self.pos >= len(self.data)


def decode_args(data: bytes) -> list[Any]:
    """Split a ``Data`` byte array into ints and byte strings."""
    reader = _Reader(data)
    values: list[Any] = []
    while not reader.done:
        tag = reader.u8()
        kind, size = tag >> 4, max((tag & 0x7) - 1, 0)
        if tag == FLOAT_TAG:
            values.append(struct.unpack("<f", reader.take(4))[0])
        elif kind == 0:
            value = reader.uint(size)
            values.append(-value if tag & 0x8 else value)
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
    if kind == 0x03:
        return reader.u8()
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
    if kind == 0x09:
        return struct.unpack("<q", reader.take(8))[0]
    msg = f"unknown field type 0x{kind:02x} at {reader.pos - 1}"
    raise ValueError(msg)


def _node(reader: _Reader) -> Node:
    if reader.u8() != ord("<"):
        msg = f"expected '<' at {reader.pos - 1}"
        raise ValueError(msg)
    node = Node(reader.str8())
    for _ in range(reader.count()):
        name = reader.str8()
        node.fields.append((name, _value(reader, reader.u8())))
    node.children.extend(_node(reader) for _ in range(reader.count()))
    if reader.u8() != ord(">"):
        msg = f"expected '>' at {reader.pos - 1}"
        raise ValueError(msg)
    return node


def decode_tree(raw: bytes) -> Node:
    """Parse a binary save-file tree.

    A node is ``'<'``, its name, a count of fields (each a name, a type byte
    and a value), a count of child nodes, the children, then ``'>'``. Names
    and counts are single bytes; ``0xff`` escapes to an int32 (long string,
    or 255+ children).
    """
    reader = _Reader(raw)
    node = _node(reader)
    if not reader.done:
        msg = f"{len(raw) - reader.pos} trailing bytes after the tree"
        raise ValueError(msg)
    return node


def show_value(value: Any) -> str:
    """A decoded value as readable text; non-text bytes as their length."""
    if isinstance(value, bytes):
        try:
            text = value.decode("utf-8")
        except UnicodeDecodeError:
            return f"<{len(value)} bytes>"
        return repr(text) if text.isprintable() else f"<{len(value)} bytes>"
    if isinstance(value, float):
        return f"{value:g}"
    if isinstance(value, list):
        return "[" + ", ".join(show_value(v) for v in value) + "]"
    return repr(value) if isinstance(value, str) else str(value)


def _field(key: str, value: Any) -> str:
    """``key=value``, with a hint for fields whose meaning is known."""
    text = f"{key}={show_value(value)}"
    if key == "gt" and isinstance(value, (int, float)):
        text += " (paused)" if value == 0 else f" (speed {value:g}x)"
    return text


def format_tree(node: Node, indent: str = "") -> list[str]:
    """One line per node: ``name {field=value, ...}``, children indented.

    ``gt`` (``World``'s ``ClientData``/``UniformColourData``) is the game
    speed: 0 when paused, else the multiplier (1, 2, 5 or 10).
    """
    fields = ", ".join(_field(k, v) for k, v in node.fields)
    lines = [f"{indent}{node.name}" + (f" {{{fields}}}" if fields else "")]
    for child in node.children:
        lines.extend(format_tree(child, indent + "  "))
    return lines
