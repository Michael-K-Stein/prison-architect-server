from enum import Enum

from server.photon.param.int8_param import Int8Parameter
from server.photon.param.string_param import StringParameter


class ActorPropertyKey(Enum):
    """Properties attached to a specific player/actor."""

    PlayerName = Int8Parameter(255)
    IsInactive = Int8Parameter(254)
    UserId = Int8Parameter(253)
    Ping = StringParameter("P")
    Color = StringParameter("C")


class GamePropertyKey(Enum):
    """Properties attached to the room/game state."""

    MaxPlayers = Int8Parameter(255)
    IsVisible = Int8Parameter(254)
    IsOpen = Int8Parameter(253)
    PlayerCount = Int8Parameter(252)
    Removed = Int8Parameter(251)
    PropsListedInLobby = Int8Parameter(250)
    CleanupCacheOnLeave = Int8Parameter(249)
    MasterClientId = Int8Parameter(248)
    ExpectedUsers = Int8Parameter(247)
    PlayerTtl = Int8Parameter(246)
    EmptyRoomTtl = Int8Parameter(245)
    MaxPlayersInt = Int8Parameter(243)

    # Prison Architect Specific Properties
    PasswordProtected = StringParameter("PA")
    GameMaster = StringParameter("MAS")
