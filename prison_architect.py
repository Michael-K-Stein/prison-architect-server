"""Prison Architect on top of pyPhotonRealtime's self-hosted Photon server.

Everything generic (Name/Master/Game Server, rooms, events, properties) comes
from :class:`pyphotonrealtime.server.PhotonServer`. Only the game's own rules
live here.
"""

from __future__ import annotations

from typing import Any, override

from pyphotonrealtime.protocol.param.hashtable_param import HashtableParameter
from pyphotonrealtime.protocol.param.int8_param import Int8Parameter
from pyphotonrealtime.protocol.param.int32_param import Int32Parameter
from pyphotonrealtime.protocol.property_keys import GamePropertyKey
from pyphotonrealtime.realtime._convert import string_array
from pyphotonrealtime.server import PhotonServer
from pyphotonrealtime.server.connection import Role
from pyphotonrealtime.server.game_server import GameServer
from pyphotonrealtime.server.rooms import PROPS_LISTED_IN_LOBBY, Room

PRISON_ARCHITECT_APP_ID = "6f869876-bfbc-491e-8fff-4210c966f145"
# The game lists the host's name and the password flag in the lobby.
LOBBY_PROPERTIES = (
    GamePropertyKey.GameMaster.value.value,
    GamePropertyKey.PasswordProtected.value.value,
)
# Keep dropped players' slots, and empty rooms, around for reconnects (ms).
PLAYER_TTL = 180_000
EMPTY_ROOM_TTL = 300_000


class PrisonArchitectGameServer(GameServer):
    """Caps room size and keeps rooms alive across reconnects."""

    def __init__(self, server: PhotonServer, max_players: int) -> None:
        super().__init__(server)
        self.max_players = max_players

    @override
    def _create_room(self, name: str, params: Any) -> Room:
        room = super()._create_room(name, params)
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


class PrisonArchitectServer(PhotonServer):
    """A Photon server that only accepts Prison Architect."""

    def __init__(
        self,
        host: str = "0.0.0.0",  # noqa: S104
        *,
        public_host: str = "127.0.0.1",
        region: str = "local",
        max_players: int = 4,
        **ports: int,
    ) -> None:
        super().__init__(
            host,
            public_host=public_host,
            regions=(region,),
            app_id=PRISON_ARCHITECT_APP_ID,
            **ports,
        )
        self._handlers[Role.GameServer] = PrisonArchitectGameServer(self, max_players)
