from threading import Thread
from time import sleep

from server.consts import ServerType
from server.local_servers import GameServer, MasterServer, NameServer
from server.local_servers.server_base import ServerBase
from server.log import print_error, print_packet_log
from server.photon.operation_code import OperationCode
from server.photon.packet.operation_packet import PhotonOperationPacket


def _process_internal(server_instance: ServerBase) -> None:
    had_packets = False
    for client, packet in server_instance.process():
        if (
            server_instance.get_type() in (ServerType.NameServer, ServerType.MasterServer)
            and isinstance(packet, PhotonOperationPacket)
            and packet.get_payload().operation_code in (
                OperationCode.RaiseEvent,
                OperationCode.SetProperties,
                OperationCode.GetProperties,
            )
        ):
            # NameServer/MasterServer are discovery/auth only; gameplay noise is ignored.
            continue

        had_packets = True
        print_error(
            server_instance.get_type(),
            f"[{type(server_instance).__name__}] Unhandled Packet From {client.get_address()}",
        )
        print_packet_log(server_instance.get_type(), packet, printer=print_error)

    if not had_packets:
        # Instead of a hard sleep, we wait on an Event. This gives 0ms latency 
        # because the Event wakes us instantly the millisecond a packet is queued.
        if hasattr(server_instance, "wait_for_packets"):
            server_instance.wait_for_packets(0.01)
        else:
            sleep(0.01)


def _name_server():
    while True:
        try:
            with NameServer() as name_server:
                while True:
                    try:
                        _process_internal(name_server)
                    except Exception as ex:
                        print_error(
                            name_server.get_type(),
                            f"Unhandled server loop exception: {type(ex).__name__}: {ex}",
                        )
                        sleep(0.1)
        except Exception as ex:
            print_error(
                ServerType.NameServer,
                f"NameServer crashed outside process loop and will restart: {type(ex).__name__}: {ex}",
            )
            sleep(1)


def _master_server():
    while True:
        try:
            with MasterServer() as master_server:
                while True:
                    try:
                        _process_internal(master_server)
                    except Exception as ex:
                        print_error(
                            master_server.get_type(),
                            f"Unhandled server loop exception: {type(ex).__name__}: {ex}",
                        )
                        sleep(0.1)
        except Exception as ex:
            print_error(
                ServerType.MasterServer,
                f"MasterServer crashed outside process loop and will restart: {type(ex).__name__}: {ex}",
            )
            sleep(1)


def _game_server():
    while True:
        try:
            with GameServer() as game_server:
                while True:
                    try:
                        _process_internal(game_server)
                    except Exception as ex:
                        print_error(
                            game_server.get_type(),
                            f"Unhandled server loop exception: {type(ex).__name__}: {ex}",
                        )
                        sleep(0.1)
        except Exception as ex:
            print_error(
                ServerType.GameServer,
                f"GameServer crashed outside process loop and will restart: {type(ex).__name__}: {ex}",
            )
            sleep(1)


def main():
    name_server_worker = Thread(target=_name_server, name="NameServer Worker", daemon=True)
    master_server_worker = Thread(target=_master_server, name="MasterServer Worker", daemon=True)
    game_server_worker = Thread(target=_game_server, name="GameServer Worker", daemon=True)

    name_server_worker.start()
    master_server_worker.start()
    game_server_worker.start()

    try:
        while True:
            sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down servers...")
