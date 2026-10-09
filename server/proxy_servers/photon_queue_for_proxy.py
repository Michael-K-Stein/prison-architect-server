from queue import Empty, Queue
from socket import AF_INET, SOCK_STREAM, socket
from threading import Thread
from time import time
from types import TracebackType
from typing import Optional, Type

from server.log import (
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
from server.proxy_servers.proxy_queue_type import ProxyQueueType


class PhotonQueueForProxy:
    """Base class for Photon Queues used for proxying traffic"""

    _incoming: Queue["PhotonDataPacket"]
    _outgoing: Queue["PhotonPacket"]

    _sock: socket

    _aes_key: Optional[bytes]
    _private_key: Optional[int]

    _recv_worker: Thread
    _send_worker: Thread

    _last_keep_alive = 0
    _stream_parser: PhotonStreamParser

    def __init__(self, proxy_type: ProxyQueueType) -> None:
        self._init_time = time()
        self._sock = socket(AF_INET, SOCK_STREAM)
        self._closing = False
        self._incoming = Queue()
        self._outgoing = Queue()
        self._stream_parser = PhotonStreamParser()
        self._aes_key = None
        self._private_key = None
        self._proxy_type = proxy_type

        self._recv_worker = Thread(
            target=self._recv_loop, name=f"{proxy_type.value} Recv Worker"
        )
        self._send_worker = Thread(
            target=self._send_loop, name=f"{proxy_type.value} Send Worker"
        )

    def _recv_loop(self) -> None:
        while not self._closing:
            try:
                self._recv_data(self._sock)
            except ConnectionAbortedError:
                print_error(self.get_type(), "Receive failed. ConnectionAbortedError")
                self._closing = True

    def _send_loop(self) -> None:
        while not self._closing:
            try:
                outgoing_packet = self._outgoing.get(timeout=0.5)
            except Empty:
                continue
            self._recrypt(outgoing_packet)
            try:
                self._sock.sendall(outgoing_packet.serialize())
            except (ConnectionAbortedError, ConnectionResetError) as ex:
                print_error(self.get_type(), f"Send failed. {type(ex).__name__}")
                self._closing = True

    def _recv_data(self, client_sock: socket):
        try:
            data = client_sock.recv(0x1000)
        except ConnectionResetError:
            print_error(self.get_type(), "Failed to recieve! ConnectionResetError")
            return
        except OSError:
            return
        if len(data) == 0:
            return

        self._stream_parser.feed(data)

        for packet in self._stream_parser.parse(
            expect_responses=self.get_type() == ProxyQueueType.Upstream,
            aes_key=self._aes_key,
        ):
            try:
                if isinstance(packet, PhotonKeepAlive):
                    self._handle_keep_alive(packet)
                    continue
                else:
                    assert isinstance(packet, PhotonDataPacket)
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
                    self.get_type(),
                    f"Failed to process packet! Exception: {ex}, Raw: {packet.serialize().hex()}",
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
        self._sock.close()
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
        print_info(self.get_type(), "    Diffie-Hellman Request")

        client_pub_key = request_packet.get_public_key()
        print_info(
            self.get_type(), f"    Client Public Key: {client_pub_key[:16].hex()}..."
        )

        server_pub_key, self._aes_key = generate_dh_keys(
            request_packet.get_public_key()
        )
        print_info(
            self.get_type(), f"    Server Public Key: {server_pub_key[:16].hex()}..."
        )
        print_info(
            self.get_type(), f"    Downstream AES Key: {self._aes_key[:16].hex()}..."
        )

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

    def get_type(self) -> ProxyQueueType:
        return self._proxy_type
