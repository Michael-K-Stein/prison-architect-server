from typing import Tuple, cast

from server.models.game_properties import GamePropertiesTable
from server.photon.param.bool_param import BooleanParameter
from server.photon.param.hashtable_param import HashtableParameter
from server.photon.param.int8_param import Int8Parameter
from server.photon.param.int32_param import Int32Parameter
from server.photon.param.string_param import StringParameter
from server.photon.property_keys import GamePropertyKey


class GameListEntry:
    name: str
    owner: str
    password_required: bool
    player_count: int
    player_capacity: int
    max_players_int: int
    is_open: bool

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
        self.name = name
        self.owner = owner
        self.password_required = password_required
        self.player_count = player_count
        self.player_capacity = player_capacity
        self.max_players_int = max_players_int
        self.is_open = is_open

    @staticmethod
    def from_hashtable_entry(key: StringParameter, game_params: GamePropertiesTable):
        game_name: str = key.value
        is_password_protected: bool = cast(
            BooleanParameter, game_params[GamePropertyKey.PasswordProtected.value]
        ).value
        current_player_count: int = cast(
            Int8Parameter, game_params[GamePropertyKey.PlayerCount.value]
        ).value
        game_master: str = cast(
            StringParameter, game_params[GamePropertyKey.GameMaster.value]
        ).value
        max_players_int: int = (
            cast(Int32Parameter, game_params[GamePropertyKey.MaxPlayersInt.value]).value
            if GamePropertyKey.MaxPlayersInt.value in game_params
            else 0
        )
        is_open: bool = (
            cast(BooleanParameter, game_params[GamePropertyKey.IsOpen.value]).value
            if GamePropertyKey.IsOpen.value in game_params
            else False
        )
        player_capacity: int = (
            cast(Int8Parameter, game_params[GamePropertyKey.MaxPlayers.value]).value
            if GamePropertyKey.MaxPlayers.value in game_params
            else 0
        )
        return GameListEntry(
            name=game_name,
            password_required=is_password_protected,
            player_count=current_player_count,
            owner=game_master,
            player_capacity=player_capacity,
            max_players_int=max_players_int,
            is_open=is_open,
        )

    def to_hashtable_entry(self) -> Tuple[StringParameter, GamePropertiesTable]:
        return (
            StringParameter(self.name),
            HashtableParameter(
                {
                    GamePropertyKey.PasswordProtected.value: BooleanParameter(
                        self.password_required
                    ),
                    GamePropertyKey.PlayerCount.value: Int8Parameter(self.player_count),
                    GamePropertyKey.GameMaster.value: StringParameter(self.owner),
                    GamePropertyKey.MaxPlayers.value: Int8Parameter(
                        self.player_capacity
                    ),
                    GamePropertyKey.MaxPlayersInt.value: Int32Parameter(
                        self.max_players_int
                    ),
                    GamePropertyKey.IsOpen.value: BooleanParameter(self.is_open),
                }
            ),
        )
