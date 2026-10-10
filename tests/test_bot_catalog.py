"""The action catalog: one action per RPC, typed argument parsing."""

from __future__ import annotations

import pytest

from src.bot.catalog import ACTIONS, ArgError, find, parse_args
from src.protocol import rpc
from src.protocol.rpc_table import RPCS


def test_every_rpc_is_an_action() -> None:
    assert set(ACTIONS) == set(RPCS)
    assert find("acceptgrant").code == 47
    assert find(96).name == "GameSpeedChange"
    assert ACTIONS[21].kind == "player"
    assert ACTIONS[118].kind == "host"
    assert ACTIONS[5].kind == "handshake"


def test_blocked_actions_name_the_unknown_type() -> None:
    assert ACTIONS[56].blocked == "wire format unknown: Vector2"
    assert ACTIONS[47].blocked == ""


def test_sendable_actions_build() -> None:
    for action in ACTIONS.values():
        if action.blocked:
            continue
        sample = {"int": "1", "signed char": "0", "float": "1.5", "bool": "yes"}
        sample |= {"string": "x", "MemoryBlock": "00", "ObjectId": "5,6"}
        values = [sample[a.type] for a in action.args]
        rpc.build(action.code, *parse_args(action, values))


def test_object_id_from_state_index() -> None:
    args = parse_args(ACTIONS[45], ["#17"], resolve={17: 8427316}.get)
    assert args == [(8427316, 17)]
    with pytest.raises(ArgError, match="not in the game state"):
        parse_args(ACTIONS[45], ["#3"], resolve={}.get)


def test_bad_values_and_counts() -> None:
    with pytest.raises(ArgError, match="true/false"):
        parse_args(ACTIONS[65], ["maybe"])
    with pytest.raises(ArgError, match="takes 1 arguments"):
        parse_args(ACTIONS[47], [])
    with pytest.raises(ArgError, match="unknown"):
        parse_args(ACTIONS[56], ["1,2", "3"])
