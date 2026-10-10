"""Proxy mode: finding games, attaching, and injecting a marked event."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from pyphotonrealtime.protocol.command_code import CommandCode  # noqa: E402
from pyphotonrealtime.protocol.operation_code import OperationCode  # noqa: E402
from pyphotonrealtime.protocol.packet.factory import PacketFactory  # noqa: E402
from pyphotonrealtime.protocol.param.int32_param import Int32Parameter  # noqa: E402
from pyphotonrealtime.protocol.param.parameter_key import ParameterKey  # noqa: E402
from pyphotonrealtime.protocol.param.string_param import StringParameter  # noqa: E402
from pyphotonrealtime.protocol.serialization_protocol import (  # noqa: E402
    SerializationProtocol,
)
from pyphotonrealtime.server import Direction  # noqa: E402

from src.capture import Capture, Recorder  # noqa: E402
from src.capture.render import CompactView, _render  # noqa: E402
from src.cli.attach import GameTracker, event_packet, inject  # noqa: E402
from src.protocol.events import compact_lines  # noqa: E402
from src.protocol.rpc import build  # noqa: E402
from test_capture import FakeSession  # noqa: E402


class Session(FakeSession):
    def __init__(self) -> None:
        super().__init__()
        self.client_key = None
        self.sent: list = []
        self.client_parser.protocol = SerializationProtocol.V18

    def send_to_client(self, packet) -> None:
        self.sent.append(packet)


def _join(name: str):
    return PacketFactory.operation(
        CommandCode.Operation,
        OperationCode.JoinGame,
        {ParameterKey.GameId: StringParameter(name)},
        protocol=SerializationProtocol.V18,
    )


def _joined(actor: int | None, rc: int = 0):
    params = {ParameterKey.ActorNr: Int32Parameter(actor)} if actor else {}
    return PacketFactory.operation(
        CommandCode.OperationResponse,
        OperationCode.JoinGame,
        params,
        return_code=rc,
        protocol=SerializationProtocol.V18,
    )


def _tracker(live: set) -> GameTracker:
    return GameTracker(lambda s: s in live)


def _join_game(tracker: GameTracker, session, name="jail", actor=2) -> None:
    tracker.observe(session, Direction.ToServer, _join(name))
    tracker.observe(session, Direction.ToClient, _joined(actor))


def test_game_appears_after_a_joined_response_only() -> None:
    session = Session()
    tracker = _tracker({session})
    tracker.observe(session, Direction.ToServer, _join("jail"))
    tracker.observe(session, Direction.ToClient, _joined(None))  # Master: an address
    assert tracker.games() == []
    tracker.observe(session, Direction.ToClient, _joined(2))
    (game,) = tracker.games()
    assert (game.name, game.actor, game.number) == ("jail", 2, 1)


def test_refused_join_is_not_a_game() -> None:
    session = Session()
    tracker = _tracker({session})
    tracker.observe(session, Direction.ToServer, _join("jail"))
    tracker.observe(session, Direction.ToClient, _joined(2, rc=32758))
    assert tracker.games() == []


def test_attach_by_number_name_or_alone() -> None:
    a, b = Session(), Session()
    tracker = _tracker({a, b})
    with pytest.raises(ValueError, match="no game"):
        tracker.attach(None)
    _join_game(tracker, a, "one")
    assert tracker.attach(None).name == "one"
    _join_game(tracker, b, "two")
    with pytest.raises(ValueError, match="several"):
        tracker.attach(None)
    assert tracker.attach("2").name == "two"
    assert tracker.attach("one").session is a
    with pytest.raises(ValueError, match="no single"):
        tracker.attach("nope")


def test_status_and_dead_client() -> None:
    session = Session()
    live = {session}
    tracker = _tracker(live)
    assert "not attached" in tracker.status()
    _join_game(tracker, session)
    tracker.attach("jail")
    assert tracker.status() == "attached: jail as actor 2"
    live.clear()
    assert tracker.current() is None and "client gone" in tracker.status()
    assert tracker.games() == []


def test_reconnect_reattaches_by_name() -> None:
    old, new = Session(), Session()
    live = {old}
    tracker = _tracker(live)
    _join_game(tracker, old)
    tracker.attach("jail")
    live.clear()
    live.add(new)
    _join_game(tracker, new, actor=3)
    assert tracker.current().session is new


def test_event_packet_layout() -> None:
    session = Session()
    tracker = _tracker({session})
    _join_game(tracker, session, actor=4)
    packet = event_packet(tracker.games()[0], 117, 3, "hello")
    payload = packet.get_payload()
    assert packet.get_header().get_command_code() == CommandCode.Event
    assert payload.operation_code == 117
    assert payload.params[ParameterKey.ActorNr].value == 4
    assert bytes(payload.params[ParameterKey.Data].value) == build(117, 3, "hello")
    assert "Event 117 NewSpeechAdded" in compact_lines(packet)[0]


def test_injected_packet_is_sent_and_marked_in_the_capture(tmp_path: Path) -> None:
    session = Session()
    tracker = _tracker({session})
    _join_game(tracker, session)
    path = tmp_path / "c.sqlite"
    with Recorder(path) as rec:
        rec.record(session, Direction.ToClient, _joined(2))
        packet, packet_id = inject(tracker.games()[0], 117, 3, "hi", record=rec.record)
    assert session.sent == [packet] and packet_id == 2
    with Capture(path) as cap:
        real, fake = list(cap.packets())
    assert (real.injected, fake.injected) == (False, True)
    assert fake.is_event and fake.code == 117
    header, _ = _render(fake, raw=False)
    assert "[injected]" in header
    assert "[injected]" in CompactView().render(fake)[0]
    assert "[injected]" not in CompactView().render(real)[0]


def test_old_capture_without_the_column(tmp_path: Path) -> None:
    import sqlite3

    path = tmp_path / "old.sqlite"
    with Recorder(path) as rec:
        rec.record(Session(), Direction.ToClient, _joined(2))
    db = sqlite3.connect(path)
    db.execute("ALTER TABLE packets DROP COLUMN injected")
    db.commit()
    db.close()
    with Capture(path) as cap:
        assert [p.injected for p in cap.packets()] == [False]
    with Recorder(path) as rec:  # reopening migrates it
        rec.record(Session(), Direction.ToClient, _joined(2))
    with Capture(path) as cap:
        assert [p.injected for p in cap.packets()] == [False, False]
