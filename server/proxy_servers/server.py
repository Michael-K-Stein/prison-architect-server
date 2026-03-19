from time import sleep

from server.consts import ServerType
from server.hijack import do_hijacks
from server.log import print_packet_log
from server.photon.packet.operation_packet import PhotonOperationPacket
from server.proxy_servers.photon_queue_client import PhotonQueueClient
from server.proxy_servers.photon_queue_server import PhotonQueueServer
from server.settings import Settings


def run_server(upstream_ip: str, port: int, server_type: ServerType):
    with PhotonQueueClient(upstream_ip, port) as upstream, PhotonQueueServer(
        Settings().get_listen_host(), port
    ) as downstream:
        packets_seen = 0

        while True:
            sleep(0.1)
            downstream_packet = downstream.pop()
            while downstream_packet is not None:
                name = downstream_packet.get_header().get_command_name()
                # print_critical(f"Proxying {name} from Client to Server")

                if isinstance(downstream_packet, PhotonOperationPacket):
                    packet_log = downstream_packet.log()
                    if packet_log is not None:
                        print_packet_log("Client", "Proxy", packet_log)
                    # print(cast(PhotonOperationPacket, downstream_packet).log())
                upstream.push(downstream_packet)
                downstream_packet = downstream.pop()

            upstream_packet = upstream.pop()
            while upstream_packet is not None:
                name = upstream_packet.get_header().get_command_name()
                # print_critical(f"Proxying {name} from Server to Client")

                if isinstance(upstream_packet, PhotonOperationPacket):
                    packet_log = upstream_packet.log()
                    if packet_log is not None:
                        print_packet_log("Server", "Proxy", packet_log)
                do_hijacks(upstream_packet, server_type=server_type)

                packets_seen += 1
                downstream.push(upstream_packet)
                upstream_packet = upstream.pop()
