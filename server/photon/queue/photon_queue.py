from queue import Empty, Queue
from socket import socket
from threading import Thread
from time import sleep, time
from types import TracebackType
from typing import Optional, Type

from server.consts import ServerType
from server.log import (
    print_debug,
    print_error,
    print_warning,
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
from server.settings import Settings


class PhotonQueue:
    _incoming: Queue["PhotonDataPacket"]
    _outgoing: Queue["PhotonPacket"]

    _sock: socket

    _closing: bool

    _aes_key: Optional[bytes]
    _private_key: Optional[int]

    _recv_worker: Thread
    _send_worker: Thread
    _check_keep_alive_worker: Thread

    _server_type: ServerType
    remote_name: str

    _last_keep_alive = 0
    _stream_parser: PhotonStreamParser

    def __init__(self, sock: socket, remote_name: str, server_type: ServerType) -> None:
        self._init_time = time()
        self._sock = sock
        self._closing = False
        self._aes_key = None
        self._server_type = server_type
        self.remote_name = remote_name
        self._incoming = Queue()
        self._outgoing = Queue()
        self._last_keep_alive = time()
        self._stream_parser = PhotonStreamParser()
        self._private_key = None

        self._recv_worker = Thread(
            target=self._handle_recv,
            name=f"Server Recv Worker ({server_type.value})",
        )
        self._send_worker = Thread(
            target=self._handle_send,
            name=f"Server Send Worker ({server_type.value})",
        )
        self._check_keep_alive_worker = Thread(
            target=self._check_keep_alive,
            name=f"Server KeepAlive Check Worker ({server_type.value})",
        )

    def get_aes_key(self) -> bytes | None:
        return self._aes_key

    def _recv_data(self, client_sock: socket):
        try:
            data = client_sock.recv(0x1000)
        except ConnectionResetError:
            print_error(self._server_type, "Failed to recieve! ConnectionResetError")
            sleep(0.1)
            return
        except OSError:
            return
        if len(data) == 0:
            return

        # The client may stop sending keep alives, but so long as they are active everything is fine.
        self._last_keep_alive = time()

        self._stream_parser.feed(data)

        for packet in self._stream_parser.parse(
            expect_responses=False,
            aes_key=self._aes_key,
        ):
            try:
                if isinstance(packet, PhotonKeepAlive):
                    self._handle_keep_alive(packet)
                    continue
                else:
                    assert isinstance(
                        packet, PhotonDataPacket
                    ), f'Expected "PhotonDataPacket", got {type(packet).__name__}'
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
                    self._server_type,
                    f"Failed to process packet from {self.remote_name}! Exception: {ex}, Raw: {packet.serialize().hex()}",
                )

    def set_aes_key(self, key: bytes) -> None:
        self._aes_key = key

    def __enter__(self):
        self._send_worker.start()
        self._recv_worker.start()
        self._check_keep_alive_worker.start()
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        try:
            self._sock.close()
        except Exception:
            pass
        self._closing = True
        self._recv_worker.join(5)
        self._send_worker.join(5)
        self._check_keep_alive_worker.join(5)

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
        server_pub_key, self._aes_key = generate_dh_keys(
            request_packet.get_public_key()
        )
        print_debug(self._server_type, f"AES Key: {self._aes_key.hex()}")

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

    def _check_keep_alive(self):
        while not self._closing:
            sleep(1)
            if time() - self._last_keep_alive > Settings().get_timeout():
                print_warning(
                    self._server_type,
                    f"{self.remote_name} timed out. Closing socket.",
                )
                self._sock.close()
                self._last_keep_alive = time()
                self._closing = True

    def _handle_send(self):
        while not self._closing:
            outgoing_packet = self._outgoing.get()
            self._recrypt(outgoing_packet)
            serialized_data = outgoing_packet.serialize()
            if isinstance(outgoing_packet, PhotonOperationPacket):
                msg = f"Sending: {outgoing_packet.get_header().get_command_name()}, Length: {len(serialized_data)}, Operation: {outgoing_packet.get_payload().get_operation_name()}"
                print_debug(
                    self._server_type,
                    msg,
                )
            try:
                self._sock.sendall(serialized_data)
            except ConnectionAbortedError:
                print_error(
                    self._server_type,
                    f"Failed to send! ConnectionAbortedError on {self.remote_name}",
                )
                self._closing = True
                return

    def _handle_recv(self):
        while not self._closing:
            try:
                self._recv_data(self._sock)
            except ConnectionAbortedError:
                print_error(
                    self._server_type,
                    f"Receive from {self.remote_name} failed. ConnectionAbortedError",
                )
                self._closing = True
                return
