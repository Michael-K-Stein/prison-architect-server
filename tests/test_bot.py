"""The bot's pure helpers, the slider Application and the speed action (no network)."""

import zlib
import logging
import sys
from contextlib import contextmanager
from os import environ
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput
from pyphotonrealtime.protocol.command_code import CommandCode
from pyphotonrealtime.protocol.packet.factory import PacketFactory
from pyphotonrealtime.protocol.param.int8_slice_param import Int8SliceParameter
from pyphotonrealtime.protocol.param.parameter_key import ParameterKey
from pyphotonrealtime.protocol.serialization_protocol import SerializationProtocol
from pyphotonrealtime.realtime._convert import to_param
from pyphotonrealtime.realtime.lobby import LobbyType, TypedLobby
from pyphotonrealtime.realtime.room import RoomInfo

from src.bot import actions, formatting, slider, speed
from src.bot.recording import RecordingTransport
from src.bot.session import Options, Session, make_settings, split_address
from src.capture import TO_CLIENT, TO_SERVER, Capture, Recorder
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


def test_read_ceo_letter_action_matches_the_capture() -> None:
    session = FakeSession()
    actions.action_read_ceo_letter(actions.Context(session, Options("id")))
    # captures/ad-hoc/read-ceo-letter.sqlite, packet 330
    assert session.sent == [(21, b"\x12\x0eReadCeosLetter\x00")]


def test_grant_actions_send_the_grant_name() -> None:
    session = FakeSession()
    ctx = actions.Context(session, Options("id"))
    actions.action_accept_grant(ctx)
    actions.action_cancel_grant(ctx)
    assert session.sent == [
        (47, build(47, "Grant_bootstraps")),
        (48, build(48, "Grant_bootstraps")),
    ]


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


class _FakeEventClient(_FakeClient):
    """A client that also accepts raised events (for the log and recording tests)."""

    def __init__(self) -> None:
        super().__init__()
        self.raised: list[tuple[int, bytes]] = []

    def op_raise_event(self, code: int, content: bytes, args: object = None) -> bool:
        self.raised.append((code, content))
        return True


@contextmanager
def _file_logging(path: Path, level: int = logging.DEBUG):
    """Send the ``src`` loggers to ``path`` for the duration (no console output)."""
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger("src")
    old_level = root.level
    root.addHandler(handler)
    root.setLevel(level)
    try:
        yield
    finally:
        root.removeHandler(handler)
        root.setLevel(old_level)
        handler.close()


def test_log_file_records_the_menu_and_speed_actions(
    monkeypatch, tmp_path: Path
) -> None:
    picks = iter([actions.action_speed, None])
    monkeypatch.setattr(actions, "pick", lambda *a, **k: next(picks))
    monkeypatch.setattr(actions, "pick_speed", lambda *a, **k: 3)  # "5x"
    log_path = tmp_path / "bot.log"
    session = Session(_FakeEventClient())  # type: ignore[arg-type]
    with _file_logging(log_path):
        actions.menu(actions.Context(session, Options("id")))
    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert any("action action_speed: start" in line for line in lines)
    assert any("speed: 5x chosen, wire value 5" in line for line in lines)
    assert any("sent RPC 96 GameSpeedChange (2 B): queued" in line for line in lines)
    assert any("action action_speed: end" in line for line in lines)
    assert lines[-1].endswith("menu: leave")
    # Per-packet detail only appears at debug level.
    assert any(line.startswith("DEBUG ") and "#2" in line for line in lines)


def test_log_file_has_no_debug_lines_at_info(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(actions, "pick_speed", lambda *a, **k: 1)
    log_path = tmp_path / "info.log"
    session = Session(_FakeEventClient())  # type: ignore[arg-type]
    with _file_logging(log_path, logging.INFO):
        actions.action_speed(actions.Context(session, Options("id")))
    text = log_path.read_text(encoding="utf-8")
    assert "sent RPC 96" in text
    assert "DEBUG" not in text


def _op_bytes(command: CommandCode, code: int, data: bytes) -> bytes:
    """One plaintext Photon packet: an operation (or event) with a Data slice."""
    packet = PacketFactory.operation(
        command,
        operation=code,
        params={ParameterKey.Data: to_param(data)},
        protocol=SerializationProtocol.V18,
    )
    return packet.serialize()


class _FakeTransport:
    """An in-memory transport: sends are kept, receives come from ``inbox``."""

    path = ""

    def __init__(self) -> None:
        self.sent: list[bytes] = []
        self.inbox: list[bytes] = []

    def connect(self, host: str, port: int, timeout: float) -> None:
        pass

    def send(self, data: bytes) -> None:
        self.sent.append(data)

    def receive(self) -> bytes:
        return self.inbox.pop(0) if self.inbox else b""


class _FakeRecordingPeer:
    """The peer attributes that RecordingTransport reads; no network."""

    serialization_protocol = SerializationProtocol.V18
    _aes_key = None


def test_recording_transport_writes_both_directions(tmp_path: Path) -> None:
    path = tmp_path / "bot.sqlite"
    inner = _FakeTransport()
    event = _op_bytes(CommandCode.Event, 13, b"\x04\x34")
    inner.inbox.append(event)
    with Recorder(path) as recorder:
        wrapper = RecordingTransport(inner, recorder, _FakeRecordingPeer())  # type: ignore[arg-type]
        wrapper.connect("10.0.0.1", 5058, 1.0)
        outgoing = _op_bytes(CommandCode.Operation, 96, b"\x02\x05")
        wrapper.send(outgoing)
        assert wrapper.receive() == event  # the bytes pass through unchanged
        assert wrapper.path == ""  # attributes come from the wrapped transport
        assert inner.sent == [outgoing]
    with Capture(path) as cap:
        packets = list(cap.packets())
        sessions = cap.sessions()
    assert [(p.direction, p.code) for p in packets] == [
        (TO_SERVER, 96),
        (TO_CLIENT, 13),
    ]
    assert [p.is_event for p in packets] == [False, True]
    assert len(sessions) == 1
    assert sessions[0][3] == "10.0.0.1:5058"


def test_each_connect_is_its_own_session(tmp_path: Path) -> None:
    path = tmp_path / "hops.sqlite"
    with Recorder(path) as recorder:
        wrapper = RecordingTransport(
            _FakeTransport(),
            recorder,
            _FakeRecordingPeer(),  # type: ignore[arg-type]
        )
        wrapper.connect("10.0.0.1", 5058, 1.0)  # Name Server
        wrapper.send(_op_bytes(CommandCode.Operation, 230, b"\x01"))
        wrapper.connect("10.0.0.2", 5055, 1.0)  # Master Server
        wrapper.send(_op_bytes(CommandCode.Operation, 226, b"\x02"))
    with Capture(path) as cap:
        sessions = cap.sessions()
        packets = list(cap.packets())
    assert [s[3] for s in sessions] == ["10.0.0.1:5058", "10.0.0.2:5055"]
    assert [p.session for p in packets] == [1, 2]


def test_session_recorder_wires_the_peer(tmp_path: Path) -> None:
    path = tmp_path / "wired.sqlite"
    client = _FakeClient()
    client.peer.transport = _FakeTransport()  # type: ignore[attr-defined]
    with Recorder(path) as recorder:
        Session(client, recorder=recorder)  # type: ignore[arg-type]
        assert isinstance(client.peer.transport, RecordingTransport)  # type: ignore[attr-defined]


def test_session_tracks_objectives() -> None:
    session = Session(client=SimpleNamespace(add_callback_target=lambda t: None))
    tree = (
        b"<\tObjective\x02\x04Name\x04\x10FeedAllPrisoners"
        b"\x04Type\x04\x10FeedAllPrisoners\x00>"
    )
    blob = zlib.compress(tree) + len(tree).to_bytes(2, "big") + b"\x03"
    state = b"\x12\x09Objective\x12" + bytes([len(blob)]) + blob
    session.state.apply(9, state)
    assert session.objectives == {"FeedAllPrisoners": "FeedAllPrisoners"}
    assert "FeedAllPrisoners" in actions._menu_title(session)
    session.state.apply(21, b"\x12\x10FeedAllPrisoners\x00")
    assert session.objectives == {}
