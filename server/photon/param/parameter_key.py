from enum import IntEnum


class ParameterKey(IntEnum):
    """Parameters passed inside network Operations and Events."""

    GameId = 0xFF  # 255
    ActorNr = 0xFE  # 254
    TargetActorNr = 0xFD  # 253
    Actors = 0xFC  # 252
    Properties = 0xFB  # 251
    Broadcast = 0xFA  # 250
    ActorProperties = 0xF9  # 249
    GameProperties = 0xF8  # 248
    Cache = 0xF7  # 247
    ReceiverGroup = 0xF6  # 246
    Data = 0xF5  # 245
    Code = 0xF4  # 244
    Flush = 0xF3  # 243
    DeleteCacheOnLeave = 0xF1  # 241
    Group = 0xF0  # 240
    GroupsForRemove = 0xEF  # 239
    GroupsForAdd = 0xEE  # 238
    SuppressRoomEvents = 0xED  # 237
    EmptyRoomLiveTime = 0xEC  # 236
    PlayerTTL = 0xEB  # 235
    HttpForward = 0xEA  # 234
    WebFlags = 0xEA  # 234
    Address = 0xE6  # 230
    PeerCount = 0xE5  # 229
    GameCount = 0xE4  # 228
    MasterPeerCount = 0xE3  # 227
    UserId = 0xE1  # 225
    ApplicationId = 0xE0  # 224
    Position = 0xDF  # 223
    GameList = 0xDE  # 222
    Token = 0xDD  # 221
    AppVersion = 0xDC  # 220
    NodeId = 0xDB  # 219
    Info = 0xDA  # 218
    ClientAuthenticationType = 0xD9  # 217
    ClientAuthenticationParams = 0xD8  # 216
    CreateIfNotExists = 0xD7  # 215
    ClientAuthenticationData = 0xD6  # 214
    LobbyName = 0xD5  # 213
    LobbyType = 0xD4  # 212
    LobbyStats = 0xD3  # 211
    Region = 0xD2  # 210
    Nickname = 0xCA  # 202
    Flags = 0xC7  # 199
    CloudType = 0xC6  # 198
    GameRemoveReason = 0xC5  # 197
    Cluster = 0xC4  # 196
    ExpectedProtocol = 0xC3  # 195
    CustomInitData = 0xC2  # 194
    EncryptionMode = 0xC1  # 193
    EncryptionData = 0xC0  # 192
    AuthMode = 0xBF  # 191

    ClientKey = 1

    Null = 0
