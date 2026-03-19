from io import BytesIO
from typing import TYPE_CHECKING, Optional, cast

from server.photon.packet.operation_packet import PhotonOperationPacket
from server.photon.packet.operation_payload import PhotonPacketPayload

if TYPE_CHECKING:
    from server.photon.packet.header import PhotonDataPacketHeader


class DisconnectMessagePacket(PhotonOperationPacket):
    def __init__(
        self,
        header: "PhotonDataPacketHeader",
        payload: PhotonPacketPayload,
        aes_key: Optional[bytes] = None,
    ):
        super().__init__(header=header, payload=payload)

    @classmethod
    def from_bytes(
        cls,
        data: BytesIO,
        *,
        header: Optional["PhotonDataPacketHeader"] = None,
        aes_key: Optional[bytes] = None,
    ):
        return cast(
            DisconnectMessagePacket,
            super().from_bytes(
                data,
                header=header,
                aes_key=aes_key,
            ),
        )

    def log(self) -> list[str]:
        return [
            f"Command: {self.get_header().get_command_name()} {self.get_payload().get_operation_name()}",
            f"Reason: {self.get_payload().get_debug_message()}",
        ]
