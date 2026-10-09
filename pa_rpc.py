"""Typed RPC arguments inside a ``RaiseEvent`` ``Data`` byte array.

:mod:`pa_rpc_data` says what each event code means: ``RPCS`` maps the code
to the RPC name and the C++ types of its arguments. This module uses those
types to read and write ``Data``:

* :func:`parse` walks the raw bytes, reading each argument as its declared
  type, so a composite such as ``ObjectId`` (two tagged numbers) becomes one
  ``(uId, index)`` tuple;
* :func:`build` does the reverse and returns the ``Data`` bytes for a call;
* :func:`encode_args` writes tagged values (the inverse of
  :func:`pa_events.decode_args` for them).

A ``bool`` is not a tagged value: it is one raw byte, ``00`` (false) or
``01`` (true), so it is read and written by its type, never as a tag. (A
``01`` byte read as a tag would decode as the number 0.)

:data:`COMPOSITE_ARITY` gives how many wire values each type takes. A code
that uses a type of unknown arity cannot be split, so :func:`parse` and
:func:`build` raise :class:`RpcShapeError` for it.

Encoding follows the tags that :func:`pa_events.decode_args` reads: a whole
number uses the fewest little-endian magnitude bytes (at most 3, the
largest size the captures use), tag ``0x08`` for negative, and ``0x00`` for
zero. A byte string's tag is ``0x10`` plus the length-bytes count plus one,
so ``0x12`` is a one-byte length. A float is tag ``0x1a`` and a float32.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Any

from pa_rpc_data import RPCS

COMPOSITE_ARITY: dict[str, int | None] = {
    "int": 1,  # measured: code 13 (x5, with ObjectId) and 118 (x8)
    "bool": 1,  # one raw byte 00/01 (from the binary; not a tagged value)
    "float": 1,  # format only: one 0x1a tag; not seen in captures
    "string": 1,  # measured: code 118 (x8) and 9 (x1461, with MemoryBlock)
    "signed char": 1,  # measured: code 118 (x8)
    "MemoryBlock": 1,  # measured: code 9 (x1461)
    "ObjectId": 2,  # measured: code 13 (x5, with int) and 14 (x1, alone)
    "Vector2": None,  # unknown: no captured code uses it
    "Vector3": None,  # unknown: no captured code uses it
    "WorldPosition": None,  # unknown: no captured code uses it
    "MisconductPolicy": None,  # unknown: no captured code uses it
    "SoundConstraint": None,  # unknown: no captured code uses it
    "SoundObjectId": None,  # unknown: no captured code uses it
    "NetworkSoundId": None,  # unknown: no captured code uses it
    "CustomSectorNetworkData": None,  # unknown: no captured code uses it
}
"""Flat wire values per declared type; ``None`` = not yet measured."""

MAX_MAGNITUDE_BYTES = 3
"""Largest whole-number magnitude (in bytes) the encoder writes."""

FLOAT_TAG = 0x1A
NEGATIVE_BIT = 0x08
_MAX_MAGNITUDE = (1 << (8 * MAX_MAGNITUDE_BYTES)) - 1


class RpcShapeError(ValueError):
    """A payload or argument list does not match the RPC's declared types."""


@dataclass(frozen=True)
class Rpc:
    """One entry of ``RPCS``: the event code, its name and argument types."""

    code: int
    name: str
    types: tuple[str, ...]


@dataclass
class ParsedRpc:
    """A decoded call: ``args`` is ``(type name, value)`` per argument.

    A composite value is a tuple (``ObjectId`` -> ``(uId, index)``); a byte
    string is ``bytes``, a whole number ``int``, a float32 ``float``.
    """

    rpc: Rpc
    args: list[tuple[str, object]]


def lookup(code: int) -> Rpc | None:
    """The RPC registered for ``code``, or None."""
    entry = RPCS.get(code)
    if entry is None:
        return None
    name, types = entry
    return Rpc(code, name, types)


def rpc_name(code: int) -> str:
    """The RPC's name, or the code as text when it is unknown."""
    rpc = lookup(code)
    return str(code) if rpc is None else rpc.name


def _encode_int(value: int) -> bytes:
    magnitude = abs(value)
    if magnitude > _MAX_MAGNITUDE:
        msg = f"{value} does not fit in {MAX_MAGNITUDE_BYTES} bytes"
        raise ValueError(msg)
    size = (magnitude.bit_length() + 7) // 8
    if size == 0:
        return b"\x00"
    tag = (size + 1) | (NEGATIVE_BIT if value < 0 else 0)
    return bytes([tag]) + magnitude.to_bytes(size, "little")


def _encode_bytes(data: bytes) -> bytes:
    size = (len(data).bit_length() + 7) // 8
    if size > MAX_MAGNITUDE_BYTES:
        msg = f"{len(data)} bytes is too long for a byte string tag"
        raise ValueError(msg)
    if size == 0:
        return b"\x10"
    return bytes([0x10 | (size + 1)]) + len(data).to_bytes(size, "little") + data


def encode_args(values: list[int | float | bool | bytes | str]) -> bytes:
    """Encode flat values as a ``Data`` byte array.

    The inverse of :func:`pa_events.decode_args` for tagged values: ``str``
    is its UTF-8 bytes, ``float`` a float32. A ``bool`` is not a tagged
    value (the game reads it as one raw byte), so it is refused here; use
    :func:`build`, which writes it correctly.
    Raises ``ValueError`` for a whole number too big for three bytes, a
    float32 overflow, or a byte string too long for the length tag, and
    ``TypeError`` for a ``bool`` or an unsupported type.
    """
    out = bytearray()
    for value in values:
        if isinstance(value, bool):
            msg = "a bool is one raw byte, not a tagged value; use build()"
            raise TypeError(msg)
        if isinstance(value, float):
            out.append(FLOAT_TAG)
            try:
                out += struct.pack("<f", value)
            except OverflowError as exc:
                msg = f"{value} does not fit in a float32"
                raise ValueError(msg) from exc
        elif isinstance(value, int):
            out += _encode_int(int(value))
        elif isinstance(value, str):
            out += _encode_bytes(value.encode("utf-8"))
        elif isinstance(value, bytes):
            out += _encode_bytes(value)
        else:
            msg = f"cannot encode a {type(value).__name__}"
            raise TypeError(msg)
    return bytes(out)


def _arity(type_name: str) -> int | None:
    return COMPOSITE_ARITY.get(type_name)


def _read_tagged(rpc: Rpc, data: bytes, pos: int) -> tuple[Any, int]:
    """One tagged value at ``pos`` (as :func:`pa_events.decode_args` reads it).

    Returns the value and the position after it. Only used for types other
    than ``bool``, which is a raw byte and so must be read by its type.
    """

    def take(n: int) -> bytes:
        if pos + n > len(data):
            msg = f"{rpc.name}: truncated at byte {pos}"
            raise RpcShapeError(msg)
        return data[pos : pos + n]

    tag = take(1)[0]
    pos += 1
    if tag == FLOAT_TAG:
        return struct.unpack("<f", take(4))[0], pos + 4
    kind, size = tag >> 4, max((tag & 0x7) - 1, 0)
    if kind == 0:
        value = int.from_bytes(take(size), "little")
        pos += size
        return (-value if tag & NEGATIVE_BIT else value), pos
    if kind == 1:
        length = int.from_bytes(take(size), "little")
        pos += size
        return take(length), pos + length
    msg = f"{rpc.name}: unknown tag 0x{tag:02x} at byte {pos - 1}"
    raise RpcShapeError(msg)


def _walk(rpc: Rpc, data: bytes) -> list[tuple[str, object]]:
    """Split ``data`` by the declared types, reading each argument as its type.

    A ``bool`` is one raw byte, ``00`` or ``01``; anything else is an error.
    Other types are tagged values (a composite takes its arity of them).
    """
    args: list[tuple[str, object]] = []
    pos = 0
    for type_name in rpc.types:
        if type_name == "bool":
            if pos >= len(data):
                msg = f"{rpc.name}: truncated at byte {pos}"
                raise RpcShapeError(msg)
            byte = data[pos]
            pos += 1
            if byte not in (0, 1):
                msg = f"{rpc.name}: bool byte 0x{byte:02x} is not 00 or 01"
                raise RpcShapeError(msg)
            args.append((type_name, bool(byte)))
            continue
        size = _arity(type_name)
        if size is None:
            msg = f"{rpc.name}: wire size of {type_name} is unknown"
            raise RpcShapeError(msg)
        values: list[Any] = []
        for _ in range(size):
            value, pos = _read_tagged(rpc, data, pos)
            values.append(value)
        args.append((type_name, values[0] if size == 1 else tuple(values)))
    if pos != len(data):
        msg = f"{rpc.name}: {len(data) - pos} trailing bytes"
        raise RpcShapeError(msg)
    return args


def parse(code: int, data: bytes) -> ParsedRpc:
    """Decode an event's ``Data`` into the RPC's typed arguments.

    Raises :class:`RpcShapeError` for an unknown code, a bool byte other
    than 00 or 01, a type of unknown arity, truncated or trailing bytes, or
    an unknown tag.
    """
    rpc = lookup(code)
    if rpc is None:
        msg = f"unknown RPC code {code}"
        raise RpcShapeError(msg)
    return ParsedRpc(rpc, _walk(rpc, data))


def _flatten(type_name: str, arg: object) -> list[Any]:
    size = _arity(type_name)
    if size is None:
        msg = f"cannot build {type_name}: its wire size is unknown"
        raise RpcShapeError(msg)
    if size == 1:
        values = [arg]
    elif isinstance(arg, tuple) and len(arg) == size:
        values = list(arg)
    else:
        msg = f"{type_name} takes a tuple of {size} values, got {arg!r}"
        raise RpcShapeError(msg)
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float, str, bytes)):
            msg = f"{type_name}: {value!r} is not a wire value"
            raise RpcShapeError(msg)
    return values


def _bool_byte(rpc: Rpc, arg: object) -> bytes:
    """The raw byte for a ``bool`` argument: a bool, or the int 0 or 1."""
    if isinstance(arg, bool):
        return bytes([int(arg)])
    if isinstance(arg, int) and arg in (0, 1):
        return bytes([arg])
    msg = f"{rpc.name}: bool takes True, False, 0 or 1, got {arg!r}"
    raise RpcShapeError(msg)


def build(code: int, *args: object) -> bytes:
    """The ``Data`` bytes for calling RPC ``code`` with ``args``.

    Composite arguments are tuples (``build(13, (8427316, 17), 139)``); a
    ``bool`` argument is one raw byte (``00`` or ``01``). The count, the
    bool values and the composite shapes are checked; a primitive argument
    is otherwise accepted as any wire value, since the captures do not
    always match the declared type (see the code 118 note in the tests).
    Raises :class:`RpcShapeError` on a wrong count or shape.
    """
    rpc = lookup(code)
    if rpc is None:
        msg = f"unknown RPC code {code}"
        raise RpcShapeError(msg)
    if len(args) != len(rpc.types):
        msg = f"{rpc.name} takes {len(rpc.types)} arguments, got {len(args)}"
        raise RpcShapeError(msg)
    out = bytearray()
    for type_name, arg in zip(rpc.types, args):
        if type_name == "bool":
            out += _bool_byte(rpc, arg)
        else:
            out += encode_args(_flatten(type_name, arg))
    return bytes(out)


def _value_text(type_name: str, value: object) -> str:
    if type_name == "string" and value == 0:
        return "''"
    if isinstance(value, bytes):
        if type_name == "string":
            try:
                return repr(value.decode("utf-8"))
            except UnicodeDecodeError:
                return f"<{len(value)} bytes>"
        if value[:1] == b"\x78":
            return f"<{len(value)} bytes zlib>"
        return f"<{len(value)} bytes>"
    if isinstance(value, tuple):
        if type_name == "ObjectId" and len(value) == 2:
            return f"uId {value[0]}, index {value[1]}"
        return ", ".join(str(item) for item in value)
    if isinstance(value, float):
        return f"{value:g}"
    return repr(value) if isinstance(value, str) else str(value)


def format_rpc(parsed: ParsedRpc) -> list[str]:
    """Readable terminal lines: the RPC's name, then one line per argument."""
    lines = [f"RPC {parsed.rpc.code} {parsed.rpc.name}:"]
    lines.extend(
        f"  {type_name}: {_value_text(type_name, value)}"
        for type_name, value in parsed.args
    )
    return lines
