"""Recording proxied traffic: a real client through a real proxy to a server."""

import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pyphotonrealtime import AppSettings, RealtimeClient  # noqa: E402
from pyphotonrealtime.server import Direction, PhotonProxy, PhotonServer  # noqa: E402

from capture import Capture, Recorder  # noqa: E402


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


if __name__ == "__main__":
    main()
