from typing import Union, cast

from server.models.properties_base import PropertiesBase
from server.photon.param.hashtable_param import HashtableParameter
from server.photon.param.int8_param import Int8Parameter
from server.photon.param.int32_param import Int32Parameter
from server.photon.param.string_param import StringParameter
from server.photon.property_keys import ActorPropertyKey

ActorPropertiesHashtable = HashtableParameter[
    Union[Int8Parameter, StringParameter],
    Union[StringParameter, Int32Parameter],
]


class ActorProperties(PropertiesBase[ActorPropertiesHashtable]):
    """A clean Pythonic wrapper for reading and writing Prison Architect actor (player) properties."""

    @property
    def player_name(self) -> str:
        key = ActorPropertyKey.PlayerName.value
        return cast(StringParameter, self.raw[key]).value if key in self.raw else ""

    @player_name.setter
    def player_name(self, value: str) -> None:
        self.raw[ActorPropertyKey.PlayerName.value] = StringParameter(value)

    @property
    def ping(self) -> int:
        key = ActorPropertyKey.Ping.value
        return cast(Int32Parameter, self.raw[key]).value if key in self.raw else 0

    @ping.setter
    def ping(self, value: int) -> None:
        self.raw[ActorPropertyKey.Ping.value] = Int32Parameter(value)

    @property
    def user_id(self) -> str:
        key = ActorPropertyKey.UserId.value
        return cast(StringParameter, self.raw[key]).value if key in self.raw else ""

    @user_id.setter
    def user_id(self, value: str) -> None:
        self.raw[ActorPropertyKey.UserId.value] = StringParameter(value)
