from typing import Optional, Union, cast

from server.models.properties_base import PropertiesBase
from server.photon.param.bool_param import BooleanParameter
from server.photon.param.hashtable_param import HashtableParameter
from server.photon.param.int8_param import Int8Parameter
from server.photon.param.int32_param import Int32Parameter
from server.photon.param.slice_param import SliceParameter
from server.photon.param.string_param import StringParameter
from server.photon.property_keys import GamePropertyKey

GamePropertiesTable = HashtableParameter[
    Union[StringParameter, Int8Parameter],
    Union[
        StringParameter,
        Int8Parameter,
        Int32Parameter,
        BooleanParameter,
        SliceParameter[StringParameter],
    ],
]


class GameProperties(PropertiesBase[GamePropertiesTable]):
    """A clean Pythonic wrapper for reading and writing Prison Architect game properties."""

    raw: GamePropertiesTable

    def __init__(self, hashtable: Optional[GamePropertiesTable] = None):
        self.raw = hashtable if hashtable is not None else HashtableParameter()

    @property
    def is_password_protected(self) -> bool:
        key = GamePropertyKey.PasswordProtected.value
        return cast(BooleanParameter, self.raw[key]).value if key in self.raw else False

    @is_password_protected.setter
    def is_password_protected(self, value: bool) -> None:
        self.raw[GamePropertyKey.PasswordProtected.value] = BooleanParameter(value)

    @property
    def current_player_count(self) -> int:
        key = GamePropertyKey.PlayerCount.value
        return cast(Int8Parameter, self.raw[key]).value if key in self.raw else 0

    @current_player_count.setter
    def current_player_count(self, value: int) -> None:
        self.raw[GamePropertyKey.PlayerCount.value] = Int8Parameter(value)

    @property
    def game_master(self) -> str:
        key = GamePropertyKey.GameMaster.value
        return cast(StringParameter, self.raw[key]).value if key in self.raw else ""

    @game_master.setter
    def game_master(self, value: str) -> None:
        self.raw[GamePropertyKey.GameMaster.value] = StringParameter(value)

    @property
    def max_players_int(self) -> int:
        key = GamePropertyKey.MaxPlayersInt.value
        return cast(Int32Parameter, self.raw[key]).value if key in self.raw else 0

    @max_players_int.setter
    def max_players_int(self, value: int) -> None:
        self.raw[GamePropertyKey.MaxPlayersInt.value] = Int32Parameter(value)

    @property
    def is_open(self) -> bool:
        key = GamePropertyKey.IsOpen.value
        return cast(BooleanParameter, self.raw[key]).value if key in self.raw else False

    @is_open.setter
    def is_open(self, value: bool) -> None:
        self.raw[GamePropertyKey.IsOpen.value] = BooleanParameter(value)

    @property
    def player_capacity(self) -> int:
        key = GamePropertyKey.MaxPlayers.value
        return cast(Int8Parameter, self.raw[key]).value if key in self.raw else 0

    @player_capacity.setter
    def player_capacity(self, value: int) -> None:
        self.raw[GamePropertyKey.MaxPlayers.value] = Int8Parameter(value)

    @property
    def is_visible(self) -> bool:
        key = GamePropertyKey.IsVisible.value
        return cast(BooleanParameter, self.raw[key]).value if key in self.raw else False

    @is_visible.setter
    def is_visible(self, value: bool) -> None:
        self.raw[GamePropertyKey.IsVisible.value] = BooleanParameter(value)

    @property
    def master_client_id(self) -> int:
        key = GamePropertyKey.MasterClientId.value
        return cast(Int32Parameter, self.raw[key]).value if key in self.raw else 0

    @master_client_id.setter
    def master_client_id(self, value: int) -> None:
        self.raw[GamePropertyKey.MasterClientId.value] = Int32Parameter(value)

    @property
    def player_ttl(self) -> int:
        key = GamePropertyKey.PlayerTtl.value
        return cast(Int32Parameter, self.raw[key]).value if key in self.raw else 0

    @player_ttl.setter
    def player_ttl(self, value: int) -> None:
        self.raw[GamePropertyKey.PlayerTtl.value] = Int32Parameter(value)

    @property
    def empty_room_ttl(self) -> int:
        key = GamePropertyKey.EmptyRoomTtl.value
        return cast(Int32Parameter, self.raw[key]).value if key in self.raw else 0

    @empty_room_ttl.setter
    def empty_room_ttl(self, value: int) -> None:
        self.raw[GamePropertyKey.EmptyRoomTtl.value] = Int32Parameter(value)

    @property
    def props_listed_in_lobby(self) -> list[str]:
        key = GamePropertyKey.PropsListedInLobby.value
        if key not in self.raw:
            return []
        slice_param = cast("SliceParameter[StringParameter]", self.raw[key])
        return [cast(StringParameter, p).value for p in slice_param.value]

    @props_listed_in_lobby.setter
    def props_listed_in_lobby(self, keys: list[str]) -> None:
        self.raw[GamePropertyKey.PropsListedInLobby.value] = SliceParameter(
            [StringParameter(k) for k in keys]
        )
