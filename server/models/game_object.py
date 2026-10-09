from typing import Dict, List, Optional, cast

from server.local_servers.common import raised_event_to_event_packet
from server.models.actor_properties import ActorProperties
from server.models.game_list_entry import GameListEntry
from server.models.game_properties import GameProperties
from server.photon.command_code import CommandCode
from server.photon.operation_code import OperationCode
from server.photon.packet.header import PhotonDataPacketHeader
from server.photon.packet.operation_packet import PhotonOperationPacket
from server.photon.packet.operation_payload import PhotonPacketPayload
from server.photon.param.hashtable_param import HashtableParameter
from server.photon.param.int32_param import Int32Parameter
from server.photon.param.parameter_key import ParameterKey
from server.photon.param.slice_param import SliceParameter
from server.photon.queue.photon_client_socket import PhotonClientSocket


class GameObject(GameListEntry):
    _custom_properties: GameProperties
    _connected_players: Dict[int, PhotonClientSocket]  # ActorNr: Player
    _next_player_num: int

    def __init__(
        self,
        name: str,
        owner: str,
        password_required: bool,
        player_count: int = 0,
        player_capacity: int = 4,
        max_players_int: int = 4,
        is_open: bool = True,
    ):
        super().__init__(
            name,
            owner,
            password_required,
            player_count,
            player_capacity,
            max_players_int,
            is_open,
        )
        self._custom_properties = GameProperties()
        self._connected_players = {}
        self._next_player_num = 0

    def update_custom_properties(self, custom_properties: GameProperties):
        self._custom_properties.update(custom_properties)

    def join_player(self, player: PhotonClientSocket):
        actor_num = self._new_player_num()
        all_actor_nums = [Int32Parameter(x) for x in self._connected_players.keys()] + [
            Int32Parameter(actor_num)
        ]
        self._connected_players[actor_num] = player
        self.player_count = len(self._connected_players)

        # Start from the client's actual actor properties so we keep fields like color.
        actor_props = ActorProperties(player.get_custom_properties().to_hashtable())
        if actor_props.player_name == "":
            actor_props.player_name = player.get_user_name()
        if actor_props.user_id == "":
            actor_props.user_id = str(player.get_user_id())

        actors_props = HashtableParameter(
            {Int32Parameter(actor_num): actor_props.to_hashtable()}
        )

        for old_player_num, old_player in self._connected_players.items():
            if old_player_num == actor_num:
                continue

            header = PhotonDataPacketHeader(CommandCode.EncryptedEvent)
            old_player.send(
                PhotonOperationPacket(
                    header=header,
                    payload=PhotonPacketPayload(
                        operation_code=OperationCode.Event,
                        params={
                            ParameterKey.ActorNr: Int32Parameter(actor_num),
                            ParameterKey.Actors: SliceParameter(all_actor_nums),
                            ParameterKey.ActorProperties: actors_props,
                        },
                        header=header,
                        response_debug_data=None,
                    ),
                )
            )

            # Some clients apply display fields (name/color) from PropertiesChanged.
            # Push the full actor properties right after join to avoid "?" placeholders.
            props_header = PhotonDataPacketHeader(CommandCode.EncryptedEvent)
            old_player.send(
                PhotonOperationPacket(
                    header=props_header,
                    payload=PhotonPacketPayload(
                        operation_code=cast(OperationCode, 0xFD),
                        params={
                            ParameterKey.TargetActorNr: Int32Parameter(actor_num),
                            ParameterKey.Properties: actor_props.to_hashtable(),
                        },
                        header=props_header,
                        response_debug_data=None,
                    ),
                )
            )

        return actor_num

    def remove_player(self, player_num: int):
        self._connected_players.pop(player_num, None)
        self.player_count = len(self._connected_players)

    def _new_player_num(self) -> int:
        self._next_player_num += 1
        return self._next_player_num

    def get_connected_players(self) -> Dict[int, PhotonClientSocket]:
        return self._connected_players

    def get_connected_player_ids(self) -> List[int]:
        return [x.get_user_id() for x in self._connected_players.values()]

    def raise_event(
        self,
        from_player: PhotonClientSocket | int,
        event_packet: PhotonOperationPacket,
        to_players: Optional[List[int]] = None,
    ) -> None:
        if isinstance(from_player, int):
            from_player = self._connected_players.get(from_player, -1)
            if from_player == -1:
                raise RuntimeError("Player not found!")

        # Create the packet exactly once to avoid redundant allocations for every player.
        event_to_send = raised_event_to_event_packet(
            from_player=from_player, raised_event=event_packet
        )

        for actor_num, player in self._connected_players.items():
            if player == from_player:
                continue
            if to_players is not None and actor_num not in to_players:
                continue

            player.send(event_to_send)

    def get_id(self) -> str:
        return self.name
