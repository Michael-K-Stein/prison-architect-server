"""Parsing the game's RaiseEvent payloads, on bytes from captures/run1.sqlite."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pyphotonrealtime.protocol.command_code import CommandCode  # noqa: E402
from pyphotonrealtime.protocol.deserializer import (  # noqa: E402
    deserialize_photon_payload,
)
from pyphotonrealtime.protocol.packet.header import (  # noqa: E402
    PhotonDataPacketHeader,
)
from pyphotonrealtime.protocol.packet.operation_packet import (  # noqa: E402
    PhotonOperationPacket,
)
from pyphotonrealtime.protocol.packet.operation_payload import (  # noqa: E402
    PhotonPacketPayload,
)

from src.protocol.events import (  # noqa: E402
    format_event,
    is_hidden,
    log_lines,
    packet_label,
)
from src.protocol.rpc import build, encode_args, rpc_name  # noqa: E402
from src.protocol.snapshot import (  # noqa: E402
    Node,
    decode_args,
    decode_tree,
    decompress,
    format_tree,
)

# Whole RaiseEvent operation payloads (packets 31 and 35).
CASHFLOW = bytes.fromhex(
    "fd0002f5780000001b0223121566696e616e63655f636f73745f63617368666c6f770000f46276"
)
# SetProperties of the player's colour and ping (run2 packets 30 and 122).
COLOUR = bytes.fromhex(
    "fc0003fb6800017300014373000a30783834373966346666fe6900000001fa6f01"
)
PING = bytes.fromhex("fc0003fb68000173000150690000014ffe6900000001fa6f01")
FOUNDATIONS = bytes.fromhex(
    "fd0002f5780000001f0ba014121866696e616e63655f636f73745f666f756e646174696f6e73"
    "0000f46276"
)
SPAWN = bytes.fromhex("fd0002f57800000008043497800211028bf4620d")
FINANCE = bytes.fromhex(
    "fd0002f57800000033120746696e616e63651228789cb36177cbcc4bcc4b4e65622929d24b62ac"
    "2e6560602ed333639c076430d8010085e807941f02f46209"
)


def packet(body: bytes) -> PhotonOperationPacket:
    header = PhotonDataPacketHeader(command_code=CommandCode.Operation)
    code, params, _ = deserialize_photon_payload(header, body)
    return PhotonOperationPacket(header, PhotonPacketPayload(code, params, header))


def decode_and_get(body: bytes) -> bytes:
    return bytes(packet(body).get_payload().params[245].value)


def test_payloads() -> None:
    data = bytes(packet(CASHFLOW).get_payload().params[245].value)
    assert decode_args(data) == [35, b"finance_cost_cashflow", 0, 0]

    data = bytes(packet(FINANCE).get_payload().params[245].value)
    name, blob = decode_args(data)
    assert name == b"Finance"
    tree = decompress(blob).tree
    assert tree is not None
    assert tree.name == "Finance"
    assert tree.fields == [("tr.b", 30075), ("v.6", 30110)]
    assert format_event(9, data) == [
        "Event 9 (DirectoryData):",
        "  'Finance'",
        "  snapshot: 40 B zlib -> 31 B",
        "    Finance {tr.b=30075, v.6=30110}",
    ]

    lines = log_lines(packet(FINANCE))
    assert "    Finance {tr.b=30075, v.6=30110}" in lines[-1], lines
    assert not any(line.startswith("  Data/") for line in lines), lines

    label = packet_label(packet(FINANCE))
    assert label == "RaiseEvent:DirectoryData:Finance", label
    assert is_hidden(label, ["RaiseEvent:DirectoryData"])
    assert is_hidden(label, ["RaiseEvent:DirectoryData:Finance"])
    assert not is_hidden(label, ["RaiseEvent:DirectoryData:Fin", "RaiseEvent:Other"])

    assert format_event(118, decode_and_get(CASHFLOW)) == [
        "Event 118 (TransactionAdded):",
        "  finance_cost_cashflow: amount +35 (int 0, string '')",
    ]
    assert packet_label(packet(CASHFLOW)) == "RaiseEvent:TransactionAdded"

    lines = log_lines(packet(COLOUR))
    assert lines[-1] == "  Actor 1: colour = #8479f4 (alpha ff) (broadcast)", lines
    assert not any("Broadcast" in line for line in lines), lines
    lines = log_lines(packet(PING))
    assert lines[-1] == "  Actor 1: ping = 335 ms (broadcast)", lines

    # Paying for a 17x14 concrete foundation (run4 packet 274): negative int tag.
    data = decode_and_get(FOUNDATIONS)
    assert decode_args(data) == [-5280, b"finance_cost_foundations", 0, 0]
    assert format_event(118, data)[1] == (
        "  finance_cost_foundations: amount -5280 (int 0, string '')"
    )
    # The delivery truck spawning (run4 packet 327).
    assert format_event(13, decode_and_get(SPAWN)) == [
        "Event 13 (ObjectAdded):",
        "  uId 8427316 as object 17, type 139",
    ]
    # Float tag 0x1a (a sound's position) and a null string (length 0xff, -1).
    assert decode_args(bytes.fromhex("1a00002242")) == [40.5]
    assert decode_tree(bytes.fromhex("3c014101014104ffffffffff003e")).fields == [
        ("A", None)
    ]

    # Anything that doesn't parse is shown raw rather than raising.
    assert "unparsed" in format_event(9, b"\xff")[0]

    # gt is the game speed (run3 packets 1021 and 847).
    world = Node("World", children=[Node("ClientData", [("gt", 10.0)])])
    assert format_tree(world)[1] == "  ClientData {gt=10 (speed 10x)}"
    assert format_tree(Node("ClientData", [("gt", 0.0)])) == [
        "ClientData {gt=0 (paused)}"
    ]


def test_legacy_names_still_filter() -> None:
    # Old filters (our own names for 9, 13, 118) match the game's names.
    finance = "RaiseEvent:DirectoryData:Finance"
    assert is_hidden(finance, ["RaiseEvent:SystemState"])
    assert is_hidden(finance, ["RaiseEvent:SystemState:Finance"])
    assert is_hidden("RaiseEvent:TransactionAdded", ["RaiseEvent:Cashflow"])
    assert is_hidden("RaiseEvent:ObjectAdded:x", ["RaiseEvent:SpawnObject"])
    # New filters work too, and the old label form matches a new filter.
    assert is_hidden(finance, ["RaiseEvent:DirectoryData"])
    assert is_hidden("RaiseEvent:TransactionAdded", ["RaiseEvent:Cashflow"])
    assert is_hidden("RaiseEvent:SystemState:x", ["RaiseEvent:DirectoryData"])
    # Other events and partial names are not hidden.
    assert not is_hidden(finance, ["RaiseEvent:Dir"])
    assert not is_hidden("RaiseEvent:ObjectRemoved", ["RaiseEvent:ObjectAdded"])
    assert not is_hidden(finance, ["RaiseEvent:DirectoryData:Fin"])


def test_object_removed_typed() -> None:
    data = build(14, (8427316, 8))
    assert decode_args(data) == [8427316, 8]
    assert format_event(14, data) == [
        "Event 14 (ObjectRemoved):",
        "  ObjectId: uId 8427316, index 8",
    ]
    assert rpc_name(14) == "ObjectRemoved"


def test_unknown_code_falls_back_to_flat_values() -> None:
    data = encode_args([1, b"ab"])
    assert format_event(200, data) == ["Event 200:", "  1", "  'ab'"]
    # A known code whose argument count does not match also falls back.
    assert format_event(14, encode_args([1])) == [
        "Event 14 (ObjectRemoved):",
        "  1",
    ]


if __name__ == "__main__":
    test_payloads()
    test_legacy_names_still_filter()
    test_object_removed_typed()
    test_unknown_code_falls_back_to_flat_values()
    print("ok")
