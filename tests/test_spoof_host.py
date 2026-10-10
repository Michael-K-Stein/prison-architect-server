from __future__ import annotations

from types import SimpleNamespace

from pyphotonrealtime.protocol.param.int32_param import Int32Parameter
from pyphotonrealtime.protocol.param.parameter_key import ParameterKey
from pyphotonrealtime.server import GameServer

from src.server.game_server import PrisonArchitectGameServer, spoofed_codes


def test_spoofed_codes_from_env(monkeypatch):
    monkeypatch.setenv("PA_SPOOF_HOST_CODES", "118, 49,x")
    assert spoofed_codes() == {118, 49}
    monkeypatch.delenv("PA_SPOOF_HOST_CODES")
    assert spoofed_codes() == frozenset()


def test_sender_is_rewritten_to_host_only_for_listed_codes(monkeypatch):
    host, bot = SimpleNamespace(number=1), SimpleNamespace(number=2)
    room = SimpleNamespace(master_client_id=1, actors={1: host, 2: bot})
    seen = []

    def fake_raise(self, connection, operation, params, *, encrypted):
        seen.append(self._room_of(connection)[1].number)

    monkeypatch.setattr(GameServer, "_room_of", lambda self, c: (room, bot))
    monkeypatch.setattr(GameServer, "_raise_event", fake_raise)
    monkeypatch.setenv("PA_SPOOF_HOST_CODES", "118")
    server = object.__new__(PrisonArchitectGameServer)
    for code in (118, 9):
        params = {ParameterKey.Code: Int32Parameter(code)}
        server._raise_event(None, 0, params, encrypted=False)
    assert seen == [1, 2]
    assert not server._spoofing
