from time import time
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
    print_warning,
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
from server.photon.param.int32_param import Int32Parameter
from server.photon.param.parameter_key import ParameterKey
from server.photon.param.slice_param import SliceParameter
from server.photon.param.string_param import StringParameter
from server.photon.queue.photon_client_socket import PhotonClientSocket
from server.settings import Settings


class GameServer(ServerBase):
    _games_manager: GamesManager
    _pending_disconnects: Dict[Tuple[str, int], float]
    _disconnect_grace_seconds: int
    _empty_game_since: Dict[str, float]
    _empty_game_ttl_seconds: int
    _world_update_log_counter: int

    def __init__(self):
        super().__init__(Settings().get_listen_host(), 4531)
        self._games_manager = GamesManager()
        self._pending_disconnects = {}
        # Allow network hiccups/reconnect loops before treating as hard disconnect.
        self._disconnect_grace_seconds = 180
        self._empty_game_since = {}
        # Keep empty games for a while so clients can reconnect without losing the room.
        self._empty_game_ttl_seconds = 300
        self._world_update_log_counter = 0

    @staticmethod
    def _resolve_player_name(
        packet: PhotonOperationPacket, actor_properties: ActorProperties
    ) -> str:
        name_from_actor_props = actor_properties.player_name.strip()
        if name_from_actor_props != "":
            return name_from_actor_props

        nickname = packet.get_payload().params.get(ParameterKey.Nickname)
        if isinstance(nickname, StringParameter):
            fallback_name = nickname.value.strip()
            if fallback_name != "":
                return fallback_name

        return "Unknown"

    def _cleanup_disconnected_players(self) -> None:
        empty_game_ids: List[str] = []
        now = time()

        for game_id, game in list(self._games_manager.get_games().items()):
            for actor_num, actor_client in list(game.get_connected_players().items()):
                marker_key = (game_id, actor_num)

                if not actor_client.is_disconnected():
                    self._pending_disconnects.pop(marker_key, None)
                    continue

                first_seen = self._pending_disconnects.get(marker_key)
                if first_seen is None:
                    self._pending_disconnects[marker_key] = now
                    continue

                if now - first_seen < self._disconnect_grace_seconds:
                    continue

                player_name = "Unknown"
                try:
                    player_name = actor_client.get_user_name()
                except ValueError:
                    pass

                game.remove_player(actor_num)
                try:
                    actor_client.leave_game()
                except TypeError:
                    pass

                self._pending_disconnects.pop(marker_key, None)

                print_warning(
                    self.get_type(),
                    f'"{player_name}" disconnected unexpectedly and was removed from game "{game_id}"',
                )

            if game.player_count == 0:
                empty_since = self._empty_game_since.get(game_id)
                if empty_since is None:
                    self._empty_game_since[game_id] = now
                elif now - empty_since >= self._empty_game_ttl_seconds:
                    empty_game_ids.append(game_id)
            else:
                self._empty_game_since.pop(game_id, None)

        for game_id in empty_game_ids:
            self._games_manager.remove_game(game_id)
            # Remove any stale pending markers for the removed game.
            self._pending_disconnects = {
                k: v for k, v in self._pending_disconnects.items() if k[0] != game_id
            }
            self._empty_game_since.pop(game_id, None)
            print_info(self.get_type(), f'Game "{game_id}" is empty and was removed')

    def process(self, do_not_handle: Optional[Tuple[OperationCode, ...]] = None):
        self._cleanup_disconnected_players()

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
        requesting_player_name = self._resolve_player_name(packet, actor_properties)
        actor_properties.player_name = requesting_player_name
        client.set_user_name(requesting_player_name)
        client.update_custom_properties(actor_properties)

        game_properties = GameProperties(
            cast(GamePropertiesTable, params.get(ParameterKey.GameProperties))
        )
        game_id = cast(StringParameter, params.get(ParameterKey.GameId)).value
        game_owner = game_properties.game_master
        password_required = game_properties.is_password_protected
        configured_capacity = Settings().get_max_players()
        player_capacity = configured_capacity
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

        creator_props = ActorProperties(client.get_custom_properties().to_hashtable())
        creator_props.player_name = requesting_player_name
        creator_props.user_id = str(client.get_user_id())

        props = GameProperties()
        props.is_visible = True
        props.is_open = True
        props.is_password_protected = True
        props.game_master = requesting_player_name
        props.master_client_id = new_num
        props.player_ttl = 0
        props.empty_room_ttl = 0
        props.max_players_int = configured_capacity
        props.player_capacity = configured_capacity
        props.props_listed_in_lobby = ["MAS", "PA"]

        client.send(
            PacketFactory.operation(
                CommandCode.EncryptedOperationResponse,
                OperationCode.CreateGame,
                {
                    ParameterKey.ActorNr: Int32Parameter(new_num),
                    ParameterKey.ActorProperties: HashtableParameter(
                        {Int32Parameter(new_num): creator_props.to_hashtable()}
                    ),
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

        requestor_name = self._resolve_player_name(packet, requesting_actor_properties)
        requesting_actor_properties.player_name = requestor_name

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

        if requested_game.player_count >= requested_game.player_capacity:
            client.send(
                PacketFactory.operation(
                    CommandCode.OperationResponse,
                    OperationCode.JoinGame,
                    return_code=-1,
                    error_message="Game is full",
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
        game_props.max_players_int = requested_game.player_capacity
        game_props.props_listed_in_lobby = ["MAS", "PA"]

        client.join_game(requested_game.get_id(), actor_number)
        actors = [
            Int32Parameter(x)
            for x in requested_game.get_connected_players().keys()
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

        # JoinGame response already includes the full actor list and actor properties.
        # Sending an additional join event to the same client can cause duplicate/partial actor state.

    def _handle_raise_event(
        self, client: PhotonClientSocket, packet: PhotonOperationPacket
    ):
        params = packet.get_payload().params

        if ParameterKey.Code not in params or ParameterKey.Data not in params:
            print_warning(
                self.get_type(),
                f'Ignoring malformed RaiseEvent from {client.get_address()}: missing required params (keys={list(params.keys())})',
            )
            print_packet_log(self.get_type(), packet)
            return

        game_id = client.get_game_id()
        current_game = self._games_manager[game_id]

        code_param = params[ParameterKey.Code]
        if not isinstance(code_param, Int8Parameter):
            print_warning(
                self.get_type(),
                f"Ignoring malformed RaiseEvent from {client.get_address()}: Code is {type(code_param).__name__}, expected Int8Parameter",
            )
            return

        event_code = code_param
        data_param = params[ParameterKey.Data]

        recieving_actors = cast(
            SliceParameter[Int32Parameter] | None,
            params.get(ParameterKey.Actors, None),
        )

        # Removed terminal output for RaiseEvent here. Printing thousands of events
        # per minute artificially limits server performance because stdout on Windows
        # is blocking and pauses the entire Python process.

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
        properties = ActorProperties(
            cast(ActorPropertiesHashtable, params.get(ParameterKey.Properties))
        )
        client.update_custom_properties(properties)

        # Return an ACK
        client.send(
            PacketFactory.operation(
                CommandCode.OperationResponse,
                OperationCode.SetProperties,
                return_code=0,
            )
        )

        # Broadcast updated actor properties to other players in the same room.
        try:
            game_id = client.get_game_id()
            actor_num = client.get_in_game_user_num()
        except ValueError:
            return

        current_game = self._games_manager[game_id]
        props_snapshot = client.get_custom_properties().to_hashtable()

        for other_num, other_client in current_game.get_connected_players().items():
            if other_num == actor_num:
                continue
            update_event = PacketFactory.operation(
                CommandCode.EncryptedEvent,
                cast(OperationCode, 0xFD),  # PropertiesChanged event
                {
                    ParameterKey.TargetActorNr: Int32Parameter(actor_num),
                    ParameterKey.Properties: props_snapshot,
                },
            )
            other_client.send(update_event)

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
