"""The Prison Architect game server: room caps and reconnect-friendly TTLs."""

from __future__ import annotations

import os
from typing import Any, override

from pyphotonrealtime.protocol.param.hashtable_param import HashtableParameter
from pyphotonrealtime.protocol.param.int8_param import Int8Parameter
from pyphotonrealtime.protocol.param.int32_param import Int32Parameter
from pyphotonrealtime.protocol.param.parameter_key import ParameterKey
from pyphotonrealtime.protocol.property_keys import GamePropertyKey
from pyphotonrealtime.realtime._convert import string_array
from pyphotonrealtime.server import GameServer, PhotonServer
from pyphotonrealtime.server.rooms import PROPS_LISTED_IN_LOBBY, Room

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
