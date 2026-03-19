from queue import Empty, Queue
from socket import AF_INET, SOCK_STREAM, socket
from threading import Thread
from time import sleep, time
from types import TracebackType
from typing import Optional, Type

from server.log import (
    print_debug,
    print_error,
    print_info,
)
from server.photon.packet.base import PhotonDataPacket, PhotonPacket
from server.photon.packet.init import InitRequestPacket, InitResponsePacket
from server.photon.packet.keep_alive import (
    PhotonKeepAlive,
    PhotonKeepAliveRequest,
    PhotonKeepAliveResponse,
)
from server.photon.packet.key_exchange import (
    InitEncryptionRequest,
    InitEncryptionResponse,
)
from server.photon.packet.operation_packet import PhotonOperationPacket
from server.photon.packet.packet_stream import PhotonStreamParser
from server.photon.photon_enc import (
    build_dh_request,
    generate_dh_keys,
    process_dh_response,
)


class PhotonQueueForProxy:  # TODO: Delete this
    _incoming: Queue["PhotonDataPacket"]
    _outgoing: Queue["PhotonPacket"]

    _sock: socket

    _closing: bool

    _aes_key: Optional[bytes]
    _private_key: Optional[int]

    _recv_worker: Thread
    _send_worker: Thread
    my_name: str
    remote_name: str

    _last_keep_alive = 0
    _stream_parser: PhotonStreamParser

    def __init__(self, my_name: str, remote_name: str) -> None:
        self._init_time = time()
        self._sock = socket(AF_INET, SOCK_STREAM)
        self._closing = False
        self._aes_key = None
        self.my_name = my_name
        self.remote_name = remote_name
        self._incoming = Queue()
        self._outgoing = Queue()
        self._last_keep_alive = time()
        self._stream_parser = PhotonStreamParser()
        self._private_key = None

    def _recv_data(self, client_sock: socket):
        try:
            data = client_sock.recv(0x12000)
        except ConnectionResetError:
            print_error("Failed to recieve! ConnectionResetError")
            sleep(0.1)
            return
        except OSError:
            return
        if len(data) == 0:
            return
        hdr = f"[{self.remote_name} -> {self.my_name}]"
        print_debug(f"{hdr} Recieved {len(data)} bytes")
        self._stream_parser.feed(data)

        for packet in self._stream_parser.parse(
            expect_responses=self.remote_name == "Server",
            aes_key=self._aes_key,
        ):
            try:
                if isinstance(packet, PhotonKeepAlive):
                    self._handle_keep_alive(packet)
                    continue
                else:
                    assert isinstance(packet, PhotonDataPacket)
                    print_debug(
                        f"{hdr} {packet.get_header().get_command_name()}, Length: {packet.get_header().packet_length}"
                    )
                    if isinstance(packet, InitResponsePacket):
                        self._handle_init_response(packet)
                        continue
                    elif isinstance(packet, InitRequestPacket):
                        self._handle_init_request(packet)
                        continue
                    if isinstance(packet, InitEncryptionRequest):
                        self._outgoing.put(self._handle_dh_request(packet))
                        continue
                    elif isinstance(packet, InitEncryptionResponse):
                        self._handle_dh_response(packet)
                        continue
                    self._incoming.put(packet)
            except RuntimeError as ex:
                print_error(
                    f"{hdr} Failed to process packet! Exception: {ex}, Raw: {packet.serialize().hex()}"
                )

    def set_aes_key(self, key: bytes) -> None:
        self._aes_key = key

    def __enter__(self):
        self._send_worker.start()
        self._recv_worker.start()
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        self._closing = True
        self._recv_worker.join(5)
        self._send_worker.join(5)

    def pop(self) -> PhotonDataPacket | None:
        if self._incoming.empty():
            return None
        try:
            return self._incoming.get_nowait()
        except Empty:
            return None

    def push(self, packet: PhotonPacket) -> None:
        self._outgoing.put(packet)

    def _handle_dh_request(self, request_packet: InitEncryptionRequest):
        print_info("    Diffie-Hellman Request")

        client_pub_key = request_packet.get_public_key()
        print_info(f"    Client Public Key: {client_pub_key[:16].hex()}...")

        server_pub_key, self._aes_key = generate_dh_keys(
            request_packet.get_public_key()
        )
        print_info(f"    Server Public Key: {server_pub_key[:16].hex()}...")
        print_info(f"    Downstream AES Key: {self._aes_key[:16].hex()}...")

        return InitEncryptionResponse(public_key=server_pub_key)

    def craft_dh_request(self) -> InitEncryptionRequest:
        self._private_key, encryption_request_packet = build_dh_request(
            self._private_key
        )
        return encryption_request_packet

    def _handle_dh_response(self, response_packet: InitEncryptionResponse) -> None:
        if self._private_key is None:
            raise ValueError("Private key not initialized!")
        self._aes_key = process_dh_response(self._private_key, response_packet)

    def _recrypt(self, packet: PhotonPacket) -> None:
        if not isinstance(packet, PhotonOperationPacket):
            return
        if not packet.get_header().is_encrypted():
            return
        if self._aes_key is None:
            raise RuntimeError("Cannot send encrypted packets without AES key!")
        packet.set_aes_key(self._aes_key)

    def _handle_keep_alive(self, packet: PhotonKeepAlive) -> None:
        if isinstance(packet, PhotonKeepAliveResponse):
            return
        assert isinstance(packet, PhotonKeepAliveRequest)
        self._last_keep_alive = time()
        self._outgoing.put(
            PhotonKeepAliveResponse(self.get_uptime(), packet.get_client_time())
        )

    def get_uptime(self) -> int:
        return int(time() - self._init_time)

    def _handle_init_response(self, _packet: InitResponsePacket) -> None:
        dh_req = self.craft_dh_request()
        self.push(dh_req)

    def _handle_init_request(self, _packet: InitRequestPacket) -> None:
        self.push(InitResponsePacket())
