"""The reconnect policy and the reconnector thread (no network)."""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

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
