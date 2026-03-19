from io import BytesIO
from struct import Struct, pack
from typing import Optional, cast

from server.photon.command_code import CommandCode
from server.photon.packet.base import PhotonDataPacket
from server.photon.packet.header import PhotonDataPacketHeader
from server.photon.serialization_protocol import SerializationProtocol


class InitRequestPacket(PhotonDataPacket):
    ip_protocol: int
    serialization_protocol: SerializationProtocol
    app_id: str
    sdk_id: int

    def __init__(
        self,
        app_id: str,
        ip_protocol: int = 1,
        serialization_protocol: SerializationProtocol = SerializationProtocol.V6,
        sdk_id: int = 17,
        sdk_version: str = "4.1.11.0",
        header: Optional[PhotonDataPacketHeader] = None,
    ):
        if header is None:
            header = PhotonDataPacketHeader(command_code=CommandCode.Init)
        super().__init__(header)
        self.app_id = app_id
        self.ip_protocol = ip_protocol
        self.serialization_protocol = serialization_protocol
        self.sdk_version = sdk_version
        self.sdk_id = sdk_id

    @classmethod
    def from_bytes(
        cls,
        data: BytesIO,
        *,
        header: Optional[PhotonDataPacketHeader] = None,
    ):
        if header is not None and header.get_command_code() != CommandCode.Init:
            raise TypeError("Packet header is not of a init request!")

        # Byte 0: IP Protocol (1)
        # Byte 1: Serialization Protocol (6)
        # Byte 2: SDK ID (17)
        # Byte 3: Major/Minor Version
        # Byte 4: Patch Version
        # Bytes 5-6: Build Number
        header_struct = Struct(">BBBBBh")
        ip_protocol, serialization_version, sdk_id, major_minor, patch, build = (
            header_struct.unpack_from(data.read(header_struct.size))
        )

        major_version = major_minor >> 4
        minor_version = major_minor & 0x0F

        version_string = f"{major_version}.{minor_version}.{patch}.{build}"

        app_id = data.read(32)
        if len(app_id) != 32:
            raise ValueError("AppId is not 32 bytes!")

        return cls(
            app_id=app_id.decode(),
            sdk_id=sdk_id,
            sdk_version=version_string,
            serialization_protocol=cast(SerializationProtocol, serialization_version),
            ip_protocol=ip_protocol,
            header=header,
        )

    def serialize(self) -> bytes:
        parts = self.sdk_version.split(".")
        major = int(parts[0]) if len(parts) > 0 else 0
        minor = int(parts[1]) if len(parts) > 1 else 0
        patch = int(parts[2]) if len(parts) > 2 else 0
        build = int(parts[3]) if len(parts) > 3 else 0
        major_minor = (major << 4) | (minor & 0x0F)

        payload_header = pack(
            ">BBBBBh",
            self.ip_protocol,
            int(self.serialization_protocol),
            self.sdk_id,
            major_minor,
            patch,
            build,
        )

        app_id_bytes = self.app_id.encode("utf-8")
        serialized_payload = payload_header + app_id_bytes

        super().resize(len(serialized_payload))
        return super().serialize() + serialized_payload


class InitResponsePacket(PhotonDataPacket):
    def __init__(self, header: Optional[PhotonDataPacketHeader] = None):
        if header is None:
            header = PhotonDataPacketHeader(command_code=CommandCode.InitResponse)
        super().__init__(header)

    @classmethod
    def from_bytes(
        cls,
        data: BytesIO,
        *,
        header: Optional[PhotonDataPacketHeader] = None,
    ):
        if header is not None and header.get_command_code() != CommandCode.InitResponse:
            raise TypeError("Packet header is not of a init response!")

        content = data.read(1)
        assert content == b"\x00", f"Unexpected data in InitResponse! Got {content}"

        return cls(header)

    def serialize(self) -> bytes:
        super().resize(1)
        return super().serialize() + b"\x00"
