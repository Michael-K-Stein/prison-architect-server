"""The Prison Architect game server: room caps and reconnect-friendly TTLs."""

from __future__ import annotations

import os
from typing import Any, override

from pyphotonrealtime.protocol.param.hashtable_param import HashtableParameter
from pyphotonrealtime.protocol.param.int8_param import Int8Parameter
from pyphotonrealtime.protocol.param.int32_param import Int32Parameter
from pyphotonrealtime.protocol.param.parameter_key import ParameterKey
from pyphotonrealtime.protocol.property_keys import GamePropertyKey
from pyphotonrealtime.realtime._convert import string_array, to_param
from pyphotonrealtime.server import GameServer, PhotonServer
from pyphotonrealtime.server.rooms import PROPS_LISTED_IN_LOBBY, Room

from src.protocol.rpc import build

# The game lists the host's name and the password flag in the lobby.
LOBBY_PROPERTIES = (
    GamePropertyKey.GameMaster.value.value,
    GamePropertyKey.PasswordProtected.value.value,
)
# Keep dropped players' slots, and empty rooms, around for reconnects (ms).
PLAYER_TTL = 180_000
EMPTY_ROOM_TTL = 300_000


SPOOF_ENV = "PA_SPOOF_HOST_CODES"


def spoofed_codes() -> frozenset[int]:
    """RPC codes whose sender is rewritten to the host (env ``PA_SPOOF_HOST_CODES``,
    comma-separated ints, e.g. ``118``). For testing against your own game only."""
    raw = os.environ.get(SPOOF_ENV, "")
    return frozenset(int(x) for x in raw.split(",") if x.strip().isdigit())


class PrisonArchitectGameServer(GameServer):
    """Caps room size and keeps rooms alive across reconnects."""

    def __init__(self, server: PhotonServer, max_players: int) -> None:
        super().__init__(server)
        self.max_players = max_players

    _spoofing = False

    def _capacity_properties(self, count: int) -> HashtableParameter:
        return HashtableParameter(
            {
                Int8Parameter(GamePropertyKey.MaxPlayers.value.value): Int8Parameter(
                    count
                ),
                Int8Parameter(
                    GamePropertyKey.MaxPlayersInt.value.value
                ): Int32Parameter(count),
            }
        )

    def set_capacity(self, count: int) -> int:
        """Set the player limit for new rooms and every room that exists.

        Players already inside stay; a full room just refuses further joins.
        Returns how many existing rooms were changed.
        """
        if not 1 <= count <= 16:
            raise ValueError("capacity must be between 1 and 16")
        self.max_players = count
        rooms = list(self.server.rooms.values())
        for room in rooms:
            room.properties.update(self._capacity_properties(count))
        return len(rooms)

    def inject_event(
        self,
        code: int,
        *args: object,
        to: str = "all",
        room: str | None = None,
    ) -> int:
        """Send RPC ``code(*args)`` to a room's players as if the host raised it.

        The layout is the one ``_raise_event`` relays (``ActorNr`` + ``Data``, the
        codec's bytes), with the master client as the sender, as in the spoofing
        above. ``to`` is ``all`` or ``host``; ``room`` limits it to one room
        (default: every room). Returns how many players were sent it. Raises
        ``RpcShapeError`` (a ``ValueError``) for arguments the RPC doesn't take.
        """
        if to not in ("all", "host"):
            raise ValueError("to must be all or host")
        data = to_param(build(code, *args))
        sent = 0
        for candidate in list(self.server.rooms.values()):
            if room is not None and candidate.name != room:
                continue
            master = candidate.actors.get(candidate.master_client_id)
            if master is None:
                continue
            event: Any = {
                ParameterKey.ActorNr: Int32Parameter(master.number),
                ParameterKey.Data: data,
            }
            receivers = [master] if to == "host" else list(candidate.active_actors())
            for actor in receivers:
                if actor.connection is not None and actor.is_active:
                    actor.connection.send_event(code, event, encrypt=True)
                    sent += 1
        return sent

    @override
    def _raise_event(
        self, connection: Any, operation: int, params: Any, *, encrypted: bool
    ) -> None:
        code = params.get(ParameterKey.Code)
        self._spoofing = code is not None and int(code.value) in spoofed_codes()
        try:
            super()._raise_event(connection, operation, params, encrypted=encrypted)
        finally:
            self._spoofing = False

    @override
    def _room_of(self, connection: Any) -> Any:
        """The sender of a spoofed event is the room's master client (the host)."""
        room, actor = super()._room_of(connection)
        if self._spoofing and room.master_client_id in room.actors:
            actor = room.actors[room.master_client_id]
        return room, actor

    @override
    def create_room(self, name: str, params: Any) -> Room:
        room = super().create_room(name, params)
        overrides: dict[Any, Any] = {
            Int8Parameter(GamePropertyKey.MaxPlayers.value.value): Int8Parameter(
                self.max_players
            ),
            Int8Parameter(GamePropertyKey.MaxPlayersInt.value.value): Int32Parameter(
                self.max_players
            ),
        }
        if not room.properties.get(PROPS_LISTED_IN_LOBBY):
            overrides[Int8Parameter(PROPS_LISTED_IN_LOBBY)] = string_array(
                LOBBY_PROPERTIES
            )
        room.properties.update(HashtableParameter(overrides))
        room.player_ttl = max(room.player_ttl, PLAYER_TTL)
        room.empty_room_ttl = max(room.empty_room_ttl, EMPTY_ROOM_TTL)
        return room
