from abc import ABC
from struct import pack
from typing import TYPE_CHECKING, List, Optional, cast
from io import BytesIO

from server.photon.packet.format import PacketFormat

if TYPE_CHECKING:
    from server.photon.packet.header import PhotonDataPacketHeader


class PhotonPacket(ABC):
    _packet_format: PacketFormat

    def __init__(self, packet_format: PacketFormat = PacketFormat.Data) -> None:
        self._packet_format = packet_format

    @classmethod
    def from_bytes(cls, data: BytesIO) -> "PhotonPacket":
        packet_format = cast(PacketFormat, int.from_bytes(data.read(1)))
        return cls(packet_format)

    def serialize(self) -> bytes:
        format_val = (
            self._packet_format.value
            if hasattr(self._packet_format, "value")
            else self._packet_format
        )
        return pack(">B", format_val)

    def get_format(self) -> PacketFormat:
        return self._packet_format

    def log(self) -> List[str]:
        return [
            f"Abstract Packet {self.get_format()}",
        ]


class PhotonDataPacket(PhotonPacket):
    _header: "PhotonDataPacketHeader"
    _data_length: Optional[int]

    def __init__(self, header: "PhotonDataPacketHeader") -> None:
        super().__init__(PacketFormat.Data)
        self._header = header
        self._data_length = None

    @classmethod
    def from_bytes(cls, data: BytesIO) -> "PhotonDataPacket":
        return cls(PhotonDataPacketHeader.from_bytes(data))

    def get_header(self) -> "PhotonDataPacketHeader":
        return self._header

    def resize(self, new_data_length: int) -> None:
        self._data_length = new_data_length

    def serialize(self) -> bytes:
        return super().serialize() + self._header.serialize(self._data_length)

    def log(self) -> List[str]:
        return [
            f"{self.get_header().get_command_name()}, Length: {self._data_length if self._data_length is not None else self.get_header().packet_length}"
        ]
