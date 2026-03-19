from io import BytesIO
from typing import Optional, cast

from server.consts import MSG_MAGIC
from server.photon.command_code import CommandCode
from server.photon.enum_lookups import get_command_name


class PhotonDataPacketHeader:
    peer_id: bytes
    msg_magic: int
    command: "CommandCode"
    packet_length: Optional[int]

    def __init__(
        self,
        command_code: "CommandCode",
        peer_id: bytes = b"\x00\x01",
        msg_magic: int = MSG_MAGIC,
        packet_length: Optional[int] = None,
    ):
        self.peer_id = peer_id
        self.msg_magic = msg_magic
        self.command = command_code
        self.packet_length = packet_length

    def get_command_code(self):
        return self.command

    def get_command_name(self) -> str:
        return get_command_name(self.command)

    @staticmethod
    def from_bytes(data: BytesIO):
        length = int.from_bytes(data.read(4), byteorder="big", signed=False)

        packet_length = length
        peer_id = data.read(2)
        msg_magic = int.from_bytes(data.read(1))
        command = cast(CommandCode, int.from_bytes(data.read(1)))

        return PhotonDataPacketHeader(
            peer_id=peer_id,
            msg_magic=msg_magic,
            command_code=command,
            packet_length=packet_length,
        )

    def data_offset(self):
        return 9

    def is_encrypted(self) -> bool:
        return self.get_command_code() in (
            CommandCode.EncryptedOperation,
            CommandCode.EncryptedOperationResponse,
            CommandCode.EncryptedEvent,
        )

    def is_response(self) -> bool:
        return self.get_command_code() in (
            CommandCode.KeyExchangeResponse,
            CommandCode.EncryptedOperationResponse,
            CommandCode.OperationResponse,
            CommandCode.InitResponse,
        )

    def is_operation(self) -> bool:
        return self.get_command_code() in (
            CommandCode.Operation,
            CommandCode.OperationResponse,
            CommandCode.EncryptedOperation,
            CommandCode.EncryptedOperationResponse,
            CommandCode.Event,
            CommandCode.EncryptedEvent,
            CommandCode.DisconnectMessage,
            CommandCode.KeyExchangeRequest,
            CommandCode.KeyExchangeResponse,
        )

    def serialize(self, data_length: Optional[int] = None) -> bytes:
        command_byte = self.get_command_code().to_bytes(1)
        routing_header = self.peer_id + b"\xf3" + command_byte

        total_length = (
            (self.data_offset() + data_length)
            if data_length is not None
            else self.packet_length
        )
        if total_length is None:
            raise ValueError("Packet length is unknown!")

        tcp_envelope = total_length.to_bytes(4, byteorder="big")

        full_header = tcp_envelope + routing_header

        return full_header

    @staticmethod
    def size():
        return 9
