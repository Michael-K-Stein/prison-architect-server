from enum import Enum
from threading import Thread
from time import sleep
from types import TracebackType
from typing import Optional, Tuple, Type, cast

from server.consts import ServerType
from server.local_servers.games_manager import GamesManager
from server.local_servers.server_base import ServerBase
from server.models.actor_properties import ActorProperties, ActorPropertiesHashtable
from server.photon.command_code import CommandCode
from server.photon.event_code import EventCode
from server.photon.operation_code import OperationCode
from server.photon.packet.factory import PacketFactory
from server.photon.packet.operation_packet import PhotonOperationPacket
from server.photon.param.parameter_key import ParameterKey
from server.photon.param.string_param import StringParameter
from server.photon.queue.photon_client_socket import PhotonClientSocket
from server.settings import Settings


class InstanceState(Enum):
    Disconnected = 0
    AwaitingInit = 1
    AwaitingKeyExchange = 2
    AwaitingRegionListRequest = 3
    AwaitingAuthenticationRequest = 4
    Complete = 5


class MasterServer(ServerBase):
    _game_list_updater_worker: Thread
    _running: bool

    def __init__(self):
        super().__init__(Settings().get_listen_host(), 4530)
        self._running = False
        self._game_list_updater_worker = Thread(
            target=self._game_list_updater,
            name="[MASTERSERVER] Game List Updater Worker",
            daemon=True,
        )

    def __enter__(self):
        super().__enter__()
        self._running = True
        self._game_list_updater_worker.start()
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        self._running = False
        self._game_list_updater_worker.join(2)
        super().__exit__(exc_type, exc_val, exc_tb)

    def process(self, do_not_handle: Optional[Tuple[OperationCode, ...]] = None):
        extra_ops = (
            OperationCode.Authenticate,
            OperationCode.JoinLobby,
            OperationCode.CreateGame,
        )
        if do_not_handle is not None:
            combined_do_not_handle = do_not_handle + extra_ops
        else:
            combined_do_not_handle = extra_ops

        for client, packet in super().process(do_not_handle=combined_do_not_handle):
            if (
                isinstance(packet, PhotonOperationPacket)
                and packet.get_payload().operation_code == OperationCode.Authenticate
            ):
                self._handle_authenticate_request(client, packet)
                continue
            if (
                isinstance(packet, PhotonOperationPacket)
                and packet.get_payload().operation_code == OperationCode.JoinLobby
            ):
                self._handle_join_lobby_request(client, packet)
                continue
            if (
                isinstance(packet, PhotonOperationPacket)
                and packet.get_payload().operation_code == OperationCode.CreateGame
            ):
                self._handle_create_game_request(client, packet)
                continue
            if (
                isinstance(packet, PhotonOperationPacket)
                and packet.get_payload().operation_code == OperationCode.JoinGame
            ):
                self._handle_join_game_request(client, packet)
                continue
            yield client, packet

    def _handle_join_lobby_request(
        self, client: PhotonClientSocket, packet: PhotonOperationPacket
    ) -> None:
        client.send(
            PacketFactory.operation(
                CommandCode.EncryptedOperationResponse,
                OperationCode.JoinLobby,
                return_code=0,
            )
        )

        self._send_game_list(client)

    def _send_game_list(self, client: PhotonClientSocket):
        client.send(PacketFactory.game_list(GamesManager()))

        client.send(
            PacketFactory.event(
                EventCode.AppStats,
                params=GamesManager().app_stats(),
            )
        )

        self._send_game_list_update(client)

    def _send_game_list_update(self, client: PhotonClientSocket):
        client.send(
            PacketFactory.event(
                EventCode.GameListUpdate,
                params=PacketFactory.game_list_params(GamesManager()),
            )
        )

    def _handle_authenticate_request(
        self, client: PhotonClientSocket, packet: PhotonOperationPacket
    ) -> None:
        token = cast(
            StringParameter, packet.get_payload().params.get(ParameterKey.Token)
        )
        client.enrich_with_token_data(client, token.value)

        client.send(
            PacketFactory.operation(
                CommandCode.EncryptedOperationResponse,
                OperationCode.Authenticate,
                params={
                    ParameterKey.Token: StringParameter(client.to_token()),
                },
                return_code=0,
            )
        )

        client.send(
            PacketFactory.event(EventCode.AppStats, params=GamesManager().app_stats())
        )

    def _handle_create_game_request(
        self, client: PhotonClientSocket, packet: PhotonOperationPacket
    ):
        params = packet.get_payload().params
        game_id = cast(StringParameter, params.get(ParameterKey.GameId))
        actor_properties = params.get(ParameterKey.ActorProperties)
        if actor_properties is not None:
            actor_props = ActorProperties(
                cast(ActorPropertiesHashtable, actor_properties)
            )
            if actor_props.player_name:
                client.set_user_name(actor_props.player_name)
            if actor_props.user_id:
                client.set_user_id(int(actor_props.user_id))

        client.send(
            PacketFactory.operation(
                CommandCode.EncryptedOperationResponse,
                OperationCode.CreateGame,
                params={
                    ParameterKey.Address: StringParameter(
                        f"{Settings().get_ip()}:4531"
                    ),
                    ParameterKey.GameId: game_id,
                    ParameterKey.Token: StringParameter(client.to_token()),
                },
                return_code=0,
            )
        )

    def _handle_join_game_request(
        self, client: PhotonClientSocket, packet: PhotonOperationPacket
    ):
        client.send(
            PacketFactory.operation(
                CommandCode.EncryptedOperationResponse,
                OperationCode.JoinGame,
                params={
                    ParameterKey.Address: StringParameter(
                        f"{Settings().get_ip()}:4531"
                    ),
                    ParameterKey.Token: StringParameter(client.to_token()),
                },
                return_code=0,
            )
        )

    @classmethod
    def get_type(cls) -> ServerType:
        return ServerType.MasterServer

    def _game_list_updater(self) -> None:
        while self._running:
            sleep(5)
            clients = self._dispatcher.get_clients()
            if not clients:
                continue
            
            # Build the packet exactly once for all clients
            packet = PacketFactory.event(
                EventCode.GameListUpdate,
                params=PacketFactory.game_list_params(GamesManager()),
            )
            for client in clients:
                client.send(packet)
