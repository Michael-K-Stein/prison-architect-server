import time
from typing import Callable

from server.consts import LISTEN_HOST
from server.log import print_info
from server.photon.packet.base import PhotonDataPacket
from server.photon.queue.photon_client_socket import PhotonClientSocket
from server.proxy_servers.photon_queue_client import PhotonQueueClient
from server.proxy_servers.photon_queue_server import PhotonQueueServer


class ProxyTunnel:
    _downstream_recieve_callback: Callable[[PhotonClientSocket, PhotonDataPacket], None]
    _upstream_recieve_callback: Callable[[PhotonClientSocket, PhotonDataPacket], None]

    def __init__(
        self,
        local_port: int,
        remote_ip: str,
        remote_port: int,
        downstream_recieve_callback: Callable[
            [PhotonClientSocket, PhotonDataPacket], None
        ],
        upstream_recieve_callback: Callable[
            [PhotonClientSocket, PhotonDataPacket], None
        ],
    ) -> None:

        self.local_port = local_port
        self.remote_ip = remote_ip
        self.remote_port = remote_port

        self.upstream = PhotonQueueClient(remote_ip, remote_port)
        self.downstream = PhotonQueueServer(LISTEN_HOST, local_port)

        self._downstream_recieve_callback = downstream_recieve_callback
        self._upstream_recieve_callback = upstream_recieve_callback

    def process(self):
        with self.upstream as upstream, self.downstream as downstream:
            while True:
                # Client -> Server
                # Client may be different for each packet if multiple games are connecting to our proxy
                # Each unique client needs a unique upstream
                for downstream_client, downstream_packet in downstream.process():
                    self._downstream_recieve_callback(
                        downstream_client, downstream_packet
                    )
                    print_info(
                        self.downstream.get_type(),
                        f"Proxying {downstream_packet.get_header().get_command_name()} from Client to Server",
                    )
                    upstream.push(downstream_packet)

                # Server -> Client
                for upstream_client, upstream_packet in upstream.process():
                    self._upstream_recieve_callback(upstream_client, upstream_packet)
                    print_info(
                        self.upstream.get_type(),
                        f"Proxying {upstream_packet.get_header().get_command_name()} from Server to Client",
                    )
                    downstream.push(upstream_packet)
                    upstream_packet = upstream.pop()

                time.sleep(0.01)
