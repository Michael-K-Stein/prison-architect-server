from threading import Thread
from time import sleep

from server.local_servers import GameServer, MasterServer, NameServer
from server.local_servers.server_base import ServerBase
from server.log import print_error, print_packet_log


def _process_internal(server_instance: ServerBase) -> None:
    packets = list(
        (
            client,
            packet,
        )
        for client, packet in server_instance.process()
    )
    if not packets:
        sleep(0.1)
        return
    for client, packet in packets:
        print_error(
            server_instance.get_type(),
            f"[{type(server_instance).__name__}] Unhandled Packet From {client.get_address()}",
        )
        print_packet_log(server_instance.get_type(), packet, printer=print_error)


def _name_server():
    with NameServer() as name_server:
        while True:
            _process_internal(name_server)


def _master_server():
    with MasterServer() as master_server:
        while True:
            _process_internal(master_server)


def _game_server():
    with GameServer() as game_server:
        while True:
            _process_internal(game_server)


def main():
    name_server_worker = Thread(target=_name_server, name="NameServer Worker")
    master_server_worker = Thread(target=_master_server, name="MasterServer Worker")
    game_server_worker = Thread(target=_game_server, name="GameServer Worker")

    name_server_worker.start()
    master_server_worker.start()
    game_server_worker.start()

    game_server_worker.join()
    master_server_worker.join()
    name_server_worker.join()
