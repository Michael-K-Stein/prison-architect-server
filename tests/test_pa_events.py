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

from pa_events import (  # noqa: E402
    decode_args,
    decompress,
    format_event,
    is_hidden,
    log_lines,
    packet_label,
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


def main() -> None:
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
        "Event 9 (SystemState):",
        "  'Finance'",
        "  snapshot: 40 B zlib -> 31 B",
        "    Finance {tr.b=30075, v.6=30110}",
    ]

    lines = log_lines(packet(FINANCE))
    assert "    Finance {tr.b=30075, v.6=30110}" in lines[-1], lines
    assert not any(line.startswith("  Data/") for line in lines), lines

    label = packet_label(packet(FINANCE))
    assert label == "RaiseEvent:SystemState:Finance", label
    assert is_hidden(label, ["RaiseEvent:SystemState"])
    assert is_hidden(label, ["RaiseEvent:SystemState:Finance"])
    assert not is_hidden(label, ["RaiseEvent:SystemState:Fin", "RaiseEvent:Other"])

    assert format_event(118, decode_and_get(CASHFLOW)) == [
        "Event 118 (Cashflow):",
        "  finance_cost_cashflow: amount 35 (unknown: 0, 0)",
    ]
    assert packet_label(packet(CASHFLOW)) == "RaiseEvent:Cashflow"

    lines = log_lines(packet(COLOUR))
    assert lines[-1] == "  Actor 1: colour = #8479f4 (alpha ff) (broadcast)", lines
    assert not any("Broadcast" in line for line in lines), lines
    lines = log_lines(packet(PING))
    assert lines[-1] == "  Actor 1: ping = 335 ms (broadcast)", lines

    # Anything that doesn't parse is shown raw rather than raising.
    assert "unparsed" in format_event(9, b"\xff")[0]
    print("ok")


if __name__ == "__main__":
    main()
