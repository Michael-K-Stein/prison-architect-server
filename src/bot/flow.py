"""The connect-and-join flow: Master Server, lobby, game."""

from __future__ import annotations

import logging
import time
from typing import Any

from InquirerPy import inquirer
from pyphotonrealtime.realtime import EnterRoomParams
from pyphotonrealtime.realtime.lobby import LobbyType, TypedLobby

from src.bot.formatting import colour_property, format_lobby, format_room
from src.bot.session import ConnectError, Options, Session, make_settings
from src.capture import Recorder

log = logging.getLogger(__name__)


def pick(message: str, choices: list[tuple[str, Any]]) -> Any:
    """An InquirerPy select over ``(label, value)`` pairs."""
    return inquirer.select(
        message=message,
        choices=[{"name": name, "value": value} for name, value in choices],
        raise_keyboard_interrupt=True,
    ).execute()


def connect(opts: Options, region: str, recorder: Recorder | None = None) -> Session:
    """A started :class:`Session` connected to ``region``'s Master Server."""
    session = Session(recorder=recorder)
    # Sent as the actor name (Photon player property 255), which the game shows.
    session.client.local_player.nick_name = opts.name
    try:
        session.start(make_settings(opts, region))
        if not session.wait_for(lambda: session.master):
            raise ConnectError(
                f"could not reach region {region!r}"
                f" (disconnected: {session.disconnected})"
            )
    except BaseException:
        session.stop()
        raise
    return session


def lobbies_of(session: Session) -> list[TypedLobby]:
    """The default lobby, then the other lobbies the Master listed."""
    lobbies = [TypedLobby()]
    with session.lock:
        lobbies += [
            s.lobby for s in session.client.lobby_statistics if not s.lobby.is_default
        ]
    return lobbies


def list_rooms(session: Session, lobby: TypedLobby) -> list[Any]:
    """Join ``lobby`` and return the rooms it lists (ConnectError if none)."""
    log.info("lobby: %s", format_lobby(lobby))
    with session.lock:
        session.client.op_join_lobby(lobby)
    session.wait_for(lambda: session.lobby_joined)
    if lobby.type == LobbyType.SqlLobby:
        with session.lock:
            session.client.op_get_game_list(lobby, "")
    time.sleep(1.5)  # the full room list arrives as an event right after
    with session.lock:
        rooms = list(session.client.room_list.values())
    if not rooms:
        raise ConnectError("no games in this lobby")
    log.info("%d games listed", len(rooms))
    return rooms


def choose_room(rooms: list[Any], name: str | None) -> str:
    """The room called ``name`` (case-insensitive), or the first open one."""
    open_rooms = [r for r in rooms if r.is_open]
    if name is None:
        if not open_rooms:
            raise ConnectError("no open games in this lobby")
        return open_rooms[0].name
    for room in rooms:
        if room.name == name or room.name.lower() == name.lower():
            if not room.is_open:
                raise ConnectError(f"game {room.name!r} is closed")
            return room.name
    listed = ", ".join(repr(r.name) for r in open_rooms) or "none"
    raise ConnectError(f"no game named {name!r}; open games: {listed}")


def enter_room(session: Session, opts: Options, name: str) -> None:
    """Join room ``name`` and wait for the result (ConnectError on failure)."""
    log.info("game chosen: %s", name)
    with session.lock:
        session.client.op_join_room(
            EnterRoomParams(
                room_name=name,
                player_properties={"C": colour_property(opts.colour)},
            )
        )
    if not session.wait_for(lambda: session.joined or bool(session.join_error)):
        raise ConnectError("joining timed out")
    if session.join_error:
        raise ConnectError(f"join failed: {session.join_error}")


def join_room(
    opts: Options,
    region: str,
    room: str | None,
    recorder: Recorder | None = None,
    lobby: TypedLobby | None = None,
) -> Session:
    """Headless join: ``room`` (or the first open one) in ``lobby`` (default)."""
    session = connect(opts, region, recorder)
    try:
        rooms = list_rooms(session, lobby or TypedLobby())
        enter_room(session, opts, choose_room(rooms, room))
    except BaseException:
        session.stop()
        raise
    return session


def join_flow(opts: Options, region: str, recorder: Recorder | None = None) -> Session:
    """Connect to ``region``'s Master, pick a lobby and a game, join it."""
    session = connect(opts, region, recorder)
    try:
        lobbies = lobbies_of(session)
        lobby = lobbies[0]
        if len(lobbies) > 1:
            lobby = pick("Lobby", [(format_lobby(x), x) for x in lobbies])
        rooms = list_rooms(session, lobby)
        name = pick("Game", [(format_room(r), r.name) for r in rooms if r.is_open])
        enter_room(session, opts, name)
    except BaseException:
        session.stop()
        raise
    return session
