"""Recording proxied traffic: a real client through a real proxy to a server.

Also: reading a capture while it is still being written (``Capture.follow``),
the ``capture tail`` and ``capture sessions`` commands, and captures recorded by
older runs.
"""

import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pyphotonrealtime import AppSettings, RealtimeClient  # noqa: E402
from pyphotonrealtime.protocol.command_code import CommandCode  # noqa: E402
from pyphotonrealtime.protocol.deserializer import (  # noqa: E402
    deserialize_photon_payload,
)
from pyphotonrealtime.protocol.packet.header import (  # noqa: E402
    PhotonDataPacketHeader,
)
from pyphotonrealtime.protocol.packet.operation_payload import (  # noqa: E402
    PhotonPacketPayload,
)
from pyphotonrealtime.protocol.serialization_protocol import (  # noqa: E402
    SerializationProtocol,
)
from pyphotonrealtime.server import Direction, PhotonProxy, PhotonServer  # noqa: E402
from pyphotonrealtime.protocol.packet.operation_packet import (  # noqa: E402
    PhotonOperationPacket,
)

from src.capture import TO_CLIENT, TO_SERVER, Capture, Recorder  # noqa: E402
from src.capture.cli import app  # noqa: E402
from src.capture.reader import Packet  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

# SetProperties of the player's colour and ping (run2 packets 30 and 122).
COLOUR = bytes.fromhex(
    "fc0003fb6800017300014373000a30783834373966346666fe6900000001fa6f01"
)
# RaiseEvent of a cash-flow event (run1).
CASHFLOW = bytes.fromhex(
    "fd0002f5780000001b0223121566696e616e63655f636f73745f63617368666c6f770000f46276"
)


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "run.sqlite"
        with (
            PhotonServer(
                name_server_port=0, master_server_port=0, game_server_port=0
            ) as server,
            Recorder(path) as recorder,
            PhotonProxy(
                ("127.0.0.1", server.name_server_port), on_packet=recorder.on_packet
            ) as proxy,
        ):
            server.regions = ("rec-test",)
            client = RealtimeClient()
            assert client.connect_using_settings(
                AppSettings(
                    app_id_realtime="00000000-0000-0000-0000-000000000000",
                    name_server="127.0.0.1",
                    name_server_port=proxy.port,
                    fixed_region="rec-test",
                )
            )
            deadline = time.monotonic() + 5
            # The name server answers with the Master Server's address, which this
            # one-hop proxy doesn't follow; getting that response is enough.
            while not any(True for _ in _responses(recorder)):
                assert time.monotonic() < deadline, client.state
                client.service()
                time.sleep(0.005)
            client.disconnect()
        assert recorder.dropped == 0

        with Capture(path) as cap:
            packets = list(cap.packets())
            assert packets, "nothing recorded"
            assert [p.id for p in packets] == sorted(p.id for p in packets)
            assert len(cap.sessions()) >= 1
            assert {p.direction for p in packets} == {0, 1}, "both directions"
            assert any(p.encrypted for p in packets), (
                "encrypted ops are recorded (as plaintext)"
            )
            ops = [p for p in packets if p.is_operation]
            for p in ops:
                assert p.size == len(p.payload)
                decoded = p.decode()
                assert decoded.operation_code == p.code
                assert p.name
            # Filters.
            to_server = list(cap.packets(direction=Direction.ToServer))
            assert to_server and all(p.direction == 0 for p in to_server)
            sized = list(cap.packets(where="size >= ?", params=(1,), direction=1))
            assert all(p.size >= 1 and p.direction == 1 for p in sized)
            # Plain SQL works too.
            count = cap.db.execute("SELECT count(*) FROM packets").fetchone()[0]
            assert count == len(packets)

        # Appending continues the session numbering.
        with Capture(path) as cap:
            before = max(s[0] for s in cap.sessions())
        with Recorder(path) as again:
            assert again._next_session == before + 1
    print("ok")


def test_recorder_round_trip() -> None:
    main()


def _responses(recorder: Recorder):
    # Peek at what has been flushed so far, without disturbing the writer.
    import sqlite3

    try:
        db = sqlite3.connect(f"file:{recorder.path}?mode=ro", uri=True)
        try:
            yield from db.execute(
                "SELECT 1 FROM packets WHERE dir = 1 AND code IS NOT NULL"
            )
        finally:
            db.close()
    except sqlite3.Error:
        return


# --- Writing without a network: fake sessions and packets ------------------


class _Sock:
    def getpeername(self):
        return ("127.0.0.1", 4530)


class FakeSession:
    """The attributes of a ProxySession that Recorder reads."""

    def __init__(self) -> None:
        self.client = _Sock()
        self.server = _Sock()
        parser = SimpleNamespace(protocol=SerializationProtocol.V6)
        self.client_parser = parser
        self.server_parser = parser


class _Raw:
    """A packet that is not an operation (serialized as its bytes)."""

    def __init__(self, body: bytes) -> None:
        self.body = body

    def get_format(self) -> int:
        return 0xF3

    def serialize(self) -> bytes:
        return self.body


def _op(body: bytes) -> PhotonOperationPacket:
    header = PhotonDataPacketHeader(command_code=CommandCode.Operation)
    code, params, debug = deserialize_photon_payload(header, body)
    return PhotonOperationPacket(
        header, PhotonPacketPayload(code, params, header, debug)
    )


def _write(rec: Recorder, session, direction, start: int, n: int) -> None:
    for i in range(start, start + n):
        rec.on_packet(session, direction, _Raw(f"pkt{i}".encode()))


def _payloads(packets) -> list[bytes]:
    return [p.payload for p in packets]


def test_recorder_is_wal() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "wal.sqlite"
        with Recorder(path):
            pass
        import sqlite3

        db = sqlite3.connect(path)
        try:
            assert db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        finally:
            db.close()


def test_follow_sees_packets_before_close() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "live.sqlite"
        session = FakeSession()
        with Recorder(path) as rec:
            started = time.monotonic()
            _write(rec, session, Direction.ToClient, 0, 3)
            gen = Capture.follow(path, timeout=5, poll=0.02)
            arrivals = []
            for _ in range(3):
                pkt = next(gen)
                arrivals.append(time.monotonic() - started)
                assert pkt.payload == f"pkt{len(arrivals) - 1}".encode()
            # Still recording: the reader saw the rows without a close.
            assert not rec._closed
            assert max(arrivals) < 1.0, arrivals
            gen.close()


def test_follow_is_ordered_and_complete() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "bulk.sqlite"
        session = FakeSession()
        total = 3000

        def produce() -> None:
            with Recorder(path) as rec:
                for start in range(0, total, 100):
                    _write(rec, session, Direction.ToServer, start, 100)
                    time.sleep(0.001)

        writer = threading.Thread(target=produce)
        writer.start()
        got = list(Capture.follow(path, timeout=2, poll=0.02))
        writer.join()
        assert [p.id for p in got] == sorted({p.id for p in got}), "order/duplicates"
        assert _payloads(got) == [f"pkt{i}".encode() for i in range(total)]


def test_from_end_skips_existing_packets() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "end.sqlite"
        session = FakeSession()
        with Recorder(path) as rec:
            _write(rec, session, Direction.ToClient, 0, 3)
            # Wait until the three are on disk before the reader starts.
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                with Capture(path) as cap:
                    if len(list(cap.packets())) == 3:
                        break
                time.sleep(0.02)
            got: list[bytes] = []
            stop = threading.Event()

            def read() -> None:
                for pkt in Capture.follow(path, from_end=True, stop=stop, poll=0.02):
                    got.append(pkt.payload)

            reader = threading.Thread(target=read)
            reader.start()
            time.sleep(0.3)  # let the reader take its starting point
            _write(rec, session, Direction.ToClient, 3, 2)
            deadline = time.monotonic() + 3
            while len(got) < 2 and time.monotonic() < deadline:
                time.sleep(0.02)
            stop.set()
            reader.join()
        assert got == [b"pkt3", b"pkt4"]


def test_follow_after_id() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "after.sqlite"
        with Recorder(path) as rec:
            _write(rec, FakeSession(), Direction.ToClient, 0, 4)
        first = list(Capture.follow(path, timeout=0.3))
        later = list(Capture.follow(path, after=first[1].id, timeout=0.3))
        assert _payloads(later) == [b"pkt2", b"pkt3"]
        with pytest.raises(ValueError):
            list(Capture.follow(path, after=1, from_end=True, timeout=0.1))


def test_follow_timeout_ends_when_idle() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "idle.sqlite"
        with Recorder(path):
            pass
        started = time.monotonic()
        assert list(Capture.follow(path, timeout=0.3, poll=0.05)) == []
        assert time.monotonic() - started < 3


def test_follow_stop_event_ends_reader() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "stop.sqlite"
        with Recorder(path):
            pass
        stop = threading.Event()
        threading.Timer(0.3, stop.set).start()
        started = time.monotonic()
        assert list(Capture.follow(path, stop=stop, poll=0.02)) == []
        assert time.monotonic() - started < 3


def test_follow_waits_for_missing_file() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "later.sqlite"
        session = FakeSession()

        def create_later() -> None:
            time.sleep(0.5)
            with Recorder(path) as rec:
                _write(rec, session, Direction.ToClient, 0, 2)

        writer = threading.Thread(target=create_later)
        writer.start()
        got = list(Capture.follow(path, timeout=1.5, poll=0.02))
        writer.join()
        assert _payloads(got) == [b"pkt0", b"pkt1"]


def test_follow_filters() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "filters.sqlite"
        s1, s2 = FakeSession(), FakeSession()
        colour_code = int(_op(COLOUR).get_payload().operation_code)
        with Recorder(path) as rec:
            _write(rec, s1, Direction.ToServer, 0, 2)  # pkt0, pkt1
            _write(rec, s2, Direction.ToClient, 2, 1)  # pkt2
            rec.on_packet(s1, Direction.ToClient, _op(COLOUR))
            rec.on_packet(s2, Direction.ToServer, _op(CASHFLOW))
        to_server = list(Capture.follow(path, timeout=0.3, direction=TO_SERVER))
        assert [p.payload for p in to_server][:2] == [b"pkt0", b"pkt1"]
        assert all(p.direction == TO_SERVER for p in to_server)
        only_s2 = list(Capture.follow(path, timeout=0.3, session=2))
        assert _payloads(only_s2) == [b"pkt2", CASHFLOW]
        only_colour = list(Capture.follow(path, timeout=0.3, code=colour_code))
        assert [p.code for p in only_colour] == [colour_code]
        only_to_client = list(
            Capture.follow(path, timeout=0.3, direction=Direction.ToClient)
        )
        assert all(p.direction == TO_CLIENT for p in only_to_client)


def test_packet_rebuilds_as_operation() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "op.sqlite"
        with Recorder(path) as rec:
            rec.on_packet(FakeSession(), Direction.ToClient, _op(COLOUR))
        (pkt,) = Capture.follow(path, timeout=0.3)
        rebuilt = pkt.operation()
        assert rebuilt.get_payload().operation_code == pkt.code
        assert rebuilt.log()[0].startswith("Command:")
        raw = Packet(1, 0, 1, 0, None, 0, None, False, 6, None, 0, b"")
        with pytest.raises(ValueError):
            raw.operation()


def test_recorder_close_is_idempotent_and_counts_late_packets() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "closed.sqlite"
        rec = Recorder(path)
        rec.close()
        rec.close()
        rec.on_packet(FakeSession(), Direction.ToClient, _Raw(b"late"))
        assert rec.dropped == 1


def test_old_captures_still_load() -> None:
    # run1..4 are finished recordings; a capture that is still growing (run5
    # while a session is live) would make the two reads below disagree.
    paths = [ROOT / "captures" / f"run{i}.sqlite" for i in range(1, 5)]
    paths = [path for path in paths if path.exists()]
    if not paths:
        pytest.skip("no captures/ recordings in this checkout")
    for path in paths:
        followed = list(Capture.follow(path, timeout=0.2))
        with Capture(path) as cap:
            stored = list(cap.packets())
        assert stored, path
        assert [p.id for p in followed] == [p.id for p in stored], path


def test_tail_and_sessions_commands() -> None:
    runner = CliRunner()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "cli.sqlite"
        with Recorder(path) as rec:
            rec.on_packet(FakeSession(), Direction.ToServer, _op(COLOUR))
            _write(rec, FakeSession(), Direction.ToClient, 0, 1)
        result = runner.invoke(app, ["sessions", str(path)])
        assert result.exit_code == 0, result.output
        assert "client -> upstream" in result.output
        assert "127.0.0.1:4530" in result.output

        result = runner.invoke(
            app, ["tail", str(path), "--from-start", "--timeout", "0.3"]
        )
        assert result.exit_code == 0, result.output
        assert "client -> server" in result.output
        assert "Operation: SetProperties" in result.output
        assert "format 0xf3" in result.output  # the raw packet

        code = int(_op(COLOUR).get_payload().operation_code)
        result = runner.invoke(
            app,
            [
                "tail",
                str(path),
                "--from-start",
                "--timeout",
                "0.3",
                "--code",
                str(code),
            ],
        )
        assert result.exit_code == 0, result.output
        assert "Operation: SetProperties" in result.output
        assert "format 0xf3" not in result.output

        result = runner.invoke(
            app, ["tail", str(path), "--from-start", "--timeout", "0.3", "--raw"]
        )
        assert result.exit_code == 0, result.output
        assert COLOUR.hex() in result.output


if __name__ == "__main__":
    main()
