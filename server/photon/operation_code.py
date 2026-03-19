from enum import IntEnum


class OperationCode(IntEnum):
    DiffieHellmanRequest = 0
    DiffieHellmanResponse = 0x2A  # 42

    GetGameList = 0xD9  # 217
    Settings = 0xDA  # 218
    Rpc = 0xDB  # 219
    GetRegions = 0xDC  # 220
    LobbyStats = 0xDD  # 221
    FindFriends = 0xDE  # 222
    DebugGame = 0xDF  # 223

    JoinRandomGame = 0xE1  # 225
    JoinGame = 0xE2  # 226
    CreateGame = 0xE3  # 227
    LeaveLobby = 0xE4  # 228
    JoinLobby = 0xE5  # 229

    GameList = 0xE6  # 230
    Authenticate = 0xE6  # 230 (Alias for GameList)
    AuthOnce = 0xE7  # 231

    ChangeGroups = 0xF8  # 248
    Ping = 0xF9  # 249

    GetProperties = 0xFB  # 251
    SetProperties = 0xFC  # 252
    RaiseEvent = 0xFD  # 253
    Leave = 0xFE  # 254
    Join = 0xFF  # 255

    Event = 0xFF  # 255
