from io import BytesIO
from typing import List, Optional

from server.photon.enum_lookups import get_parameter_key_name
from server.photon.packet.base import PhotonDataPacket
from server.photon.packet.header import PhotonDataPacketHeader
from server.photon.packet.operation_payload import (
    PhotonPacketEncryptedPayload,
    PhotonPacketPayload,
)


class PhotonOperationPacket(PhotonDataPacket):
    def __init__(
        self,
        header: PhotonDataPacketHeader,
        payload: PhotonPacketPayload,
        aes_key: Optional[bytes] = None,
    ) -> None:
        # Initialize the parent PhotonDataPacket with the already-parsed data
        super().__init__(header)
        self._operation_payload = payload
        self._aes_key = aes_key

    @classmethod
    def from_bytes(
        cls,
        data: BytesIO,
        *,
        header: Optional[PhotonDataPacketHeader] = None,
        aes_key: Optional[bytes] = None,
    ) -> "PhotonOperationPacket":
        if header is None:
            raise ValueError("Header is required for PhotonOperationPacket.from_bytes")
        if header.packet_length is None:
            raise ValueError('Header must contain "packet_length" field')

        payload_length = header.packet_length - header.data_offset()
        payload_data = data.read(payload_length)
        if len(payload_data) != payload_length:
            raise ValueError("Payload length does not match header")

        if header.is_encrypted():
            if aes_key is None:
                raise ValueError("Payload is encrypted but no AES key was given!")

            payload = PhotonPacketEncryptedPayload.from_bytes(
                header=header, data=payload_data
            ).decrypt(aes_key)
        else:
            payload = PhotonPacketPayload.from_bytes(header=header, data=payload_data)

        return cls(header=header, payload=payload, aes_key=aes_key)

    def get_payload(self):
        return self._operation_payload

    def serialize(self) -> bytes:
        serialized_payload = b""
        if self.get_header().is_encrypted():
            if self._aes_key is None:
                raise ValueError("No AES key provided!")
            serialized_payload = PhotonPacketEncryptedPayload.encrypt(
                self._operation_payload,
                self._aes_key,
            )
        else:
            serialized_payload = self._operation_payload.serialize()

        super().resize(len(serialized_payload))
        return super().serialize() + serialized_payload

    def set_aes_key(self, key: bytes) -> None:
        self._aes_key = key

    def log(self) -> List[str]:
        debug_data = (
            [
                f"Return Code: {self.get_payload().get_return_code()}",
                f"Debug Message: {self.get_payload().get_debug_message()}",
            ]
            if self.get_payload().response_debug_data is not None
            else []
        )

        encrypted = "No"
        if self.get_header().is_encrypted():
            assert self._aes_key is not None
            encrypted = f"Yes [{self._aes_key.hex()[:16]}]"

        return [
            f"Command: {self.get_header().get_command_name()}",
            f"Operation: {self.get_payload().get_operation_name()}",
            *debug_data,
            f"Encrypted: {encrypted}",
            f"Params[{len(self.get_payload().params)}]:",
        ] + [
            f"  {get_parameter_key_name(param_key)}: {param_val}"
            for param_key, param_val in self.get_payload().params.items()
        ]
