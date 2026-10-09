from time import sleep

from server.consts import PRISON_ARCHITECT_APP_ID, ServerType
from server.log import print_packet_log
from server.photon.packet.base import PhotonDataPacket
from server.photon.packet.operation_packet import PhotonOperationPacket
from server.photon.queue.photon_client_socket import PhotonClientSocket
from server.proxy_servers.hijack import do_hijacks
from server.proxy_servers.proxy_queue_type import ProxyQueueType
from server.proxy_servers.proxy_tunnel import ProxyTunnel


def run_proxy(upstream_ip: str, port: int, server_type: ServerType):
    def on_client_packet(_client: PhotonClientSocket, packet: PhotonDataPacket):
        if isinstance(packet, PhotonOperationPacket):
            print_packet_log(ProxyQueueType.Downstream, packet)

    def on_server_packet(_client: PhotonClientSocket, packet: PhotonDataPacket):
        if isinstance(packet, PhotonOperationPacket):
            print_packet_log(ProxyQueueType.Upstream, packet)
        # Rewrite server responses (regions, game lists, ...) before they are
        # forwarded to the client.
        do_hijacks(packet, server_type=server_type)

    with ProxyTunnel(
        local_port=port,
        remote_ip=upstream_ip,
        remote_port=port,
        app_id=PRISON_ARCHITECT_APP_ID,
        downstream_recieve_callback=on_client_packet,
        upstream_recieve_callback=on_server_packet,
    ) as tunnel:
        while True:
            tunnel.process()
            sleep(0.1)
