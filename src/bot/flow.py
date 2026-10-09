"""The connect-and-join flow: Master Server, lobby, game."""

from __future__ import annotations

import time
from typing import Any

import typer
from InquirerPy import inquirer
from pyphotonrealtime.realtime import EnterRoomParams
from pyphotonrealtime.realtime.lobby import LobbyType, TypedLobby

from src.bot.formatting import colour_property, format_lobby, format_room
from src.bot.session import Options, Session, make_settings


def pick(message: str, choices: list[tuple[str, Any]]) -> Any:
    """An InquirerPy select over ``(label, value)`` pairs."""
    return inquirer.select(
        message=message,
        choices=[{"name": name, "value": value} for name, value in choices],
        raise_keyboard_interrupt=True,
    ).execute()


def join_flow(opts: Options, region: str) -> Session:
    """Connect to ``region``'s Master, pick a lobby and a game, join it."""
    session = Session()
    # Sent as the actor name (Photon player property 255), which the game shows.
    session.client.local_player.nick_name = opts.name
    try:
        session.start(make_settings(opts, region))
        if not session.wait_for(lambda: session.master):
            raise typer.BadParameter(f"could not reach region {region!r}")
        lobbies = [TypedLobby()]
        with session.lock:
            lobbies += [
                s.lobby
                for s in session.client.lobby_statistics
                if not s.lobby.is_default
            ]
        lobby = lobbies[0]
        if len(lobbies) > 1:
            lobby = pick("Lobby", [(format_lobby(x), x) for x in lobbies])
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
            raise typer.BadParameter("no games in this lobby")
        name = pick("Game", [(format_room(r), r.name) for r in rooms if r.is_open])
        with session.lock:
            session.client.op_join_room(
                EnterRoomParams(
                    room_name=name,
                    player_properties={"C": colour_property(opts.colour)},
                )
            )
        if not session.wait_for(lambda: session.joined or bool(session.join_error)):
            raise typer.BadParameter("joining timed out")
        if session.join_error:
            raise typer.BadParameter(f"join failed: {session.join_error}")
    except BaseException:
        session.stop()
        raise
    return session
