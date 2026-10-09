"""Prison Architect on top of pyPhotonRealtime's self-hosted Photon server.

Everything generic (Name/Master/Game Server, rooms, events, properties) comes
from :class:`pyphotonrealtime.server.PhotonServer`. Only the game's own rules
live here.
"""

from __future__ import annotations

from functools import partial

from pyphotonrealtime.server import PhotonServer, Role

from src.server.game_server import PrisonArchitectGameServer

PRISON_ARCHITECT_APP_ID = "6f869876-bfbc-491e-8fff-4210c966f145"


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
