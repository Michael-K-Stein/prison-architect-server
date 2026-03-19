from io import BytesIO
from typing import TYPE_CHECKING, Optional, cast

from server.photon.command_code import CommandCode
from server.photon.operation_code import OperationCode
from server.photon.packet.header import PhotonDataPacketHeader
from server.photon.packet.operation_packet import PhotonOperationPacket
from server.photon.packet.operation_payload import PhotonPacketPayload
from server.photon.param.int8_slice_param import Int8SliceParameter
from server.photon.param.parameter_key import ParameterKey

if TYPE_CHECKING:
    from server.photon.packet.header import PhotonDataPacketHeader


def _extract_public_key(packet: PhotonOperationPacket) -> bytes:
    pub_key = packet.get_payload().params.get(ParameterKey.ClientKey, None)
    if pub_key is None:
        raise ValueError("No public key found!")
    return pub_key.value


class KeyExchangePacket(PhotonOperationPacket):
    _public_key_bytes: bytes

    def __init__(
        self,
        *,
        header: "PhotonDataPacketHeader",
        public_key: Optional[Int8SliceParameter | bytes] = None,
        payload: Optional[PhotonPacketPayload] = None,
        aes_key: Optional[bytes] = None,
    ):
        if payload is None and public_key is None:
            raise ValueError("Payload and public key cannot both be None!")

        client_key: Optional[Int8SliceParameter] = None
        if type(public_key) is bytes:
            client_key = Int8SliceParameter(public_key)
        elif type(public_key) is Int8SliceParameter:
            client_key = public_key

        assert client_key is not None or payload is not None

        if payload is not None and public_key is not None:
            assert client_key is not None
            payload.params[ParameterKey.ClientKey] = client_key

        if payload is None:
            assert client_key is not None
            payload = PhotonPacketPayload(
                operation_code=(
                    OperationCode.DiffieHellmanRequest
                    if header.command == CommandCode.KeyExchangeRequest
                    else OperationCode.DiffieHellmanResponse
                ),
                params={
                    ParameterKey.ClientKey: client_key,
                },
                header=header,
            )
        super().__init__(header=header, payload=payload)
        self._public_key = (
            cast(bytes, client_key.value)
            if client_key is not None
            else _extract_public_key(super())
        )

    @classmethod
    def from_bytes(
        cls,
        data: BytesIO,
        *,
        header: Optional["PhotonDataPacketHeader"] = None,
        aes_key: Optional[bytes] = None,
    ):
        # Key exchange implicitly implies that the packet is both unencrypted, and that whatever AES key was passed here is now irrelevant
        packet = super().from_bytes(
            data,
            header=header,
            aes_key=None,
        )

        return cls(header=packet.get_header(), public_key=_extract_public_key(packet))

    def get_public_key(self) -> bytes:
        return self._public_key

    def get_public_key_int(self) -> int:
        return int.from_bytes(self._public_key, byteorder="big", signed=False)


class InitEncryptionRequest(KeyExchangePacket):
    def __init__(
        self,
        *,
        public_key: Optional[Int8SliceParameter | bytes] = None,
        header: Optional["PhotonDataPacketHeader"] = None,
        payload: Optional[PhotonPacketPayload] = None,
        aes_key: Optional[bytes] = None,
    ):
        super().__init__(
            header=(
                header
                if header is not None
                else PhotonDataPacketHeader(command_code=CommandCode.KeyExchangeRequest)
            ),
            public_key=public_key,
            payload=payload,
        )

    @classmethod
    def from_bytes(
        cls,
        data: BytesIO,
        *,
        header: Optional["PhotonDataPacketHeader"] = None,
        aes_key: Optional[bytes] = None,
    ):
        return cast(
            InitEncryptionRequest,
            super().from_bytes(
                data,
                header=header,
                aes_key=None,
            ),
        )


class InitEncryptionResponse(KeyExchangePacket):
    def __init__(
        self,
        *,
        public_key: Optional[Int8SliceParameter | bytes] = None,
        header: Optional["PhotonDataPacketHeader"] = None,
        payload: Optional[PhotonPacketPayload] = None,
        aes_key: Optional[bytes] = None,
    ):
        super().__init__(
            header=(
                header
                if header is not None
                else PhotonDataPacketHeader(
                    command_code=CommandCode.KeyExchangeResponse
                )
            ),
            public_key=public_key,
            payload=payload,
        )

    @classmethod
    def from_bytes(
        cls,
        data: BytesIO,
        *,
        header: Optional["PhotonDataPacketHeader"] = None,
        aes_key: Optional[bytes] = None,
    ):
        # Key exchange implicitly implies that the packet is both unencrypted, and that whatever AES key was passed here is now irrelevant
        return cast(
            InitEncryptionResponse,
            super().from_bytes(
                data,
                header=header,
                aes_key=None,
            ),
        )
