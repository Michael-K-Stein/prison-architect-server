"""Proxy mode: which games are live, which one the console is attached to, and
sending the client of an attached game an event of our own.

A game is a client connection that has joined a room on the Game Server hop
(its ``JoinGame`` / ``CreateGame`` response carries the client's ``ActorNr``).
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pyphotonrealtime.protocol.command_code import CommandCode
from pyphotonrealtime.protocol.operation_code import OperationCode
from pyphotonrealtime.protocol.packet.factory import PacketFactory
from pyphotonrealtime.protocol.packet.operation_packet import PhotonOperationPacket
from pyphotonrealtime.protocol.param.int32_param import Int32Parameter
from pyphotonrealtime.protocol.param.parameter_key import ParameterKey
from pyphotonrealtime.realtime._convert import to_param, to_python
from pyphotonrealtime.server import Direction

from src.protocol.rpc import build

ENTER_OPERATIONS = (OperationCode.JoinGame, OperationCode.CreateGame)
EVENT_COMMANDS = (CommandCode.Event, CommandCode.EncryptedEvent)
DIRECTORY_DATA = 9
PLAYER_NAME_KEY = 255


def player_name(params: Any) -> str:
    """The actor name in an enter request's player properties (property 255)."""
    props = params.get(ParameterKey.PlayerProperties)
    try:
        value = to_python(props).get(PLAYER_NAME_KEY) if props is not None else None
    except (AttributeError, TypeError):
        return ""
    return str(value) if value else ""


@dataclass(eq=False)
class Game:
    """A joined game: one proxied client in one room."""

    number: int
    """1-based label for ``attach N``; never reused in a run."""
    name: str
    session: Any
    actor: int
    player: str = ""
    """The actor's name, from the player properties of its enter request."""
    host_actor: int | None = None
    """The room's host, learned from the first ``DirectoryData`` event it sends."""

    def label(self) -> str:
        return f"{self.name or '(unnamed)'} ({self.who()}, #{self.number})"

    def who(self) -> str:
        """``actor 2 "Claude"``: the actor number, plus its name when known."""
        return (
            f'actor {self.actor} "{self.player}"'
            if self.player
            else f"actor {self.actor}"
        )


class GameTracker:
    """Watches proxied traffic for games, and holds the one the user attached to."""

    def __init__(self, alive: Callable[[Any], bool]) -> None:
        """``alive(session)``: whether the proxy still has that session."""
        self._alive = alive
        self._lock = threading.Lock()
        self._asked: dict[Any, tuple[str, str]] = {}
        """session -> (room, actor name) of its last enter request"""
        self._games: list[Game] = []
        self._count = 0
        self.attached: Game | None = None

    def observe(self, session: Any, direction: Direction, packet: Any) -> None:
        """Call for every packet; picks out room requests and their responses."""
        if not isinstance(packet, PhotonOperationPacket):
            return
        payload = packet.get_payload()
        if (
            direction == Direction.ToClient
            and payload.operation_code == DIRECTORY_DATA
            and packet.get_header().get_command_code() in EVENT_COMMANDS
        ):
            self._learn_host(session, payload.params.get(ParameterKey.ActorNr))
            return
        if payload.operation_code not in ENTER_OPERATIONS:
            return
        params = payload.params
        if direction == Direction.ToServer:
            name = params.get(ParameterKey.GameId)
            with self._lock:
                self._asked[session] = (
                    str(name.value) if name is not None else "",
                    player_name(params),
                )
            return
        actor = params.get(ParameterKey.ActorNr)
        if actor is None or payload.get_return_code() != 0:
            return  # a Master Server answer (an address) or a refusal
        name = params.get(ParameterKey.GameId)
        with self._lock:
            asked_room, asked_player = self._asked.get(session, ("", ""))
            room = str(name.value) if name is not None else asked_room
            self._count += 1
            game = Game(self._count, room, session, int(actor.value), asked_player)
            self._games.append(game)
            old = self.attached
            if old is not None and not self._alive(old.session) and old.name == room:
                self.attached = game  # the attached game's client reconnected

    def _learn_host(self, session: Any, actor: Any) -> None:
        if actor is None:
            return
        with self._lock:
            for game in self._games:
                if game.session is session:
                    game.host_actor = int(actor.value)

    def games(self) -> list[Game]:
        """Live games, oldest first (dead ones are forgotten)."""
        with self._lock:
            self._games = [g for g in self._games if self._alive(g.session)]
            return list(self._games)

    def rooms(self) -> list[tuple[str, list[Game]]]:
        """Live games grouped by room name (one entry per room, its clients in
        join order). Unnamed games are never merged."""
        out: list[tuple[str, list[Game]]] = []
        for game in self.games():
            for name, members in out:
                if name and name == game.name:
                    members.append(game)
                    break
            else:
                out.append((game.name, [game]))
        return out

    def current(self) -> Game | None:
        """The attached game while its client is still connected, else None."""
        game = self.attached
        if game is not None and not self._alive(game.session):
            return None
        return game

    def attach(self, ref: str | None) -> Game:
        """Attach to a game by number or name (no ``ref``: the only live game)."""
        live = self.games()
        if not live:
            raise ValueError("no game to attach to yet: join one in the client")
        if ref is None:
            if len(live) != 1:
                raise ValueError("several games; say which (games lists them)")
            found = live[0]
        else:
            name, _, actor = ref.rpartition(":")
            matches = [g for g in live if ref == str(g.number) or g.name == ref]
            if not matches and actor.isdigit():  # NAME:ACTOR picks one client of a room
                matches = [g for g in live if g.name == name and g.actor == int(actor)]
            if len(matches) > 1:
                raise ValueError(
                    f"{ref!r} has {len(matches)} clients; pick one: "
                    + ", ".join(
                        f"#{g.number} or {g.name}:{g.actor} ({g.player or 'no name'})"
                        for g in matches
                    )
                )
            if not matches:
                raise ValueError(f"no game matches {ref!r} (games lists them)")
            found = matches[0]
        self.attached = found
        return found

    def detach(self) -> None:
        self.attached = None

    def status(self) -> str:
        """Text for the status bar."""
        game = self.attached
        if game is None:
            return "not attached (games, attach)"
        if not self._alive(game.session):
            return f"attached to {game.name or game.number}: client gone"
        return f"attached: {game.name or '(unnamed)'} as {game.who()}"


def event_from_data(
    game: Game, code: int, data: bytes, sender: int | None = None
) -> PhotonOperationPacket:
    """The event ``code`` with ready-made ``Data`` bytes, as the Game Server would
    send it to this client.

    ``ActorNr`` + ``Data`` is the layout the server relays; the sender is
    ``sender`` (default: the client's own actor, always in the room).
    """
    session = game.session
    params: Any = {
        ParameterKey.ActorNr: Int32Parameter(game.actor if sender is None else sender),
        ParameterKey.Data: to_param(data),
    }
    return PacketFactory.event(
        code,
        params,
        encrypted=session.client_key is not None,
        protocol=session.client_parser.protocol,
    )


def event_packet(
    game: Game, code: int, *args: object, sender: int | None = None
) -> PhotonOperationPacket:
    """Like :func:`event_from_data`, with ``Data`` built from RPC ``code(*args)``.

    Raises ``RpcShapeError`` (a ``ValueError``) for arguments the RPC doesn't take.
    """
    return event_from_data(game, code, build(code, *args), sender)


def deliver(
    game: Game,
    packet: PhotonOperationPacket,
    record: Callable[..., int | None] | None = None,
) -> int | None:
    """Send ``packet`` to the client of ``game``; returns its capture id.

    ``record(session, direction, packet, injected=True)`` (the recorder's
    ``record``) stores it, marked as injected.
    """
    game.session.send_to_client(packet)
    if record is None:
        return None
    return record(game.session, Direction.ToClient, packet, injected=True)


def inject(
    game: Game,
    code: int,
    *args: object,
    sender: int | None = None,
    record: Callable[..., int | None] | None = None,
) -> tuple[PhotonOperationPacket, int | None]:
    """Send the client of ``game`` the event ``code(*args)``; returns it and its id."""
    packet = event_packet(game, code, *args, sender=sender)
    return packet, deliver(game, packet, record)
