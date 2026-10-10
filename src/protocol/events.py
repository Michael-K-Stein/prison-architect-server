"""Prison Architect's own payloads inside Photon ``RaiseEvent`` / events.

The game sends everything through ``RaiseEvent`` with the event code in
``ParameterKey.Code`` (244) and a byte array in ``ParameterKey.Data`` (245).
The byte array is read by :mod:`src.protocol.snapshot` (:func:`decode_args`).
Event names and argument types come from the game's binary: the table is
generated into :mod:`src.protocol.rpc_table` and read through
:mod:`src.protocol.rpc`. Event codes seen in the captures:

* ``9`` -- ``DirectoryData``, ``[system name, snapshot]``. The snapshot is
  zlib-compressed and followed by the uncompressed size, written backwards
  (big-endian bytes, then their count + 1) so it can be read from the end.
  Uncompressed, it is a binary form of the save-file tree
  (:func:`src.protocol.snapshot.decode_tree`).
* ``13`` -- ``ObjectAdded``, ``[ObjectId (uId, index), type]``: an object was
  spawned (it then appears in ``ObjectData`` as node ``index`` with ``uId``
  and ``t=type``). Seen for a delivery truck (type 139) and the materials it
  carries (type 2).
* ``14`` -- ``ObjectRemoved``, ``[ObjectId]``.
* ``118`` -- ``TransactionAdded``, ``[amount, ledger key, signed char,
  string]``: a cash-flow item added to the balance (``World.Balance``,
  ``Finance.v.6``). ``35`` / ``finance_cost_cashflow`` at game start;
  ``-5280`` / ``finance_cost_foundations`` for a 17x14 concrete foundation.
  The last two are 0 in every capture (the string is sent as 0, i.e. empty).

Filters and labels may use our earlier names for 9, 13 and 118
(``SystemState``, ``SpawnObject``, ``Cashflow``); see
:data:`LEGACY_EVENT_NAMES`.

Unknown tags or field types raise :class:`ValueError`; callers that only
display payloads should fall back to the raw bytes.
"""

from __future__ import annotations

import zlib
from typing import TYPE_CHECKING, Any

from pyphotonrealtime.protocol.command_code import CommandCode
from pyphotonrealtime.protocol.enum_lookups import get_parameter_key_name
from pyphotonrealtime.protocol.operation_code import OperationCode
from pyphotonrealtime.protocol.param.int8_slice_param import Int8SliceParameter
from pyphotonrealtime.protocol.param.parameter_key import ParameterKey

from src.protocol.rpc import RpcShapeError, format_rpc, lookup, parse, rpc_name
from src.protocol.snapshot import decode_args, decompress, format_tree, show_value

if TYPE_CHECKING:
    from pyphotonrealtime.protocol.packet.operation_packet import (
        PhotonOperationPacket,
    )

SNAPSHOT_EVENT = 9
SPAWN_EVENT = 13
CASHFLOW_EVENT = 118
LEGACY_EVENT_NAMES = {
    # Our own guesses, used before the game's names were known. Old filters
    # such as ``RaiseEvent:SystemState`` keep matching: labels and filters
    # are compared after mapping these to the game's names (see is_hidden).
    "SystemState": "DirectoryData",  # 9
    "SpawnObject": "ObjectAdded",  # 13
    "Cashflow": "TransactionAdded",  # 118
}
"""Old event name -> the game's name (``src.protocol.rpc_table``), for filters."""


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
        parts.append(rpc_name(code))
        try:
            args = decode_args(data)
        except ValueError:
            args = []
        if args and isinstance(args[0], bytes):
            parts.append(args[0].decode("utf-8", "replace"))
    return ":".join(parts)


def _canonical(label: str) -> str:
    """``label`` with an old event name in its event part mapped to the game's."""
    parts = label.split(":")
    if len(parts) > 1:
        parts[1] = LEGACY_EVENT_NAMES.get(parts[1], parts[1])
    return ":".join(parts)


def is_hidden(label: str, hidden: list[str]) -> bool:
    """Whether ``label`` equals, or is nested under, one of ``hidden``.

    Old event names work on either side: ``RaiseEvent:SystemState`` hides
    ``RaiseEvent:DirectoryData:World`` and vice versa.
    """
    label = _canonical(label)
    return any(label == h or label.startswith(h + ":") for h in map(_canonical, hidden))


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
    """Readable lines for one event's ``Data``; raw hex if it won't parse.

    Codes 9, 13 and 118 have their own rendering. Other codes use the typed
    parser in :mod:`src.protocol.rpc`; if that fails (unknown code, wrong
    shape) the flat values are shown one per line.
    """
    rpc = lookup(code)
    title = f"Event {code}" + (f" ({rpc.name})" if rpc is not None else "")
    try:
        args = decode_args(data)
        if code == CASHFLOW_EVENT and len(args) == 4 and isinstance(args[1], bytes):
            name = args[1].decode("utf-8", "replace")
            return [
                f"{title}:",
                f"  {name}: amount {args[0]:+} (int {args[2]}, string {(args[3] or '')!r})",
            ]
        if code == SPAWN_EVENT and len(args) == 3:
            uid, index, kind = args
            return [f"{title}:", f"  uId {uid} as object {index}, type {kind}"]
        if code != SNAPSHOT_EVENT:
            try:
                parsed = parse(code, data)
            except RpcShapeError:
                pass
            else:
                # format_rpc's first line repeats the title, and its argument
                # lines are already indented by two spaces.
                return [f"{title}:", *format_rpc(parsed)[1:]]
        lines = []
        system = (
            args[0].decode("utf-8", "replace")
            if code == SNAPSHOT_EVENT and args and isinstance(args[0], bytes)
            else None
        )
        for value in args:
            if isinstance(value, bytes) and value[:1] == b"\x78":
                snap = decompress(value)
                lines.append(
                    f"snapshot: {snap.compressed_size} B zlib -> {len(snap.raw)} B"
                )
                if snap.tree is not None:
                    lines.extend(
                        "  " + line for line in format_tree(snap.tree, system=system)
                    )
                else:
                    lines.append(f"  {snap.raw.hex(' ')}")
            else:
                lines.append(show_value(value))
    except (ValueError, zlib.error) as exc:
        return [f"{title}: unparsed ({exc}): {data.hex(' ')}"]
    return [f"{title}:", *("  " + line for line in lines)]
