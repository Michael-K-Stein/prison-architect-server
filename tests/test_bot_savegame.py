"""The join handshake: requesting, receiving and loading the save game."""

from __future__ import annotations

import zlib

from src.bot.savegame import SaveTransfer
from src.bot.state import GameState
from src.protocol.rpc import build
from src.protocol.snapshot import Node


def _save_blob() -> bytes:
    objects = b"<\x07Objects\x00\x01<\x05[i 0]\x03\x04Id.i\x01" + (3).to_bytes(
        4, "little"
    )
    objects += b"\x04Id.u\x01" + (8426858).to_bytes(4, "little")
    objects += b"\x04Type\x04\x05Light\x00>>"
    tree = (
        b"<\x08FullSave\x01\x07Balance\x02"
        + b"\x00\x00\x48\x42"
        + b"\x01"
        + objects
        + b">"
    )
    return zlib.compress(tree) + len(tree).to_bytes(2, "big") + b"\x03"


def test_chunks_are_acked_and_joined() -> None:
    sent: list[tuple[int, bytes]] = []
    transfer = SaveTransfer(lambda code, data: sent.append((code, data)))
    transfer.request("123")
    assert sent == [(5, build(5, "123"))]
    blob = _save_blob()
    transfer.on_event(4, b"")
    transfer.on_event(8, b"")
    transfer.on_event(1, build(1, 2, 12345))
    assert transfer.on_event(3, build(3, blob[:10])) == "receiving save: 1/2 chunks"
    assert transfer.tree is None
    transfer.on_event(3, build(3, blob[10:]))
    assert [code for code, _ in sent] == [5, 2, 2]
    assert transfer.tree is not None and transfer.status.startswith("save loaded")

    state = GameState()
    state.load_save(transfer.tree)
    assert state.uid_of(3) == 8426858
    assert state.object_names() == {"Light": 1}
    assert state.value("Save", "", "Balance") == 50.0


def test_problems_and_rooms_from_the_save() -> None:
    cell = Node(
        "[i 0]",
        [("Id.i", 4), ("RoomType", "Cell"), ("RoomError", 4), ("Entity.i", 65)],
    )
    pump = Node("[i 0]", [("Id.i", 59), ("Type", "WaterPumpStation"), ("Pos.x", 19.5)])
    lit = Node("[i 1]", [("Id.i", 1), ("Type", "Light"), ("Powered", True)])
    save = Node(
        "FullSave",
        [],
        [Node("Rooms", [], [cell]), Node("Objects", [], [pump, lit])],
    )
    state = GameState()
    state.load_save(save)
    assert state.room_list() == [{"index": 4, "type": "Cell", "occupant": 65}]
    assert state.problems() == [
        "Cell #4: There are no canteens accessible by this cell. Prisoners in this cell will have nowhere to eat",
        "WaterPumpStation #59 at 19.5,?: no power (a cable must touch it; only lights reach over a gap)",
    ]


def test_wrong_password_and_other_events() -> None:
    transfer = SaveTransfer(lambda code, data: None)
    assert transfer.on_event(9, b"") is None
    assert transfer.on_event(7, b"") == "incorrect password"
