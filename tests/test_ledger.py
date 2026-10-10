"""Ledger entries (118 / 119): parsing, key classes and grouping, on captured bytes."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.protocol.ledger import (
    CASHFLOW,
    CONSTRUCTION,
    GRANT,
    OTHER,
    PRISONERS,
    RESEARCH,
    SALES,
    UNKNOWN,
    Entry,
    classify,
    group_by_category,
    parse_entry,
)

# Event 118 from captures/bot-goal/todos-10-10-2026-17-13.sqlite (packet 2951):
# [-62, 'finance_cost_cashflow', 0, 0].
CASHFLOW_DATA = (
    bytes.fromhex("0a 3e 12 15") + b"finance_cost_cashflow" + bytes.fromhex("00 00")
)
# Event 118 from the same capture: [-30, 'object_Light', 0, 0].
LIGHT_DATA = bytes.fromhex("0a 1e 12 0c") + b"object_Light" + bytes.fromhex("00 00")


def test_parse_cashflow_entry_from_capture():
    entry = parse_entry(118, CASHFLOW_DATA)
    assert entry == Entry(
        code=118,
        amount=-62,
        key="finance_cost_cashflow",
        flag=0,
        text="",
    )
    assert entry.category == CASHFLOW


def test_parse_object_entry_and_its_category():
    entry = parse_entry(118, LIGHT_DATA)
    assert (entry.amount, entry.key) == (-30, "object_Light")
    assert entry.category == CONSTRUCTION
    assert "Light" in entry.description


def test_119_has_the_same_shape():
    entry = parse_entry(119, LIGHT_DATA)
    assert entry.code == 119
    assert entry.amount == -30


def test_non_ledger_code_is_rejected():
    with pytest.raises(ValueError, match="not a ledger entry"):
        parse_entry(9, LIGHT_DATA)


def test_wrong_argument_count_is_rejected():
    # Only the first three arguments: [-30, 'object_Light', 0].
    short = bytes.fromhex("0a 1e 12 0c") + b"object_Light" + bytes.fromhex("00")
    with pytest.raises(ValueError, match="expected 4"):
        parse_entry(118, short)


def test_key_must_be_text():
    # Third argument is text instead of the key: [-30, 0, 0, 0].
    bad = bytes.fromhex("0a 1e 00 00 00")
    with pytest.raises(TypeError, match="key is not a string"):
        parse_entry(118, bad)


def test_text_argument_as_bytes_is_kept():
    # [-5, 'object_Ingredients', 0, 'x'] built by hand (tags as in the captures):
    # the fourth value is real text, not the game's int 0.
    data = (
        bytes.fromhex("0a 05 12 12")
        + b"object_Ingredients"
        + bytes.fromhex("00 12 01")
        + b"x"
    )
    entry = parse_entry(118, data)
    assert entry.text == "x"


@pytest.mark.parametrize(
    ("key", "category"),
    [
        ("finance_cost_cashflow", CASHFLOW),
        ("finance_cost_foundations", CONSTRUCTION),
        ("finance_cost_prisonerintake", PRISONERS),
        ("finance_cost_grantadvance", GRANT),
        ("finance_cost_grantcompletion", GRANT),
        ("finance_cost_grantfine", GRANT),
        ("finance_cost_prisonsale", SALES),
        ("parole_fine", PRISONERS),
        ("reform_reward", PRISONERS),
        ("d11_powerexportmeter_sell_desc", SALES),
        ("object_Battery", CONSTRUCTION),
        ("object_wire", CONSTRUCTION),
        ("research_Legal", RESEARCH),
        ("finance_cost_somethingnew", OTHER),
        ("MONEY", UNKNOWN),
        ("never_seen_key", UNKNOWN),
    ],
)
def test_classify_keys(key, category):
    assert classify(key)[0] == category


def test_classify_describes_object_and_research_names():
    assert classify("object_PowerExportMeter")[1].startswith("PowerExportMeter:")
    assert classify("research_Cctv")[1].startswith("Cctv:")


def test_injected_test_keys_say_so():
    assert "injected" in classify('"Money"')[1]


def test_group_by_category_keeps_order_and_entries():
    entries = [
        Entry(118, -30, "object_Light", 0, ""),
        Entry(118, -62, "finance_cost_cashflow", 0, ""),
        Entry(118, -5280, "finance_cost_foundations", 0, ""),
        Entry(118, 20000, "finance_cost_grantadvance", 0, ""),
        Entry(118, -100, "object_Door", 0, ""),
    ]
    groups = group_by_category(entries)
    assert list(groups) == [CASHFLOW, CONSTRUCTION, GRANT]
    assert [e.key for e in groups[CONSTRUCTION]] == [
        "object_Light",
        "finance_cost_foundations",
        "object_Door",
    ]
    assert sum(e.amount for e in entries) == sum(
        e.amount for group in groups.values() for e in group
    )


def test_group_by_category_empty():
    assert group_by_category([]) == {}
