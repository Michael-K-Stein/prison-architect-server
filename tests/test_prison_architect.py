"""PrisonArchitectServer over real sockets, driven by pyPhotonRealtime's client."""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pyphotonrealtime import AppSettings, ClientState, RealtimeClient  # noqa: E402
from pyphotonrealtime.realtime import EnterRoomParams, RoomOptions  # noqa: E402

from prison_architect import PRISON_ARCHITECT_APP_ID, PrisonArchitectServer  # noqa: E402


def wait(done, client: RealtimeClient, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not done():
        assert time.monotonic() < deadline, (client.state, client.disconnect_cause)
        client.service()
        time.sleep(0.005)


def connect(server: PrisonArchitectServer, app_id: str) -> RealtimeClient:
    client = RealtimeClient()
    assert client.connect_using_settings(
        AppSettings(
            app_id_realtime=app_id,
            name_server=server.host,
            name_server_port=server.name_server_port,
            fixed_region="pa-test",
        )
    )
    return client


def main() -> None:
    with PrisonArchitectServer(
        "127.0.0.1",
        region="pa-test",
        max_players=6,
        name_server_port=0,
        master_server_port=0,
        game_server_port=0,
    ) as server:
        # The game sends its app id without dashes.
        client = connect(server, PRISON_ARCHITECT_APP_ID.replace("-", ""))
        wait(lambda: client.state == ClientState.ConnectedToMasterServer, client)
        assert client.op_create_room(
            EnterRoomParams(room_name="prison", room_options=RoomOptions(max_players=2))
        )
        wait(lambda: client.state == ClientState.Joined, client)
        room = server.rooms["prison"]
        assert room.max_players == 6, room.max_players
        assert room.player_ttl > 0 and room.empty_room_ttl > 0
        client.disconnect()

        # Other Photon apps are turned away.
        other = connect(server, "00000000-0000-0000-0000-000000000000")
        wait(lambda: other.state == ClientState.Disconnected, other)
        assert "prison" in server.rooms
    print("ok")


if __name__ == "__main__":
    main()
