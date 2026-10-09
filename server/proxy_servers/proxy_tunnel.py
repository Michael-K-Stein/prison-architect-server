from typing import Any, Callable, Dict, Optional

from server.log import print_info
from server.photon.packet.base import PhotonDataPacket
from server.photon.queue.photon_client_socket import PhotonClientSocket
from server.proxy_servers.photon_queue_downstream import PhotonQueueDownstream
from server.proxy_servers.photon_queue_upstream import PhotonQueueUpstream
from server.settings import Settings


class ProxyTunnel:
    """Tunneler between upstream and downstream of a Photon session"""

    _downstream_recieve_callback: Optional[
        Callable[[PhotonClientSocket, PhotonDataPacket], None]
    ]
    _upstream_recieve_callback: Optional[
        Callable[[PhotonClientSocket, PhotonDataPacket], None]
    ]

    # Each downstream client requires their own upstream socket
    _upstreams_entered: Dict[PhotonClientSocket, PhotonQueueUpstream]
    _downstream_entered: PhotonQueueDownstream

    _app_id: str

    def __init__(
        self,
        local_port: int,
        remote_ip: str,
        remote_port: int,
        app_id: str,
        downstream_recieve_callback: Optional[
            Callable[[PhotonClientSocket, PhotonDataPacket], None]
        ] = None,
        upstream_recieve_callback: Optional[
            Callable[[PhotonClientSocket, PhotonDataPacket], None]
        ] = None,
    ) -> None:
        self.local_port = local_port
        self.remote_ip = remote_ip
        self.remote_port = remote_port
        self._app_id = app_id

        self.downstream = PhotonQueueDownstream(
            Settings().get_listen_host(), local_port
        )
        self._upstreams_entered = {}

        self._downstream_recieve_callback = downstream_recieve_callback
        self._upstream_recieve_callback = upstream_recieve_callback

    def process(self):
        # Client -> Server
        # Client may be different for each packet if multiple games are connecting to our proxy
        # Each unique client needs a unique upstream
        for downstream_client, downstream_packet in self.downstream.process():
            # Call the callback BEFORE forwarding the packet
            if self._downstream_recieve_callback is not None:
                self._downstream_recieve_callback(downstream_client, downstream_packet)
            print_info(
                self.downstream.get_type(),
                f"Proxying {downstream_packet.get_header().get_command_name()} from Client to Server",
            )
            upstream = self._get_upstream_for_client(downstream_client)
            upstream.push(downstream_packet)

        # Server -> Client
        for upstream_client, upstream in self._upstreams_entered.items():
            for upstream_packet in upstream.process():
                if self._upstream_recieve_callback is not None:
                    self._upstream_recieve_callback(upstream_client, upstream_packet)
                print_info(
                    upstream.get_type(),
                    f"Proxying {upstream_packet.get_header().get_command_name()} from Server to Client",
                )
                upstream_client.send(upstream_packet)

    def __enter__(self):
        self._downstream_entered = self.downstream.__enter__()
        return self

    def __exit__(self, *args: Any, **kwargs: Any):
        for upstream in self._upstreams_entered.values():
            upstream.__exit__(*args, **kwargs)
        self._downstream_entered.__exit__(*args, **kwargs)

    def _get_upstream_for_client(
        self, client: PhotonClientSocket
    ) -> PhotonQueueUpstream:

        if client not in self._upstreams_entered:
            self._upstreams_entered[client] = PhotonQueueUpstream(
                client, self.remote_ip, self.remote_port, self._app_id
            ).__enter__()
        return self._upstreams_entered[client]
