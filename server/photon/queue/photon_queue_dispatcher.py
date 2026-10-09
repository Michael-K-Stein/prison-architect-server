from socket import AF_INET, SO_REUSEADDR, SOCK_STREAM, SOL_SOCKET, socket
from threading import Thread
from types import TracebackType
from typing import Generator, List, Optional, Tuple, Type

from server.consts import ServerType
from server.log import print_success
from server.photon.operation_code import OperationCode
from server.photon.packet.base import PhotonDataPacket
from server.photon.queue.photon_client_socket import PhotonClientSocket
from server.photon.queue.upstream_router import route_or_local


class PhotonQueueDispatcher:
    _clients: List[PhotonClientSocket]
    _client_accepter_worker: Thread
    _server_sock: socket
    _bind_if: str
    _bind_port: int
    _closing: bool
    _passthrough_upstream: Optional[str]

    def __init__(
        self,
        server_type: ServerType,
        bind_interface: str,
        bind_port: int,
        passthrough_upstream: Optional[str] = None,
    ) -> None:
        self._server_sock = socket(AF_INET, SOCK_STREAM)
        self._bind_if = bind_interface
        self._bind_port = bind_port
        self._closing = False
        # None disables the feature; otherwise "auto" or "host[:port]" --
        # non-Prison-Architect clients are relayed to the real Photon cloud.
        self._passthrough_upstream = passthrough_upstream

        self._client_accepter_worker = Thread(
            target=self._client_accepter, name="Client Accepter Worker"
        )

        self._clients = []
        self._server_type = server_type

    def __enter__(self):
        self._server_sock.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
        self._server_sock.bind((self._bind_if, self._bind_port))
        self._server_sock.listen(5)
        print_success(
            self._server_type, f"Server listening on {self._bind_if}:{self._bind_port}"
        )

        self._client_accepter_worker.start()

        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        self._closing = True
        try:
            # shutdown() first: close() alone does not unblock a thread
            # stuck in accept() (it holds its own socket reference).
            self._server_sock.shutdown(2)  # SHUT_RDWR
        except Exception:
            pass
        try:
            self._server_sock.close()
        except Exception:
            pass
        self._client_accepter_worker.join(5)

    def _client_accepter(self):
        while not self._closing:
            try:
                sock, addr = self._server_sock.accept()
            except OSError:
                break  # listening socket was shut down; exit the loop quietly
            print_success(
                self._server_type, f"New client connected: {addr[0]}:{addr[1]}"
            )
            if self._passthrough_upstream is not None and route_or_local(
                sock, addr, self._server_type, self._passthrough_upstream
            ):
                continue  # socket now owned by the upstream relay threads
            self._clients.append(
                PhotonClientSocket(sock=sock, addr=addr, server_type=self._server_type)
            )

    def process(
        self,
        do_not_handle: Optional[Tuple[OperationCode, ...]] = None,
    ) -> Generator[Tuple[PhotonClientSocket, PhotonDataPacket], None, None]:
        for client in self._clients:
            for packet_requiring_attention in client.process(
                do_not_handle=do_not_handle
            ):
                yield (client, packet_requiring_attention)

    def get_clients(self) -> List[PhotonClientSocket]:
        return self._clients
