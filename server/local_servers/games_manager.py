from typing import Any, Dict

from server.errors import GameDoesNotExistError
from server.models.game_object import GameObject
from server.photon.enum_lookups import CommandParams
from server.photon.param.int32_param import Int32Parameter
from server.photon.param.parameter_key import ParameterKey
from server.photon.param.string_param import StringParameter


class GamesManager:
    _instance = None
    _games: Dict[str, "GameObject"]

    def __new__(cls, *args: Any, **kwargs: Any):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._games = {}
        return cls._instance

    def create_game(
        self, name: str, owner: str, password_required: bool = False, capacity: int = 4
    ) -> "GameObject":
        new_game = GameObject(
            name=name,
            owner=owner,
            password_required=password_required,
            player_count=0,
            player_capacity=capacity,
        )
        self._games[name] = new_game
        return new_game

    def __getitem__(self, key: Any):
        if not isinstance(key, (str, StringParameter)):
            raise TypeError(f"Expected key of type str, got {type(key).__name__}")
        if isinstance(key, StringParameter):
            key = key.value
        assert isinstance(key, str)
        if key not in self._games:
            raise GameDoesNotExistError(f"The game {key} does not exist!")
        return self._games[key]

    def get_games(self) -> Dict[str, GameObject]:
        return self._games

    def app_stats(self) -> CommandParams:
        return {
            ParameterKey.MasterPeerCount: Int32Parameter(1),
            ParameterKey.GameCount: Int32Parameter(len(self._games)),
            ParameterKey.PeerCount: Int32Parameter(
                sum(x.player_count for x in self._games.values())
            ),
        }
