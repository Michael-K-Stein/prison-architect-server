from io import BytesIO
from struct import pack
from server.photon.packet.base import PhotonPacket
from server.photon.packet.format import PacketFormat


class PhotonKeepAlive(PhotonPacket):
    _client_time: int

    def __init__(self, client_time: int) -> None:
        super().__init__(PacketFormat.KeepAlive)
        self._client_time = client_time

    def get_client_time(self) -> int:
        return self._client_time


class PhotonKeepAliveRequest(PhotonKeepAlive):
    def __init__(self, client_time: int):
        super().__init__(client_time=client_time)

    @classmethod
    def from_bytes(cls, data: BytesIO) -> "PhotonKeepAliveRequest":
        client_time = int.from_bytes(data.read(4), byteorder="big")
        return cls(client_time=client_time)

    def serialize(self) -> bytes:
        return super().serialize() + pack(">I", self._client_time)


class PhotonKeepAliveResponse(PhotonKeepAlive):
    _server_uptime: int

    def __init__(self, server_uptime: int, client_time: int):
        super().__init__(client_time=client_time)
        self._server_uptime = server_uptime

    @classmethod
    def from_bytes(cls, data: BytesIO) -> "PhotonKeepAliveResponse":
        server_uptime = int.from_bytes(data.read(4), byteorder="big")
        client_time = int.from_bytes(data.read(4), byteorder="big")
        return cls(server_uptime=server_uptime, client_time=client_time)

    def serialize(self) -> bytes:
        return super().serialize() + pack(">II", self._server_uptime, self._client_time)

    def get_server_uptime(self) -> int:
        return self._server_uptime
