from threading import Thread
from time import sleep, time

from server.log import (
    print_critical,
)
from server.photon.packet.init import InitRequestPacket
from server.photon.packet.keep_alive import PhotonKeepAliveRequest
from server.photon.queue.photon_client_socket import PhotonClientSocket
from server.proxy_servers.photon_queue_for_proxy import (
    PhotonQueueForProxy,
)
from server.proxy_servers.proxy_queue_type import ProxyQueueType


class PhotonQueueUpstream(PhotonQueueForProxy):
    _app_id: str

    def __init__(
        self, client: PhotonClientSocket, remote_ip: str, remote_port: int, app_id: str
    ) -> None:
        super().__init__(ProxyQueueType.Upstream)
        self._client = client
        self._app_id = app_id
        self._remote_ip = remote_ip
        self._remote_port = remote_port

        self._keep_alive_worker = Thread(
            target=self._keep_alive_loop, name="Upstream Keep Alive Worker"
        )

    def __enter__(self):
        print_critical(
            self.get_type(), f"Connecting to {self._remote_ip}:{self._remote_port}"
        )
        self._sock.connect((self._remote_ip, self._remote_port))
        super_enter = super().__enter__()

        self._send_init_request()

        self._keep_alive_worker.start()

        return super_enter

    def _keep_alive_loop(self):
        while not self._closing:
            self._outgoing.put(PhotonKeepAliveRequest(int(time())))
            sleep(1)

    def _send_init_request(self):
        self._outgoing.put(InitRequestPacket(app_id=self._app_id.replace("-", "")))

    def process(self):
        packet = self.pop()
        while packet is not None:
            yield packet
            packet = self.pop()
