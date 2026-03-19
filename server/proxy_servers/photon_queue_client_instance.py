from socket import AF_INET, SOCK_STREAM, socket
from threading import Thread
from time import sleep, time
from types import TracebackType
from typing import Optional, Type

from server.consts import PRISON_ARCHITECT_APP_ID, ServerType
from server.log import (
    print_critical,
    print_debug,
    print_error,
    print_success,
    print_warning,
)
from server.photon.packet.init import InitRequestPacket
from server.photon.packet.keep_alive import PhotonKeepAliveRequest
from server.photon.packet.operation_packet import PhotonOperationPacket
from server.photon.queue.photon_client_socket import PhotonClientSocket
from server.proxy_servers.photon_queue_for_proxy import PhotonQueueForProxy


class PhotonQueueClientUpstreamInstance:
    """The upstream of a single client instance"""

    _sock: socket

    def __init__(
        self, client: PhotonClientSocket, remote_ip: str, remote_port: int
    ) -> None:
        self._client = client
        self._remote_ip = remote_ip
        self._remote_port = remote_port
        self._sock = socket(AF_INET, SOCK_STREAM)

        self._recv_worker = Thread(
            target=self._handle_recv,
            name="Client Recv Worker",
        )

        self._send_worker = Thread(
            target=self._handle_send,
            name="Client Send Worker",
        )

        self._keep_alive_worker = Thread(
            target=self._keep_alive_loop, name="Client Keep Alive Worker"
        )

    def __enter__(self):
        print_critical(
            self.get_type(), f"Connecting to {self._remote_ip}:{self._remote_port}"
        )
        self._sock.connect((self._remote_ip, self._remote_port))
        self._keep_alive_worker.start()
        self._send_init_request()

        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        self._recv_worker.join()
        self._send_worker.join()
        self._keep_alive_worker.join()
        self._sock.close()

    def _handle_recv(self):
        while not self._closing:
            try:
                self._recv_data(self._sock)
            except ConnectionAbortedError:
                print_error(
                    f"Receive from {self.remote_name} failed. ConnectionAbortedError"
                )
                self._reconnect()

    def _handle_send(self):
        while not self._closing:
            outgoing_packet = self._outgoing.get()
            self._recrypt(outgoing_packet)
            serialized_data = outgoing_packet.serialize()
            if isinstance(outgoing_packet, PhotonOperationPacket):
                msg = f"{outgoing_packet.get_header().get_command_name()}, Length: {len(serialized_data)}"
                print_debug(f"[{self.my_name} -> {self.remote_name}] {msg}")
            try:
                self._sock.sendall(serialized_data)
            except ConnectionAbortedError:
                print_error("Send Failed. ConnectionAbortedError")
                self._reconnect()
            except ConnectionResetError:
                print_error("Send Failed. ConnectionResetError: Server kicked us.")
                self._reconnect()

    def _keep_alive_loop(self):
        while not self._closing:
            self._outgoing.put(PhotonKeepAliveRequest(int(time())))
            sleep(1)

    def _send_init_request(self):
        self._outgoing.put(
            InitRequestPacket(app_id=PRISON_ARCHITECT_APP_ID.replace("-", ""))
        )

    @classmethod
    def get_type(cls) -> ServerType:
        return ServerType.UpstreamProxyServer
