"""Server-originated events: ``PrisonArchitectGameServer.inject_event``."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pyphotonrealtime.protocol.param.parameter_key import ParameterKey

from src.protocol.rpc import RpcShapeError, build
from src.server.game_server import PrisonArchitectGameServer


def _actor(number: int, sent: list):
    conn = SimpleNamespace(
        send_event=lambda code, params, encrypt=False: sent.append(
            (number, code, params, encrypt)
        )
    )
    return SimpleNamespace(number=number, connection=conn, is_active=True)


def _server(sent: list):
    actors = {1: _actor(1, sent), 2: _actor(2, sent)}
    room = SimpleNamespace(
        name="r",
        actors=actors,
        master_client_id=1,
        active_actors=lambda: list(actors.values()),
    )
    game = object.__new__(PrisonArchitectGameServer)
    game.server = SimpleNamespace(rooms={"r": room})
    return game


def test_event_goes_to_everyone_from_the_host() -> None:
    sent: list = []
    assert _server(sent).inject_event(117, 3, "hello") == 2
    assert {n for n, *_ in sent} == {1, 2}
    _, code, params, encrypted = sent[0]
    assert code == 117 and encrypted
    assert params[ParameterKey.ActorNr].value == 1
    assert bytes(params[ParameterKey.Data].value) == build(117, 3, "hello")


def test_host_only() -> None:
    sent: list = []
    assert _server(sent).inject_event(117, 3, "hi", to="host") == 1
    assert [n for n, *_ in sent] == [1]


def test_bad_arguments() -> None:
    server = _server([])
    with pytest.raises(RpcShapeError):
        server.inject_event(117, 3)
    with pytest.raises(ValueError):
        server.inject_event(117, 3, "x", to="nobody")
