from enum import IntEnum
from typing import Any


class PrisonArchitectEventCode(IntEnum):
    """
    Reverse-engineered custom Photon event codes for Prison Architect.
    Photon custom events are strictly in the 1-199 range.
    """

    PlayerJoin_Unknown = 2  # Suspected Player Join
    PasswordAuthRequest = 5
    KickPlayer = 6 # Soft kick, just asks the client to leave
    WorldUpdate = 9
    TickSpeedUpdate = 96

    # Placeholders for identified but unmapped events
    Unknown1 = 1
    Unknown3 = 3
    Unknown4 = 4
    Unknown8 = 8
    Unknown13 = 13
    Unknown14 = 14
    Unknown47 = 47
    Unknown89 = 89
    Unknown95 = 95
    Unknown118 = 118

    @classmethod
    def _missing_(cls, value: Any):
        """
        Gracefully handles unknown event codes intercepted from the network
        so your parser doesn't crash on undocumented events.
        """
        # You can create a dynamic generic member or just return the raw integer
        # so your script keeps running while you log the new code.
        return int(value)


class EventCode(IntEnum):
    GameList = 0xE6  # 230
    GameListUpdate = 0xE5
    QueueState = 0xE4
    AppStats = 0xE2  # 226
    GameServerOffline = 0xE1
    LobbyStats = 0xE0
    AuthEvent = 0xDF

    Event = 0xFF

    @classmethod
    def _missing_(cls, value: Any):
        """
        Gracefully handles unknown event codes intercepted from the network
        so your parser doesn't crash on undocumented events.
        """
        # You can create a dynamic generic member or just return the raw integer
        # so your script keeps running while you log the new code.
        value = int(value)
        if value > 0 and value <= 200:
            return PrisonArchitectEventCode(value)
        return value
