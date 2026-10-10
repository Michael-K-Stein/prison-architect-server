"""Bank balance override and the injecting console commands."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from pyphotonrealtime.protocol.command_code import CommandCode  # noqa: E402
from pyphotonrealtime.protocol.packet.factory import PacketFactory  # noqa: E402
from pyphotonrealtime.protocol.param.int32_param import Int32Parameter  # noqa: E402
from pyphotonrealtime.protocol.param.parameter_key import ParameterKey  # noqa: E402
from pyphotonrealtime.protocol.serialization_protocol import (  # noqa: E402
    SerializationProtocol,
)
from pyphotonrealtime.realtime._convert import to_param  # noqa: E402
from pyphotonrealtime.server import Direction  # noqa: E402

from src.cli.balance import BalanceOverride, snapshot_data  # noqa: E402
from src.cli.console import CommandTable  # noqa: E402
from src.cli.inject_commands import inject_commands  # noqa: E402
from src.protocol.rpc import build  # noqa: E402
from src.protocol.snapshot import (  # noqa: E402
    Node,
    compress,
    decode_args,
    decompress,
    encode_tree,
)
from test_attach import Session, _join_game, _tracker  # noqa: E402
from test_pa_events import FINANCE, decode_and_get  # noqa: E402


def _balance_of(data: bytes) -> int:
    tree = decompress(decode_args(data)[1]).tree
    node = tree if tree.name == "Finance" else tree.children[0]
    return dict(node.fields)["v.6" if tree.name == "Finance" else "Balance"]


def _finance_event(balance: int, actor: int = 1):
    tree = Node("Finance", [("v.6", balance)])
    data = build(9, "Finance", compress(encode_tree(tree)))
    return PacketFactory.event(
        9,
        {
            ParameterKey.ActorNr: Int32Parameter(actor),
            ParameterKey.Data: to_param(data),
        },
        protocol=SerializationProtocol.V18,
    )


def test_override_adds_an_offset_and_tracks_real_changes() -> None:
    session = object()
    over = BalanceOverride()
    assert over.rewrite(session, decode_and_get(FINANCE)) is None  # learns 30110
    assert over.pin(session, 1_000_000) == 1_000_000 - 30110
    changed = over.rewrite(session, build(9, "Finance", _blob(30110 - 500)))
    assert _balance_of(changed) == 1_000_000 - 500  # spending still shows
    assert over.shown(session) == 1_000_000 - 500
    over.release()
    assert over.rewrite(session, build(9, "Finance", _blob(100))) is None


def _blob(balance: int) -> bytes:
    return compress(encode_tree(Node("Finance", [("v.6", balance)])))


def test_only_the_pinned_session_is_rewritten() -> None:
    a, b = object(), object()
    over = BalanceOverride()
    over.rewrite(a, build(9, "Finance", _blob(10)))
    over.rewrite(b, build(9, "Finance", _blob(10)))
    over.pin(a, 99)
    assert over.rewrite(b, build(9, "Finance", _blob(20))) is None
    assert _balance_of(over.rewrite(a, build(9, "Finance", _blob(20)))) == 109


def test_pin_needs_a_seen_balance_and_world_snapshots_work() -> None:
    session = object()
    over = BalanceOverride()
    with pytest.raises(ValueError, match="no balance"):
        over.pin(session, 5)
    world = snapshot_data("World", 300)
    over.rewrite(session, world)
    over.pin(session, 1000)
    assert _balance_of(over.rewrite(session, snapshot_data("World", 250))) == 950


def test_unrelated_snapshots_are_left_alone() -> None:
    over = BalanceOverride()
    other = build(9, "Intake", compress(encode_tree(Node("Intake", [("x", 1)]))))
    assert over.rewrite(object(), other) is None
    assert over.rewrite(object(), b"\xff") is None


def _setup():
    session = Session()
    tracker = _tracker({session})
    _join_game(tracker, session, actor=3)
    over = BalanceOverride()
    seen: list = []
    shown: list = []

    def record(sess, direction, packet, injected=False):
        seen.append((direction, packet, injected))
        return len(seen)

    table = CommandTable(
        inject_commands(tracker, over, record, lambda *a, **k: shown.append((a, k)))
    )
    return session, tracker, over, table, seen, shown


def test_host_actor_is_learned_from_directory_data() -> None:
    session, tracker, *_ = _setup()
    assert tracker.games()[0].host_actor is None
    tracker.observe(session, Direction.ToClient, _finance_event(5, actor=7))
    assert tracker.games()[0].host_actor == 7


def test_commands_need_an_attached_game() -> None:
    *_, table, seen, _ = _setup()
    for line in ("/say CEO hi", "/cash 5", "/balance 5", "/inject GameSpeedChange 1"):
        assert "not attached" in table.run(line), line
    assert seen == []


def test_cash_and_inject_send_marked_events() -> None:
    session, tracker, over, table, seen, shown = _setup()
    tracker.attach("jail")
    assert table.run("/cash 500") == ""
    assert table.run("/inject GameSpeedChange 2") == ""
    assert [s.get_payload().operation_code for s in session.sent] == [118, 96]
    assert bytes(
        session.sent[0].get_payload().params[ParameterKey.Data].value
    ) == build(118, 500, "finance_cost_cashflow", 0, 0)
    assert all(injected for _, _, injected in seen) and len(shown) == 2
    assert "unknown RPC" in table.run("/inject Nope")
    assert table.run("/inject GameSpeedChange").startswith("/inject RPC")


def test_balance_command_pushes_both_snapshots_from_the_host() -> None:
    session, tracker, over, table, seen, shown = _setup()
    tracker.attach("jail")
    assert "not seen" in table.run("/balance")
    event = _finance_event(30110, actor=1)
    over.rewrite(session, bytes(event.get_payload().params[ParameterKey.Data].value))
    assert "host hasn't sent" in table.run("/balance 1000000")
    tracker.observe(session, Direction.ToClient, event)
    assert "client now shows 1000000" in table.run("/balance 1000000")
    assert len(session.sent) == 2
    for packet in session.sent:
        payload = packet.get_payload()
        assert payload.params[ParameterKey.ActorNr].value == 1  # the host, not us
        assert packet.get_header().get_command_code() == CommandCode.Event
        assert _balance_of(bytes(payload.params[ParameterKey.Data].value)) == 1_000_000
    assert "offset +969890" in table.run("/balance")
    session.sent.clear()
    assert "real balance" in table.run("/balance off")
    assert (
        _balance_of(
            bytes(session.sent[0].get_payload().params[ParameterKey.Data].value)
        )
        == 30110
    )


def test_say_without_args_offers_the_speakers() -> None:
    from src.bot.broadcast import SPEAKERS
    from src.cli.console import Choose

    _session, tracker, _over, table, _seen, _shown = _setup()
    tracker.attach(None)
    with pytest.raises(Choose) as ask:
        table.run("/say")
    assert ask.value.options == list(SPEAKERS)
    assert ask.value.template.format("CEO") == "/say CEO "
