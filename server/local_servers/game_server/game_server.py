from typing import Dict, List, Optional, Tuple, cast

from server.consts import ServerType
from server.errors import GameDoesNotExistError
from server.local_servers.games_manager import GamesManager
from server.local_servers.server_base import ServerBase
from server.log import (
    print_debug,
    print_info,
    print_packet_log,
    print_success,
)
from server.models.actor_properties import ActorProperties, ActorPropertiesHashtable
from server.models.game_object import GameObject
from server.models.game_properties import GameProperties, GamePropertiesTable
from server.photon.command_code import CommandCode
from server.photon.event_code import EventCode
from server.photon.operation_code import OperationCode
from server.photon.packet.factory import PacketFactory
from server.photon.packet.operation_packet import PhotonOperationPacket
from server.photon.param.hashtable_param import HashtableParameter
from server.photon.param.int8_param import Int8Parameter
from server.photon.param.int8_slice_param import Int8SliceParameter
from server.photon.param.int32_param import Int32Parameter
from server.photon.param.parameter_key import ParameterKey
from server.photon.param.slice_param import SliceParameter
from server.photon.param.string_param import StringParameter
from server.photon.queue.photon_client_socket import PhotonClientSocket
from server.settings import Settings


class GameServer(ServerBase):
    _games_manager: GamesManager

    def __init__(self):
        super().__init__(Settings().get_listen_host(), 4531)
        self._games_manager = GamesManager()

    def process(self, do_not_handle: Optional[Tuple[OperationCode, ...]] = None):
        extra_ops = (
            OperationCode.CreateGame,
            OperationCode.JoinLobby,
            OperationCode.RaiseEvent,
            OperationCode.SetProperties,
            OperationCode.Leave,
        )
        if do_not_handle is not None:
            combined_do_not_handle = do_not_handle + extra_ops
        else:
            combined_do_not_handle = extra_ops

        for client, packet in super().process(do_not_handle=combined_do_not_handle):
            if (
                isinstance(packet, PhotonOperationPacket)
                and packet.get_payload().operation_code == OperationCode.CreateGame
            ):
                self._handle_create_game(client, packet)
                continue
            if (
                isinstance(packet, PhotonOperationPacket)
                and packet.get_payload().operation_code == OperationCode.JoinGame
            ):
                self._handle_join_game(client, packet)
                continue
            if (
                isinstance(packet, PhotonOperationPacket)
                and packet.get_payload().operation_code == OperationCode.RaiseEvent
            ):
                self._handle_raise_event(client, packet)
                continue
            if (
                isinstance(packet, PhotonOperationPacket)
                and packet.get_payload().operation_code == OperationCode.SetProperties
            ):
                self._handle_set_properties(client, packet)
                continue
            if (
                isinstance(packet, PhotonOperationPacket)
                and packet.get_payload().operation_code == OperationCode.Leave
            ):
                self._handle_leave_game(client, packet)
                continue
            yield client, packet

    def _handle_create_game(
        self, client: "PhotonClientSocket", packet: PhotonOperationPacket
    ):
        params = packet.get_payload().params
        actor_properties = ActorProperties(
            cast(ActorPropertiesHashtable, params.get(ParameterKey.ActorProperties))
        )
        requesting_player_name = actor_properties.player_name
        client.set_user_name(requesting_player_name)

        game_properties = GameProperties(
            cast(GamePropertiesTable, params.get(ParameterKey.GameProperties))
        )
        game_id = cast(StringParameter, params.get(ParameterKey.GameId)).value
        game_owner = game_properties.game_master
        password_required = game_properties.is_password_protected
        player_capacity = game_properties.player_capacity
        print_success(
            self.get_type(),
            f'"{requesting_player_name}" ({client.get_address()}) created game "{game_id}"',
        )

        created_game = self._games_manager.create_game(
            name=game_id,
            owner=game_owner,
            password_required=password_required,
            capacity=player_capacity,
        )

        new_num = created_game.join_player(client)
        client.join_game(game_id, new_num)

        props = GameProperties()
        props.is_visible = True
        props.is_open = True
        props.is_password_protected = True
        props.game_master = requesting_player_name
        props.master_client_id = new_num
        props.player_ttl = 0
        props.empty_room_ttl = 0
        props.max_players_int = 4
        props.player_capacity = 4
        props.props_listed_in_lobby = ["MAS", "PA"]

        client.send(
            PacketFactory.operation(
                CommandCode.EncryptedOperationResponse,
                OperationCode.CreateGame,
                {
                    ParameterKey.ActorNr: Int32Parameter(new_num),
                    ParameterKey.GameProperties: props.to_hashtable(),
                    ParameterKey.Actors: SliceParameter([Int32Parameter(new_num)]),
                    ParameterKey.AuthMode: Int32Parameter(11),
                },
                return_code=0,
            )
        )

    def _send_encrypted_join_event(
        self,
        client: PhotonClientSocket,
        new_actor_num: int,
        game: GameObject,
    ):
        actors_props = HashtableParameter(
            {
                Int32Parameter(k): v.get_custom_properties().to_hashtable()
                for k, v in game.get_connected_players().items()
                if k != new_actor_num
            }
        )

        actors = list(game.get_connected_players().keys())
        print_info(self.get_type(), "Actors(join): ", actors)
        print_info(self.get_type(), "ActorProps(join): ", actors_props)

        client.send(
            PacketFactory.encrypted_event(
                EventCode.Event,
                {
                    ParameterKey.ActorNr: Int32Parameter(new_actor_num),
                    ParameterKey.Actors: SliceParameter(
                        [Int32Parameter(x) for x in actors]
                    ),
                    ParameterKey.ActorProperties: actors_props,
                },
                return_code=0,
            )
        )

    def _handle_join_game(
        self, client: PhotonClientSocket, packet: PhotonOperationPacket
    ):
        requesting_actor_properties = ActorProperties(
            cast(
                ActorPropertiesHashtable,
                packet.get_payload().params[ParameterKey.ActorProperties],
            )
        )

        requestor_name = requesting_actor_properties.player_name

        client.set_user_name(requestor_name)
        client.update_custom_properties(requesting_actor_properties)

        requested_game_id = packet.get_payload().params[ParameterKey.GameId]

        try:
            requested_game = self._games_manager[requested_game_id]
        except GameDoesNotExistError:
            client.send(
                PacketFactory.operation(
                    CommandCode.OperationResponse,
                    OperationCode.JoinGame,
                    return_code=-1,
                    error_message=f"Game does not exist (on {Settings().get_ip()})!",
                )
            )
            return

        actor_number = requested_game.join_player(client)

        actor_properties: Dict[Int32Parameter, ActorProperties] = {}

        for actor_num, actor_client in requested_game.get_connected_players().items():
            actor_props = ActorProperties(
                actor_client.get_custom_properties().to_hashtable()
            )
            actor_props.player_name = actor_client.get_user_name()
            actor_props.user_id = str(actor_client.get_user_id())
            actor_properties[Int32Parameter(actor_num)] = actor_props

        game_props = GameProperties()
        # Standard room visibility and state
        game_props.is_visible = True
        game_props.is_open = True

        # Dynamic properties from your requested_game object
        game_props.is_password_protected = requested_game.password_required
        game_props.game_master = requested_game.owner
        game_props.player_capacity = requested_game.player_capacity

        # Host and lobby configuration
        game_props.master_client_id = 1
        game_props.player_ttl = 0
        game_props.empty_room_ttl = 0
        game_props.max_players_int = 4
        game_props.props_listed_in_lobby = ["MAS", "PA"]

        client.join_game(requested_game.get_id(), actor_number)
        actors = [
            Int32Parameter(x)
            for x in [
                *list(requested_game.get_connected_players().keys()),
                actor_number,
            ]
        ]

        client.send(
            PacketFactory.operation(
                CommandCode.EncryptedOperationResponse,
                OperationCode.JoinGame,
                params={
                    ParameterKey.ActorNr: Int32Parameter(actor_number),
                    ParameterKey.ActorProperties: HashtableParameter(
                        {k: v.to_hashtable() for k, v in actor_properties.items()}
                    ),
                    ParameterKey.GameProperties: game_props.to_hashtable(),
                    ParameterKey.Actors: SliceParameter(actors),
                    ParameterKey.AuthMode: Int32Parameter(11),
                },
                return_code=0,
            )
        )

        self._send_encrypted_join_event(client, actor_number, requested_game)

    def _handle_raise_event(
        self, client: PhotonClientSocket, packet: PhotonOperationPacket
    ):
        if (
            len(packet.get_payload().params) != 2
            and len(packet.get_payload().params) != 3
        ):
            print_packet_log(self.get_type(), packet)
            raise RuntimeError(
                f'Expected 2 or 3 params for "RaiseEvent", got {len(packet.get_payload().params)}'
            )

        game_id = client.get_game_id()
        current_game = self._games_manager[game_id]

        event_code = cast(Int8Parameter, packet.get_payload().params[ParameterKey.Code])
        data = cast(Int8SliceParameter, packet.get_payload().params[ParameterKey.Data])
        recieving_actors = cast(
            SliceParameter[Int32Parameter] | None,
            packet.get_payload().params.get(ParameterKey.Actors, None),
        )

        print_debug(
            self.get_type(),
            f"Raising event {event_code.value} for game {game_id} with data (length): {len(data.value)}",
        )

        to_players = None
        if recieving_actors is not None:
            to_players = [
                x.value
                for x in cast(
                    List[Int32Parameter], recieving_actors.value
                )  # pyright: ignore[reportUnnecessaryCast]
            ]

        current_game.raise_event(
            client,
            packet,
            to_players=to_players,
        )

    def _handle_set_properties(
        self, client: PhotonClientSocket, packet: PhotonOperationPacket
    ):
        params = packet.get_payload().params
        properties = cast(ActorProperties, params.get(ParameterKey.Properties))
        client.update_custom_properties(properties)

        # Return an ACK
        client.send(
            PacketFactory.operation(
                CommandCode.OperationResponse,
                OperationCode.SetProperties,
                return_code=0,
            )
        )

    def _handle_leave_game(
        self, client: PhotonClientSocket, packet: PhotonOperationPacket
    ):
        print_success(
            self.get_type(),
            f'"{client.get_user_name()}" ({client.get_address()}) left game "{client.get_game_id()}"',
        )
        current_game = self._games_manager[client.get_game_id()]
        current_game.remove_player(client.get_in_game_user_num())
        client.leave_game()

    @classmethod
    def get_type(cls) -> ServerType:
        return ServerType.GameServer
