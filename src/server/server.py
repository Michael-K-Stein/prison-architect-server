"""Prison Architect on top of pyPhotonRealtime's self-hosted Photon server.

Everything generic (Name/Master/Game Server, rooms, events, properties) comes
from :class:`pyphotonrealtime.server.PhotonServer`. Only the game's own rules
live here.
"""

from __future__ import annotations

import json
import logging
import urllib.request
from functools import partial
from typing import Any, override

from pyphotonrealtime.protocol.param.hashtable_param import HashtableParameter
from pyphotonrealtime.protocol.param.int8_param import Int8Parameter
from pyphotonrealtime.protocol.param.int32_param import Int32Parameter
from pyphotonrealtime.protocol.property_keys import GamePropertyKey
from pyphotonrealtime.realtime._convert import string_array
from pyphotonrealtime.server import GameServer, PhotonServer, Role
from pyphotonrealtime.server.rooms import PROPS_LISTED_IN_LOBBY, Room

log = logging.getLogger(__name__)

PRISON_ARCHITECT_APP_ID = "6f869876-bfbc-491e-8fff-4210c966f145"
# The game lists the host's name and the password flag in the lobby.
LOBBY_PROPERTIES = (
    GamePropertyKey.GameMaster.value.value,
    GamePropertyKey.PasswordProtected.value.value,
)
# Keep dropped players' slots, and empty rooms, around for reconnects (ms).
PLAYER_TTL = 180_000
EMPTY_ROOM_TTL = 300_000
# The real Photon Name Server, for other games' traffic. Resolved over
# DNS-over-HTTPS: the hosts-file redirect points the name itself at us.
NAME_SERVER_HOST = "ns.exitgames.com"
NAME_SERVER_FALLBACK_IP = "216.120.180.54"
NAME_SERVER_PORT = 4533
_DOH_URLS = (
    f"https://dns.google/resolve?name={NAME_SERVER_HOST}&type=A",
    f"https://cloudflare-dns.com/dns-query?name={NAME_SERVER_HOST}&type=A",
)


def resolve_upstream(spec: str | None = None) -> tuple[str, int]:
    """The Name Server other Photon games are relayed to.

    ``spec`` is ``host`` or ``host:port``; None or ``"auto"`` resolves the
    current IP of ns.exitgames.com via DNS-over-HTTPS, falling back to a
    known address.
    """
    if spec and spec != "auto":
        host, _, port = spec.partition(":")
        return host, int(port) if port else NAME_SERVER_PORT
    for url in _DOH_URLS:
        request = urllib.request.Request(
            url, headers={"Accept": "application/dns-json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310
                answer = json.loads(response.read())
        except (OSError, ValueError):
            continue
        for record in answer.get("Answer", []):
            if record.get("type") == 1 and record.get("data"):
                return record["data"], NAME_SERVER_PORT
    log.warning(
        "could not resolve %s; using %s", NAME_SERVER_HOST, NAME_SERVER_FALLBACK_IP
    )
    return NAME_SERVER_FALLBACK_IP, NAME_SERVER_PORT


class PrisonArchitectGameServer(GameServer):
    """Caps room size and keeps rooms alive across reconnects."""

    def __init__(self, server: PhotonServer, max_players: int) -> None:
        super().__init__(server)
        self.max_players = max_players

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


class PrisonArchitectServer(PhotonServer):
    """A Photon server that only serves Prison Architect.

    Other Photon games' connections are relayed to ``upstream`` (the real
    Name Server), so the hosts-file redirect doesn't break them.
    """

    def __init__(
        self,
        host: str = "0.0.0.0",  # noqa: S104
        *,
        public_host: str = "127.0.0.1",
        region: str = "local",
        max_players: int = 4,
        upstream: tuple[str, int] | None = None,
        idle_timeout: float | None = None,
        **ports: int,
    ) -> None:
        super().__init__(
            host,
            public_host=public_host,
            regions=(region,),
            app_id=PRISON_ARCHITECT_APP_ID,
            passthrough=upstream,
            idle_timeout=idle_timeout,
            handlers={
                Role.GameServer: partial(
                    PrisonArchitectGameServer, max_players=max_players
                )
            },
            **ports,
        )
