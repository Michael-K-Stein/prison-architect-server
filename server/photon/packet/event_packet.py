from typing import Optional

from server.photon.command_code import CommandCode
from server.photon.packet.header import PhotonDataPacketHeader
from server.photon.packet.operation_packet import PhotonOperationPacket
from server.photon.packet.operation_payload import (
    PhotonPacketPayload,
)


class PhotonEventPacket(PhotonOperationPacket):
    def __init__(
        self,
        header: PhotonDataPacketHeader,
        payload: PhotonPacketPayload,
        aes_key: Optional[bytes] = None,
    ) -> None:
        super().__init__(header=header, payload=payload, aes_key=aes_key)
        if header.get_command_code() not in (
            CommandCode.Event,
            CommandCode.EncryptedEvent,
        ):
            raise TypeError("Packet is not an Event!")
        self._operation_payload = payload
        self._aes_key = aes_key
