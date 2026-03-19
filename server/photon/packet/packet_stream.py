from io import BytesIO
from typing import Generator, Optional

from server.photon.command_code import CommandCode
from server.photon.packet.base import PhotonDataPacket, PhotonPacket
from server.photon.packet.disconnect import DisconnectMessagePacket
from server.photon.packet.format import PacketFormat
from server.photon.packet.header import PhotonDataPacketHeader
from server.photon.packet.init import InitRequestPacket, InitResponsePacket
from server.photon.packet.keep_alive import (
    PhotonKeepAliveRequest,
    PhotonKeepAliveResponse,
)
from server.photon.packet.key_exchange import (
    InitEncryptionRequest,
    InitEncryptionResponse,
)
from server.photon.packet.operation_packet import PhotonOperationPacket


class PhotonStreamParser:
    def __init__(self):
        # This persistent buffer survives across multiple socket.recv() calls
        self.buffer = bytearray()

    def feed(self, new_data: bytes) -> None:
        self.buffer.extend(new_data)

    def parse(
        self,
        *,
        expect_responses: bool = False,
        aes_key: Optional[bytes] = None,
    ) -> Generator[PhotonPacket, None, None]:

        datastream = BytesIO(self.buffer)

        while datastream.tell() < len(self.buffer):
            start_pos = datastream.tell()

            # Make sure we have enough bytes to even read the header format
            if len(self.buffer) - start_pos < 1:  # Assuming 1 byte minimum for format
                break

            photon_packet = PhotonPacket.from_bytes(datastream)

            if photon_packet.get_format() == PacketFormat.KeepAlive:
                if expect_responses:
                    if len(self.buffer) - start_pos < 9:
                        break
                    yield PhotonKeepAliveResponse.from_bytes(datastream)
                else:
                    if len(self.buffer) - start_pos < 5:
                        break
                    yield PhotonKeepAliveRequest.from_bytes(datastream)
            else:
                assert (
                    photon_packet.get_format() == PacketFormat.Data
                ), "Unexpected packet format!"

                # We need to peek/parse the header to know the required length
                if len(self.buffer) - start_pos < PhotonDataPacketHeader.size():
                    break  # Wait for more data
                data_header = PhotonDataPacketHeader.from_bytes(datastream)
                assert data_header.packet_length is not None, "Packet length is None!"

                if len(self.buffer) - start_pos < data_header.packet_length:
                    break  # Wait for more data

                content_data = datastream.read(
                    data_header.packet_length - data_header.size()
                )

                yield self._handle_data_packet(data_header, content_data, aes_key)

            # Slice off the bytes we just successfully parsed from the front of the buffer
            bytes_consumed = datastream.tell() - start_pos
            del self.buffer[:bytes_consumed]

            # Reset datastream to point to the new beginning of the buffer
            datastream = BytesIO(self.buffer)

    def _handle_data_packet(
        self,
        header: PhotonDataPacketHeader,
        data: bytes,
        aes_key: Optional[bytes] = None,
    ) -> PhotonDataPacket:
        datastream = BytesIO(data)
        if header.is_operation():
            return self._handle_operation_packet(header, datastream, aes_key)

        if header.get_command_code() == CommandCode.Init:
            return self._handle_data_init_packet(header, datastream)
        if header.get_command_code() == CommandCode.InitResponse:
            return self._handle_data_init_response_packet(header, datastream)

        raise ValueError(f"Unhandled command: {header.get_command_name()}")

    def _handle_data_init_packet(self, header: PhotonDataPacketHeader, data: BytesIO):
        return InitRequestPacket.from_bytes(data, header=header)

    def _handle_data_init_response_packet(
        self, header: PhotonDataPacketHeader, data: BytesIO
    ):
        return InitResponsePacket.from_bytes(data, header=header)

    def _handle_operation_packet(
        self,
        header: PhotonDataPacketHeader,
        data: BytesIO,
        aes_key: Optional[bytes] = None,
    ) -> "PhotonOperationPacket":
        if header.get_command_code() == CommandCode.DisconnectMessage:
            return DisconnectMessagePacket.from_bytes(
                data, header=header, aes_key=aes_key
            )

        if header.get_command_code() == CommandCode.KeyExchangeRequest:
            return InitEncryptionRequest.from_bytes(
                data, header=header, aes_key=aes_key
            )
        if header.get_command_code() == CommandCode.KeyExchangeResponse:
            return InitEncryptionResponse.from_bytes(
                data, header=header, aes_key=aes_key
            )

        return PhotonOperationPacket.from_bytes(data, header=header, aes_key=aes_key)
