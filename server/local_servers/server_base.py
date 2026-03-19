from abc import ABC, abstractmethod
from types import TracebackType
from typing import Generator, Optional, Tuple, Type

from server.consts import ServerType
from server.photon.operation_code import OperationCode
from server.photon.packet.base import PhotonDataPacket
from server.photon.queue.photon_client_socket import PhotonClientSocket
from server.photon.queue.photon_queue_dispatcher import PhotonQueueDispatcher


class ServerBase(ABC):
    bind_ip: str
    bind_port: int
    _dispatcher: PhotonQueueDispatcher
    _listening: bool

    def __init__(self, bind_interface: str, bind_port: int):
        self.bind_ip = bind_interface
        self.bind_port = bind_port
        self._dispatcher = PhotonQueueDispatcher(
            self.get_type(), self.bind_ip, self.bind_port
        )
        self._listening = False

    def __enter__(self):
        self._listening = True
        self._dispatcher.__enter__()
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        self._listening = False
        self._dispatcher.__exit__(exc_type, exc_val, exc_tb)

    def process(
        self, do_not_handle: Optional[Tuple[OperationCode, ...]] = None
    ) -> Generator[Tuple[PhotonClientSocket, PhotonDataPacket], None, None]:
        for client, packet in self._dispatcher.process(do_not_handle=do_not_handle):
            yield client, packet

    @classmethod
    @abstractmethod
    def get_type(cls) -> ServerType:
        raise NotImplementedError()
