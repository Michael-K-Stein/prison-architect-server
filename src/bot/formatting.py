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


def room_players(room: Any) -> list[str]:
    """Player names in ``room``, from its players dict or custom properties."""
    names: list[str] = []

    players = getattr(room, "players", None)
    if isinstance(players, dict):
        for _, p in sorted(players.items(), key=lambda kv: str(kv[0])):
            nick = getattr(p, "nick_name", None) or getattr(p, "name", None)
            if not nick and isinstance(p, str):
                nick = p
            if nick and str(nick) not in names:
                names.append(str(nick))
    elif isinstance(players, (list, tuple, set)):
        for p in players:
            nick = getattr(p, "nick_name", None) or getattr(p, "name", None)
            if not nick and isinstance(p, str):
                nick = p
            if nick and str(nick) not in names:
                names.append(str(nick))

    props = getattr(room, "custom_properties", None)
    if isinstance(props, dict):
        for key in ("players", "player_names", "names", "actors"):
            val = props.get(key)
            if isinstance(val, (list, tuple, set)):
                for item in val:
                    n = (
                        getattr(item, "nick_name", None)
                        or getattr(item, "name", None)
                        or str(item)
                    )
                    if n and str(n) not in names:
                        names.append(str(n))
            elif isinstance(val, str) and val.strip():
                for part in val.split(","):
                    p = part.strip()
                    if p and p not in names:
                        names.append(p)

        mas = props.get("MAS") or props.get("GameMaster")
        if isinstance(mas, str) and mas.strip():
            mas_name = mas.strip()
            if mas_name not in names:
                names.insert(0, mas_name)
        elif isinstance(mas, (list, tuple, set)):
            for item in mas:
                n = str(item).strip()
                if n and n not in names:
                    names.append(n)

    mc = getattr(room, "master_client", None)
    if mc is not None:
        mc_name = getattr(mc, "nick_name", None) or getattr(mc, "name", None)
        if mc_name and str(mc_name) not in names:
            names.insert(0, str(mc_name))

    return names


def format_room(room: RoomInfo) -> str:
    """One game menu line: name, player count/max, state and players in the room."""
    state = "open" if room.is_open else "closed"
    players = room_players(room)
    players_part = f"  {', '.join(players)}" if players else ""
    return (
        f"{room.name}  ({room.player_count}/{room.max_players or '?'})  "
        f"{state}{players_part}"
    )


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
