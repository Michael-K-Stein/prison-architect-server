"""The action catalog: one action per RPC, typed argument parsing."""

from __future__ import annotations

import pytest

from src.bot.catalog import ACTIONS, ArgError, Choice, choices, find, parse_args
from src.bot.state import GameState
from src.protocol.rpc import build
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
    assert ACTIONS[88].blocked == "wire format unknown: NetworkSoundId, SoundConstraint"
    assert ACTIONS[56].blocked == ""


def test_sendable_actions_build() -> None:
    for action in ACTIONS.values():
        if action.blocked:
            continue
        sample = {"int": "1", "signed char": "0", "float": "1.5", "bool": "yes"}
        sample |= {"string": "x", "MemoryBlock": "00", "ObjectId": "5,6"}
        sample |= {"SoundObjectId": "5,6", "WorldPosition": "1,2", "Vector2": "1,2"}
        sample |= {"Vector3": "1,2,3", "MisconductPolicy": "1,2,yes,no,3"}
        sample |= {"CustomSectorNetworkData": ",".join(["1"] * 12)}
        values = [sample[a.type] for a in action.args]
        rpc.build(action.code, *parse_args(action, values))


def test_object_id_from_state_index() -> None:
    state = GameState()
    state.apply(13, build(13, (8427316, 17), 132))
    assert parse_args(ACTIONS[45], ["#17"], state) == [(8427316, 17)]
    with pytest.raises(ArgError, match="not in the game state"):
        parse_args(ACTIONS[45], ["#3"], state)


def test_choices_by_label() -> None:
    state = GameState()
    state.apply(13, build(13, (8427316, 17), 132))  # a Warden
    state.apply(13, build(13, (8427400, 18), 231))  # a desk: not staff
    assert [c.label for c in choices(ACTIONS[45].args[0], state)] == ["Warden #17"]
    assert parse_args(ACTIONS[45], ["warden #17"], state) == [(8427316, 17)]
    assert parse_args(ACTIONS[43], ["RiotPolice"], state) == [3]
    assert parse_args(ACTIONS[96], ["paused"]) == [0]
    assert choices(ACTIONS[65].args[0]) == [
        Choice(True, "true"),
        Choice(False, "false"),
    ]
    assert choices(ACTIONS[51].args[0], state) == []  # shares: free input


def test_bad_values_and_counts() -> None:
    with pytest.raises(ArgError, match="true/false"):
        parse_args(ACTIONS[65], ["maybe"])
    with pytest.raises(ArgError, match="takes 1 arguments"):
        parse_args(ACTIONS[47], [])
    with pytest.raises(ArgError, match="unknown"):
        parse_args(ACTIONS[95], ["0"])
    with pytest.raises(ArgError, match="takes 2 values"):
        parse_args(ACTIONS[56], ["1,2", "3"])


def test_composites_round_trip() -> None:
    args = parse_args(ACTIONS[61], ["4", "1,2,true,false,3", "5"])
    data = rpc.build(61, *args)
    assert data == bytes.fromhex("0204 0201 0202 01 00 0203 0205")
    assert rpc.parse(61, data).args[1] == ("MisconductPolicy", (1, 2, True, False, 3))


def test_wage_change_takes_a_room_type_name() -> None:
    from src.bot import catalog

    assert catalog.parse_args(catalog.ACTIONS[116], ["Kitchen", "0.6"]) == [8, 0.6]
