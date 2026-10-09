"""The bot's pure helpers, the slider Application and the speed action (no network)."""

import sys
from os import environ
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput
from pyphotonrealtime.protocol.param.int8_slice_param import Int8SliceParameter
from pyphotonrealtime.protocol.param.parameter_key import ParameterKey
from pyphotonrealtime.realtime._convert import to_param
from pyphotonrealtime.realtime.lobby import LobbyType, TypedLobby
from pyphotonrealtime.realtime.room import RoomInfo

from src.bot import actions, formatting, slider, speed
from src.bot.session import Options, Session, make_settings, split_address
from src.env import load_env
from src.protocol.rpc import build

LABELS = [name for name, _ in speed.SPEED_STOPS]
# Event 13 (ObjectAdded) and 9 (DirectoryData) payloads from run4 / run2.
OBJECT_ADDED = bytes.fromhex("043497800211028b")
DIRECTORY = bytes.fromhex(
    "120a4f626a656374446174611219789cb3e1f24fca4a4d2e71492c496460b00300247d04560f02"
)


@pytest.mark.parametrize("index", range(len(LABELS)))
def test_render_slider_marks_the_current_stop(index: int) -> None:
    text = slider.plain(slider.render_slider(LABELS, index))
    bar, names = text.splitlines()[-2:]
    assert bar.count("◉") == 1
    assert bar.count("●") == index
    assert bar.count("○") == len(LABELS) - 1 - index
    assert all(label in names for label in LABELS)
    selected = [s for s, t in slider.render_slider(LABELS, index) if "reverse" in s]
    assert [
        t.strip() for s, t in slider.render_slider(LABELS, index) if s in selected
    ] == [LABELS[index]]
    # The dot sits over its label.
    assert (
        abs(bar.index("◉") - (names.index(LABELS[index]) + len(LABELS[index]) // 2))
        <= 1
    )


@pytest.mark.parametrize(
    ("index", "key", "expected"),
    [
        (1, "left", (0, None)),
        (0, "left", (0, None)),
        (1, "h", (0, None)),
        (1, "right", (2, None)),
        (4, "l", (4, None)),
        (2, "enter", (2, "submit")),
        (2, "escape", (2, "cancel")),
        (2, "q", (2, "cancel")),
        (2, "x", (2, None)),
    ],
)
def test_handle_key(index: int, key: str, expected: tuple[int, str | None]) -> None:
    assert slider.handle_key(index, key, len(LABELS)) == expected


def test_speed_mapping() -> None:
    assert [speed.speed_wire_value(i) for i in range(5)] == [0, 1, 2, 5, 10]
    assert [speed.speed_wire_value(i, speed_index=True) for i in range(5)] == [
        0,
        1,
        2,
        3,
        4,
    ]


def test_speed_packet_bytes() -> None:
    assert build(speed.GAME_SPEED_CHANGE, 5) == b"\x02\x05"
    assert build(speed.GAME_SPEED_CHANGE, 0) == b"\x00"
    assert build(speed.GAME_SPEED_CHANGE, 10) == b"\x02\x0a"


def test_bytes_payload_goes_out_as_int8_slice() -> None:
    param = to_param(build(96, 2))
    assert isinstance(param, Int8SliceParameter)
    assert bytes(param.value) == b"\x02\x02"
    assert ParameterKey.Data == 245
    assert ParameterKey.Code == 244


def test_room_region_lobby_formatting() -> None:
    room = RoomInfo("Cell Block A")
    room.player_count, room.max_players = 2, 4
    assert formatting.format_room(room) == "Cell Block A  (2/4)  open"
    room.is_open = False
    room.max_players = 0
    assert formatting.format_room(room) == "Cell Block A  (2/?)  closed"
    assert formatting.format_region("eu", "1.2.3.4:4530").startswith("eu ")
    assert formatting.format_lobby(TypedLobby()) == "(default)  [Default]"
    sql = TypedLobby("x", LobbyType.SqlLobby)
    assert formatting.format_lobby(sql) == "x  [SqlLobby]"


def test_event_lines_for_a_captured_rpc() -> None:
    lines = formatting.format_event_lines(3, 13, OBJECT_ADDED)
    assert lines[0].startswith("#3 RPC 13 ObjectAdded")
    assert any("uId 8427316" in line for line in lines)


def test_directory_data_is_summarised_unless_verbose() -> None:
    (line,) = formatting.format_event_lines(1, 9, DIRECTORY)
    assert "[handshake]" in line
    assert "'ObjectData'" in line
    assert "25 B" in line
    assert len(formatting.format_event_lines(1, 9, DIRECTORY, verbose=True)) > 1


def test_event_lines_fall_back_for_bad_payloads() -> None:
    unknown = formatting.format_event_lines(1, 190, b"\x02\x05")
    assert "190" in unknown[0]
    assert "non-byte" in formatting.format_event_lines(1, 5, {"a": 1})[0]
    junk = formatting.format_event_lines(1, 13, b"\xff")
    assert "ff" in "".join(junk)


def test_split_address_and_name_server() -> None:
    assert split_address("1.2.3.4") == ("1.2.3.4", 0)
    assert split_address("1.2.3.4:5058") == ("1.2.3.4", 5058)
    opts = Options("id", name_server="9.9.9.9:4533")
    settings = make_settings(opts, "eu")
    assert (settings.name_server, settings.name_server_port) == ("9.9.9.9", 4533)
    assert settings.fixed_region == "eu"
    assert settings.app_version == "the_slammer_1.0"


def test_dotenv_does_not_override(tmp_path: Path, monkeypatch) -> None:
    env = tmp_path / ".env"
    env.write_text("A_BOT_TEST=1\nB_BOT_TEST='two'\n# c\n", encoding="utf-8")
    monkeypatch.setenv("A_BOT_TEST", "keep")
    monkeypatch.delenv("B_BOT_TEST", raising=False)
    load_env(env)
    assert environ["A_BOT_TEST"] == "keep"
    assert environ["B_BOT_TEST"] == "two"
    monkeypatch.delenv("B_BOT_TEST")


def run_slider(keys: str) -> int | None:
    with create_pipe_input() as pipe:
        pipe.send_text(keys)
        return slider.pick_speed(1, input=pipe, output=DummyOutput())


def test_slider_application_with_pipe_input() -> None:
    assert run_slider("\x1b[C\x1b[C\r") == 3  # right, right, Enter
    assert run_slider("\x1b[D\r") == 0  # left
    assert run_slider("ll\r") == 3
    assert run_slider("lhq") is None  # q cancels
    assert run_slider("\x1b[C\x1b") is None  # Esc cancels


class FakeSession:
    """Records raise_event calls."""

    def __init__(self) -> None:
        self.sent: list[tuple[int, bytes]] = []
        self.events: list = []
        self.disconnected = None

    def raise_event(self, code: int, data: bytes) -> bool:
        self.sent.append((code, data))
        return True


@pytest.mark.parametrize(
    ("speed_index", "expected"), [(False, b"\x02\x05"), (True, b"\x02\x03")]
)
def test_speed_action_raises_event_96(monkeypatch, speed_index, expected) -> None:
    stop = 3  # "5x"
    monkeypatch.setattr(actions, "pick_speed", lambda *a, **k: stop)
    session = FakeSession()
    ctx = actions.Context(session, Options("id", speed_index=speed_index))
    actions.action_speed(ctx)
    assert session.sent == [(96, expected)]
    assert ctx.log


def test_speed_action_cancel_sends_nothing(monkeypatch) -> None:
    monkeypatch.setattr(actions, "pick_speed", lambda *a, **k: None)
    session = FakeSession()
    actions.action_speed(actions.Context(session, Options("id")))
    assert session.sent == []


def test_actions_registry_and_session_event_filter() -> None:
    assert actions.ACTIONS[0][0] == "Change game speed"
    session = Session(client=SimpleNamespace(add_callback_target=lambda t: None))
    data = Int8SliceParameter(b"\x02\x05")
    session.on_event(SimpleNamespace(code=96, sender=2, parameters={245: data}))
    session.on_event(SimpleNamespace(code=255, sender=0, parameters={}))
    assert list(session.events) == [(2, 96, b"\x02\x05")]


def test_colour_property_matches_the_games_format() -> None:
    assert formatting.colour_property("d97757") == "0xd97757ff"
    assert formatting.colour_property("#D97757") == "0xd97757ff"


class _FakePeer:
    keep_alive_interval = 2.0
    round_trip_time = 337.6
    last_round_trip_time: int | None = None


class _FakePlayer:
    actor_number = 2


class _FakeClient:
    def __init__(self) -> None:
        self.peer = _FakePeer()
        self.local_player = _FakePlayer()
        self.sent: list[tuple[int, dict[str, int]]] = []

    def add_callback_target(self, target: object) -> None:
        pass

    def op_set_properties_of_actor(self, actor: int, props: dict[str, int]) -> bool:
        self.sent.append((actor, props))
        return True


def test_ping_is_reported_like_the_game() -> None:
    client = _FakeClient()
    session = Session(client)  # type: ignore[arg-type]
    assert client.peer.keep_alive_interval == 1.0
    assert not session.report_ping(0.0)  # not joined yet
    session.joined = True
    assert not session.report_ping(10.0)  # arms the first ping for 11.3
    assert not session.report_ping(11.4)  # no round trip measured yet: never P=0
    client.peer.last_round_trip_time = 340
    assert session.report_ping(11.4)
    assert client.sent == [(2, {"P": 337})]
    assert not session.report_ping(15.3)  # next one is due 4 s after the last
    assert session.report_ping(15.4)
    assert len(client.sent) == 2
