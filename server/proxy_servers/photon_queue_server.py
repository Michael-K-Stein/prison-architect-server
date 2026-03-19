from server.consts import ServerType
from server.local_servers.server_base import ServerBase


class PhotonQueueServer(ServerBase):
    def __init__(self, bind_interface: str, bind_port: int) -> None:
        super().__init__(bind_interface, bind_port)

    @classmethod
    def get_type(cls) -> ServerType:
        return ServerType.ProxyServer
