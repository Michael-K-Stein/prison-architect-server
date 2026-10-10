"""Typed RPC arguments, on payloads from captures/run1..4.sqlite."""

import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.protocol.rpc import (
    COMPOSITE_ARITY,
    ParsedRpc,
    RpcShapeError,
    build,
    encode_args,
    format_rpc,
    lookup,
    parse,
    rpc_name,
)
from src.protocol.rpc_table import RPCS
from src.protocol.snapshot import decode_args

# Event 13 (ObjectAdded) from run4: uId 8427316, index 17, type 139.
OBJECT_ADDED = bytes.fromhex("043497800211028b")
# Event 118 (TransactionAdded) from run4: -5280, foundations, 0, 0.
TRANSACTION = bytes.fromhex(
    "0ba014121866696e616e63655f636f73745f666f756e646174696f6e730000"
)
# Event 9 (DirectoryData) from run2, the shortest one: name, zlib blob.
DIRECTORY = bytes.fromhex(
    "120a4f626a656374446174611219789cb3e1f24fca4a4d2e71492c496460b00300247d04560f02"
)


@pytest.mark.parametrize("data", [OBJECT_ADDED, TRANSACTION, DIRECTORY])
def test_encode_round_trips_captured_data(data: bytes) -> None:
    assert encode_args(decode_args(data)) == data


def test_encode_numbers_use_fewest_bytes() -> None:
    assert encode_args([0]) == b"\x00"
    assert encode_args([139]) == b"\x02\x8b"
    assert encode_args([-5280]) == b"\x0b\xa0\x14"
    assert encode_args([0xFFFFFF]) == b"\x04\xff\xff\xff"
    assert decode_args(encode_args([-5280, 0xFFFFFF, 0])) == [-5280, 0xFFFFFF, 0]


def test_encode_rejects_numbers_over_three_bytes() -> None:
    with pytest.raises(ValueError):
        encode_args([0x1000000])


def test_encode_refuses_bool() -> None:
    # A bool is one raw byte, not a tagged value; encode_args would emit 02 01.
    with pytest.raises(TypeError):
        encode_args([True])


def test_encode_text_and_float() -> None:
    assert encode_args(["abc"]) == b"\x12\x03abc"
    assert encode_args([1.5]) == b"\x1a" + struct.pack("<f", 1.5)
    assert decode_args(encode_args([1.5, "abc", b"xy"])) == [1.5, b"abc", b"xy"]


def test_build_matches_captured_transaction() -> None:
    # The table declares the fourth argument a string, but every captured
    # payload carries int 0 there, so the capture is built with 0.
    assert build(118, -5280, b"finance_cost_foundations", 0, 0) == TRANSACTION


def test_build_object_id_composite() -> None:
    assert build(13, (8427316, 17), 139) == OBJECT_ADDED


def test_parse_object_added() -> None:
    parsed = parse(13, OBJECT_ADDED)
    assert isinstance(parsed, ParsedRpc)
    assert parsed.rpc.name == "ObjectAdded"
    assert parsed.args == [("ObjectId", (8427316, 17)), ("int", 139)]
    assert format_rpc(parsed) == [
        "RPC 13 ObjectAdded:",
        "  ObjectId: uId 8427316, index 17",
        "  int: 139",
    ]


def test_parse_transaction_added() -> None:
    parsed = parse(118, TRANSACTION)
    assert parsed.args == [
        ("int", -5280),
        ("string", b"finance_cost_foundations"),
        ("signed char", 0),
        ("string", 0),
    ]
    assert format_rpc(parsed) == [
        "RPC 118 TransactionAdded:",
        "  int: -5280",
        "  string: 'finance_cost_foundations'",
        "  signed char: 0",
        "  string: ''",
    ]


def test_format_shows_memory_block_as_zlib_size() -> None:
    assert format_rpc(parse(9, DIRECTORY)) == [
        "RPC 9 DirectoryData:",
        "  string: 'ObjectData'",
        "  MemoryBlock: <25 bytes zlib>",
    ]


def test_lookup_and_names() -> None:
    rpc = lookup(9)
    assert rpc is not None
    assert rpc.name == "DirectoryData"
    assert rpc.types == ("string", "MemoryBlock")
    assert lookup(999) is None
    assert rpc_name(13) == "ObjectAdded"
    assert rpc_name(999) == "999"


def test_table_has_144_entries() -> None:
    assert len(RPCS) == 144
    assert COMPOSITE_ARITY["ObjectId"] == 2


def test_unknown_code_raises() -> None:
    with pytest.raises(RpcShapeError):
        parse(999, OBJECT_ADDED)
    with pytest.raises(RpcShapeError):
        build(999)


def test_wrong_value_count_raises() -> None:
    with pytest.raises(RpcShapeError):
        parse(13, encode_args([1, 2]))
    with pytest.raises(RpcShapeError):
        parse(13, encode_args([1, 2, 3, 4]))


def test_undecodable_bytes_raise_shape_error() -> None:
    with pytest.raises(RpcShapeError):
        parse(13, b"\x30")


def test_build_wrong_count_or_shape_raises() -> None:
    with pytest.raises(RpcShapeError):
        build(13, (1, 2))
    with pytest.raises(RpcShapeError):
        build(13, 5, 139)
    with pytest.raises(RpcShapeError):
        build(13, (1, 2, 3), 139)
    with pytest.raises(RpcShapeError):
        build(118, -5280, b"x")


# Code 65 UseCellQualityChange is (bool,); code 58 TransferAllowedChange is
# (bool, int). A bool is one raw byte: 00 false, 01 true.


def test_build_bool_is_one_raw_byte() -> None:
    assert build(65, True) == b"\x01"
    assert build(65, False) == b"\x00"
    assert build(65, 1) == b"\x01"
    assert build(65, 0) == b"\x00"


def test_build_bool_then_int() -> None:
    assert build(58, True, 5) == b"\x01\x02\x05"
    assert build(58, False, -5280) == b"\x00\x0b\xa0\x14"


@pytest.mark.parametrize("bad", [2, -1, 1.0, "1", None])
def test_build_rejects_bad_bool(bad: object) -> None:
    with pytest.raises(RpcShapeError):
        build(65, bad)


def test_build_rejects_bool_for_int_slot() -> None:
    with pytest.raises(RpcShapeError):
        build(37, True)


def test_parse_bool_only() -> None:
    assert parse(65, b"\x01").args == [("bool", True)]
    assert parse(65, b"\x00").args == [("bool", False)]
    assert format_rpc(parse(65, b"\x01")) == [
        "RPC 65 UseCellQualityChange:",
        "  bool: True",
    ]


def test_parse_bool_then_int() -> None:
    parsed = parse(58, b"\x01\x02\x05")
    assert parsed.args == [("bool", True), ("int", 5)]
    assert format_rpc(parsed) == [
        "RPC 58 TransferAllowedChange:",
        "  bool: True",
        "  int: 5",
    ]


@pytest.mark.parametrize(
    ("code", "data"),
    [(65, b"\x01"), (65, b"\x00"), (58, b"\x01\x02\x05"), (58, b"\x00\x0b\xa0\x14")],
)
def test_bool_round_trips(code: int, data: bytes) -> None:
    parsed = parse(code, data)
    assert build(code, *(value for _, value in parsed.args)) == data


def test_parse_rejects_bool_byte_other_than_0_or_1() -> None:
    with pytest.raises(RpcShapeError):
        parse(65, b"\x02")


def test_parse_rejects_tagged_one_in_bool_slot() -> None:
    # 02 01 is what encode_args(True) would have written: a tagged 1, which
    # the bool slot reads as an invalid byte 0x02.
    with pytest.raises(RpcShapeError):
        parse(58, b"\x02\x01\x02\x05")


def test_parse_bool_truncated_or_trailing_raises() -> None:
    with pytest.raises(RpcShapeError):
        parse(58, b"\x01")
    with pytest.raises(RpcShapeError):
        parse(65, b"\x01\x00")
