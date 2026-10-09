from socket import (
    AF_INET,
    IPPROTO_TCP,
    SO_RCVBUF,
    SO_REUSEADDR,
    SO_SNDBUF,
    SOCK_STREAM,
    SOL_SOCKET,
    TCP_NODELAY,
    socket,
)
from threading import Lock, Thread, Event
from time import sleep
from types import TracebackType
from typing import Generator, List, Optional, Tuple, Type

from server.consts import ServerType
from server.log import print_error, print_success
from server.photon.operation_code import OperationCode
from server.photon.packet.base import PhotonDataPacket
from server.photon.queue.photon_client_socket import PhotonClientSocket
from server.photon.queue.upstream_router import route_or_local


class PhotonQueueDispatcher:
    _clients: List[PhotonClientSocket]
    _client_accepter_worker: Thread
    _global_keep_alive_worker: Thread
    _server_sock: socket
    _bind_if: str
    _bind_port: int
    _closing: bool
    _passthrough_upstream: Optional[str]
    _clients_lock: Lock
    _packet_ready_event: Event

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
        self._global_keep_alive_worker = Thread(
            target=self._keep_alive_loop, name="Global KeepAlive Worker"
        )
        self._packet_ready_event = Event()

        self._clients = []
        self._clients_lock = Lock()
        self._server_type = server_type

    def __enter__(self):
        self._server_sock.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
        self._server_sock.bind((self._bind_if, self._bind_port))
        self._server_sock.listen(64)
        print_success(
            self._server_type, f"Server listening on {self._bind_if}:{self._bind_port}"
        )

        self._client_accepter_worker.start()
        self._global_keep_alive_worker.start()

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
        self._global_keep_alive_worker.join(5)

    def _keep_alive_loop(self):
        while not self._closing:
            sleep(1)
            clients_snapshot = self.get_clients()
            for client in clients_snapshot:
                if not client.is_disconnected():
                    client._queue.check_keep_alive()

    def _client_accepter(self):
        while not self._closing:
            try:
                sock, addr = self._server_sock.accept()
            except OSError:
                if self._closing:
                    break
                continue

            try:
                # Disable Nagle's algorithm for instant packet transmission.
                # (Without modifying SO_RCVBUF to avoid loopback stalling on Windows).
                sock.setsockopt(IPPROTO_TCP, TCP_NODELAY, 1)

                print_success(
                    self._server_type, f"New client connected: {addr[0]}:{addr[1]}"
                )
                if self._passthrough_upstream is not None and route_or_local(
                    sock, addr, self._server_type, self._passthrough_upstream
                ):
                    continue  # socket now owned by the upstream relay threads
                with self._clients_lock:
                    self._clients.append(
                        PhotonClientSocket(
                            sock=sock, addr=addr, server_type=self._server_type, packet_ready_event=self._packet_ready_event
                        )
                    )
            except Exception as ex:
                print_error(
                    self._server_type,
                    f"Failed to initialize client {addr[0]}:{addr[1]}: {type(ex).__name__}: {ex}",
                )
                try:
                    sock.close()
                except OSError:
                    pass

    def process(
        self,
        do_not_handle: Optional[Tuple[OperationCode, ...]] = None,
    ) -> Generator[Tuple[PhotonClientSocket, PhotonDataPacket], None, None]:
        with self._clients_lock:
            self._clients = [
                client for client in self._clients if not client.is_disconnected()
            ]
            clients_snapshot = list(self._clients)

        for client in clients_snapshot:
            try:
                for packet_requiring_attention in client.process(
                    do_not_handle=do_not_handle
                ):
                    yield (client, packet_requiring_attention)
            except Exception as ex:
                print_error(
                    self._server_type,
                    f"Client processing failed for {client.get_address()}: {type(ex).__name__}: {ex}",
                )

    def get_clients(self) -> List[PhotonClientSocket]:
        with self._clients_lock:
            return list(self._clients)

    def wait_for_packets(self, timeout: float) -> None:
        self._packet_ready_event.wait(timeout)
        self._packet_ready_event.clear()
