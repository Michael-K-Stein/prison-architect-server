from typing import TYPE_CHECKING, Any, Optional, Tuple

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

from server.photon.deserializer import deserialize_photon_payload
from server.photon.enum_lookups import get_operation_name
from server.photon.param.nil_param import NilParameter
from server.photon.param.string_param import StringParameter
from server.photon.serializer import serialize_photon_payload

if TYPE_CHECKING:
    from server.photon.enum_lookups import CommandParams
    from server.photon.operation_code import OperationCode
    from server.photon.packet.header import PhotonDataPacketHeader
    from server.photon.param.base import ParameterBase


def _decrypt_data(encrypted_data: bytes, aes_key: bytes) -> bytes:
    iv = bytes(16)
    cipher = AES.new(aes_key, AES.MODE_CBC, iv)  # type: ignore
    padded_plaintext = cipher.decrypt(encrypted_data)
    plaintext = unpad(padded_plaintext, AES.block_size)
    return plaintext


def _encrypt_data(plaintext: bytes, aes_key: bytes) -> bytes:
    iv = bytes(16)
    cipher = AES.new(aes_key, AES.MODE_CBC, iv)  # type: ignore
    padded_plaintext = pad(plaintext, AES.block_size)
    ciphertext = cipher.encrypt(padded_plaintext)
    return ciphertext


class PhotonPacketPayload:
    params: "CommandParams"
    operation_code: "OperationCode"
    response_debug_data: Tuple[int, "ParameterBase[Any]"] | None
    header: "PhotonDataPacketHeader"

    def __init__(
        self,
        operation_code: "OperationCode",
        params: "CommandParams",
        header: "PhotonDataPacketHeader",
        response_debug_data: Optional[Tuple[int, "ParameterBase[Any]"]] = None,
    ):
        self.operation_code = operation_code
        self.params = params
        self.response_debug_data = response_debug_data
        self.header = header

    @staticmethod
    def from_bytes(header: "PhotonDataPacketHeader", data: bytes):
        operation_code, params, response_debug_data = deserialize_photon_payload(
            header,
            data,
        )
        payload = PhotonPacketPayload(
            operation_code=operation_code,
            params=params,
            response_debug_data=response_debug_data,
            header=header,
        )
        return payload

    def serialize(self) -> bytes:
        if hasattr(self, "_cached_serialized"):
            return self._cached_serialized

        serialized_data = serialize_photon_payload(
            self.operation_code,
            self.params,
            self.response_debug_data,
            header=self.header,
        )
        self._cached_serialized = serialized_data
        return serialized_data

    def get_operation_name(self) -> str:
        return get_operation_name(self.operation_code)

    def get_return_code(self) -> int | None:
        return (
            self.response_debug_data[0]
            if self.response_debug_data is not None
            else None
        )

    def get_debug_message(self) -> str | None:
        if self.response_debug_data is None or isinstance(
            self.response_debug_data[1], NilParameter
        ):
            return None
        if not isinstance(self.response_debug_data[1], StringParameter):
            raise TypeError("Debug message is not a string!")
        return self.response_debug_data[1].value


class PhotonPacketEncryptedPayload:
    raw: bytes
    is_response: bool
    header: "PhotonDataPacketHeader"

    @staticmethod
    def from_bytes(header: "PhotonDataPacketHeader", data: bytes):
        packet = PhotonPacketEncryptedPayload()
        packet.raw = data
        packet.header = header
        return packet

    def decrypt(self, aes_key: bytes) -> "PhotonPacketPayload":
        plaintext = _decrypt_data(self.raw, aes_key)
        return PhotonPacketPayload.from_bytes(header=self.header, data=plaintext)

    @staticmethod
    def encrypt(
        payload: "PhotonPacketPayload",
        aes_key: bytes,
    ) -> bytes:
        return _encrypt_data(
            payload.serialize(),
            aes_key,
        )
