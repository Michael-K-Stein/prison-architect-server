from enum import IntEnum


class PacketFormat(IntEnum):
    KeepAlive = 0xF0
    Data = 0xFB
