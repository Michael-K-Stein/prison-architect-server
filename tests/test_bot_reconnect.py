"""The reconnect policy and the reconnector thread (no network)."""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

from src.bot import reconnect


def test_policy_resyncs_then_rejoins() -> None:
    policy = reconnect.ReconnectPolicy(stall_limit=15, resync_wait=20)
    assert policy.decide(False, 3, 100) == "ok"
    assert policy.decide(False, 16, 101) == "resync"
    assert policy.decide(False, 20, 110) == "wait"
    assert policy.decide(False, 36, 121) == "rejoin"
    policy.reset()
    assert policy.decide(False, 16, 200) == "resync"


def test_policy_recovers_and_rejoins_when_disconnected() -> None:
    policy = reconnect.ReconnectPolicy()
    assert policy.decide(False, 20, 1) == "resync"
    assert policy.decide(False, 1, 2) == "ok"  # snapshots are back
    assert policy.decide(False, 20, 3) == "resync"  # a new stall starts over
    assert policy.decide(True, 0, 4) == "rejoin"


def test_backoff_grows_then_repeats() -> None:
    assert [reconnect.backoff(i) for i in (0, 1, 2, 9)] == [2.0, 4.0, 8.0, 30.0]


class _Session:
    def __init__(self, disconnected: object = None, silent: float = 0.0) -> None:
        self.disconnected = disconnected
        self.state = SimpleNamespace(world_seen=time.time() - silent if silent else 0.0)
        self.client = SimpleNamespace(local_player=SimpleNamespace(actor_number=9))
        self.saves = 0
        self.stopped = False

    def request_save(self, password: str = "") -> None:
        self.saves += 1

    def stop(self) -> None:
        self.stopped = True


def _server(session: _Session) -> SimpleNamespace:
    return SimpleNamespace(
        session=session, stopped=threading.Event(), stop=lambda: None
    )


def test_reconnector_replaces_a_dropped_session(monkeypatch) -> None:
    monkeypatch.setattr(reconnect, "BACKOFF", (0.01,))
    old, new = _Session(disconnected="cause"), _Session()
    server = _server(old)
    worker = reconnect.Reconnector(server, lambda: new, "pw", poll=0.01)
    worker.start()
    deadline = time.time() + 3
    while server.session is old and time.time() < deadline:
        time.sleep(0.01)
    server.stopped.set()
    worker.join(2)
    assert server.session is new and old.stopped and new.saves == 1
    assert worker.rejoins == 1


def test_reconnector_retries_a_full_room(monkeypatch) -> None:
    monkeypatch.setattr(reconnect, "BACKOFF", (0.01,))
    new, tries = _Session(), []

    def rejoin() -> _Session:
        tries.append(1)
        if len(tries) < 3:
            raise RuntimeError("Game full")
        return new

    server = _server(_Session(disconnected="x"))
    worker = reconnect.Reconnector(server, rejoin, "pw", poll=0.01)
    worker.start()
    deadline = time.time() + 3
    while server.session is not new and time.time() < deadline:
        time.sleep(0.01)
    server.stopped.set()
    worker.join(2)
    assert server.session is new and len(tries) == 3


def test_reconnector_asks_for_the_save_when_silent() -> None:
    session = _Session(silent=60)
    server = _server(session)
    worker = reconnect.Reconnector(
        server,
        lambda: _Session(),
        "pw",
        policy=reconnect.ReconnectPolicy(stall_limit=15, resync_wait=1000),
        poll=0.01,
    )
    worker.start()
    deadline = time.time() + 3
    while session.saves == 0 and time.time() < deadline:
        time.sleep(0.01)
    server.stopped.set()
    worker.join(2)
    assert session.saves == 1


def test_is_max_ccu() -> None:
    from pyphotonrealtime.realtime.error_code import ErrorCode
    from pyphotonrealtime.realtime.state import DisconnectCause
    from src.bot.session import ConnectError, MaxCcuError, is_max_ccu

    assert is_max_ccu(DisconnectCause.MaxCcuReached)
    assert is_max_ccu(ErrorCode.MaxCcuReached)
    assert is_max_ccu(MaxCcuError("Photon CCU limit reached"))
    assert is_max_ccu(ConnectError("disconnected: DisconnectCause.MaxCcuReached"))
    assert is_max_ccu("join failed: MaxCcuReached (code 32757)")
    assert is_max_ccu(32757)
    assert is_max_ccu(11)

    assert not is_max_ccu(None)
    assert not is_max_ccu(DisconnectCause.ClientTimeout)
    assert not is_max_ccu(ConnectError("no games in this lobby"))
    assert not is_max_ccu("room is closed")
    assert not is_max_ccu(0)


def test_retry_ccu_succeeds_immediately() -> None:
    from src.bot.session import retry_ccu

    sleeps: list[float] = []
    result = retry_ccu(lambda: 42, sleep=sleeps.append)
    assert result == 42
    assert sleeps == []


def test_retry_ccu_retries_and_succeeds() -> None:
    from pyphotonrealtime.realtime.state import DisconnectCause
    from src.bot.session import MaxCcuError, retry_ccu

    calls = 0
    sleeps: list[float] = []

    def action() -> str:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise MaxCcuError(f"CCU limit ({DisconnectCause.MaxCcuReached})")
        return "connected"

    result = retry_ccu(action, sleep=sleeps.append)
    assert result == "connected"
    assert calls == 3
    assert sleeps == [2.0, 4.0]


def test_retry_ccu_non_ccu_fails_fast() -> None:
    from src.bot.session import ConnectError, retry_ccu

    calls = 0
    sleeps: list[float] = []

    def action() -> None:
        nonlocal calls
        calls += 1
        raise ConnectError("game is closed")

    with pytest.raises(ConnectError, match="game is closed"):
        retry_ccu(action, sleep=sleeps.append)
    assert calls == 1
    assert sleeps == []


def test_retry_ccu_exhausts_attempts() -> None:
    from src.bot.session import MaxCcuError, retry_ccu

    calls = 0
    sleeps: list[float] = []

    def action() -> None:
        nonlocal calls
        calls += 1
        raise MaxCcuError("too many users")

    with pytest.raises(MaxCcuError, match="too many users"):
        retry_ccu(action, max_attempts=4, sleep=sleeps.append)
    assert calls == 4
    assert sleeps == [2.0, 4.0, 8.0]


def test_fetch_regions_raises_max_ccu_error(monkeypatch) -> None:
    from pyphotonrealtime.realtime.state import DisconnectCause
    from src.bot import session
    from src.bot.session import MaxCcuError, Options

    fake = _Session(disconnected=DisconnectCause.MaxCcuReached)
    fake.regions = {}
    fake.start = lambda s: None
    fake.wait_for = lambda fn, timeout=20: False
    monkeypatch.setattr(session, "Session", lambda **kw: fake)

    with pytest.raises(MaxCcuError, match="maximum CCU reached"):
        session.fetch_regions(Options(app_id="test"), retry=False)


def test_connect_raises_max_ccu_error(monkeypatch) -> None:
    from pyphotonrealtime.realtime.state import DisconnectCause
    from src.bot import flow
    from src.bot.session import MaxCcuError, Options

    fake = _Session(disconnected=DisconnectCause.MaxCcuReached)
    fake.master = False
    fake.start = lambda s: None
    fake.wait_for = lambda fn, timeout=20: False
    fake.client = SimpleNamespace(local_player=SimpleNamespace(nick_name=""))
    monkeypatch.setattr(flow, "Session", lambda **kw: fake)

    with pytest.raises(MaxCcuError, match="maximum CCU reached"):
        flow.connect(Options(app_id="test"), "eu", retry=False)


def test_enter_room_raises_max_ccu_error() -> None:
    from pyphotonrealtime.realtime.state import DisconnectCause
    from src.bot import flow
    from src.bot.session import MaxCcuError, Options

    # Disconnected with MaxCcuReached
    s = _Session(disconnected=DisconnectCause.MaxCcuReached)
    s.lock = threading.RLock()
    s.joined = False
    s.join_error = ""
    s.join_error_code = None
    s.client = SimpleNamespace(op_join_room=lambda params: True)
    s.wait_for = lambda fn, timeout=20: False

    with pytest.raises(MaxCcuError, match="maximum CCU reached"):
        flow.enter_room(s, Options(app_id="test"), "MyRoom")

    # join_error with 32757
    s2 = _Session()
    s2.lock = threading.RLock()
    s2.joined = False
    s2.join_error = "Server full (code 32757)"
    s2.join_error_code = 32757
    s2.client = SimpleNamespace(op_join_room=lambda params: True)
    s2.wait_for = lambda fn, timeout=20: True

    with pytest.raises(MaxCcuError, match="Server full"):
        flow.enter_room(s2, Options(app_id="test"), "MyRoom")


def test_join_room_retries_on_max_ccu(monkeypatch) -> None:
    from src.bot import flow
    from src.bot.session import MaxCcuError, Options

    monkeypatch.setattr(reconnect, "BACKOFF", (0.001,))
    tries = 0
    fake = _Session()

    def fake_join_once(opts, region, room, recorder, lobby):
        nonlocal tries
        tries += 1
        if tries < 3:
            raise MaxCcuError("CCU limit reached")
        return fake

    monkeypatch.setattr(flow, "_join_room_once", fake_join_once)
    session = flow.join_room(Options(app_id="test"), "eu", "room1")
    assert session is fake
    assert tries == 3
