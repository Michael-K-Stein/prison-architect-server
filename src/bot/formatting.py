"""Menu lines and readable text for incoming game events (pure, no network)."""

from __future__ import annotations

from typing import Any

from pyphotonrealtime.realtime.lobby import TypedLobby
from pyphotonrealtime.realtime.room import RoomInfo

from src.protocol import events, rpc, snapshot

HANDSHAKE_CODES = range(9)  # RPCs 0..8: save-game transfer / authorisation
DIRECTORY_DATA = 9


def colour_property(rrggbb: str) -> str:
    """The game's colour property (``C``): ``0xRRGGBBAA`` with full alpha."""
    return "0x" + rrggbb.lstrip("#").lower() + "ff"


def format_region(code: str, address: str) -> str:
    """One region menu line."""
    return f"{code:<8} {address}"


def format_room(room: RoomInfo) -> str:
    """One game menu line: name, players and whether it can be joined."""
    state = "open" if room.is_open else "closed"
    return f"{room.name}  ({room.player_count}/{room.max_players or '?'})  {state}"


def format_lobby(lobby: TypedLobby) -> str:
    """One lobby menu line."""
    return f"{lobby.name or '(default)'}  [{lobby.type.name}]"


def format_event_lines(
    sender: int, code: int, data: Any, *, verbose: bool = False
) -> list[str]:
    """Readable lines for one incoming game event (RPC ``code``)."""
    head = f"#{sender} "
    if not isinstance(data, (bytes, bytearray)):
        return [f"{head}event {code}: non-byte payload {data!r}"]
    data = bytes(data)
    tag = " [handshake]" if code in HANDSHAKE_CODES or code == DIRECTORY_DATA else ""
    if code == DIRECTORY_DATA and not verbose:
        try:
            name, blob = snapshot.decode_args(data)[:2]
            text = bytes(name).decode("utf-8", "replace")
            return [f"{head}{rpc.rpc_name(code)}{tag}: {text!r}, {len(blob)} B"]
        except (ValueError, TypeError):
            return [f"{head}{rpc.rpc_name(code)}{tag}: {len(data)} B"]
    try:
        lines = rpc.format_rpc(rpc.parse(code, data))
    except rpc.RpcShapeError:
        try:
            lines = events.format_event(code, data)
        except ValueError:
            lines = [f"event {code}: {data.hex(' ')}"]
    return [f"{head}{lines[0]}{tag}", *lines[1:]]
