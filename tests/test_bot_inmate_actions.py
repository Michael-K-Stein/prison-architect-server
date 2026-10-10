"""Inmate panel commands: the RPCs they build match the capture."""

from __future__ import annotations

import pytest

from src.bot import catalog, inmate_actions
from src.protocol import rpc


def test_request_maps_commands_to_rpcs() -> None:
    request = inmate_actions.request
    assert request("security", "supermax") == ("ApplyPrisonerCategory", ["5"])
    assert request("security", "Medium") == ("ApplyPrisonerCategory", ["2"])
    assert request("search") == ("PerformAction", ["7"])
    assert request("search-cell") == ("PerformAction", ["8"])
    assert request("search-block") == ("PerformAction", ["9"])
    assert request("lockdown", "6") == ("ApplyPunishment", ["1", "360"])
    assert request("solitary", "6") == ("ApplyPunishment", ["2", "360"])
    assert request("solitary", "permanent") == ("ApplyPunishment", ["2", "500000"])
    assert request("clear-punishments")[0] == "ClearAllPunishments"
    assert inmate_actions.request("assign-guard")[0] == "AssignGuardToPrisoner"
    assert inmate_actions.request("unassign-guard")[0] == "UnassignGuardFromPrisoner"


def test_request_rejects_bad_input() -> None:
    with pytest.raises(ValueError):
        inmate_actions.request("security")
    with pytest.raises(ValueError):
        inmate_actions.request("security", "nope")
    with pytest.raises(ValueError):
        inmate_actions.request("dance")


def test_builds_the_captured_bytes() -> None:
    # captures/inmate-actions.sqlite packet 19031: PerformAction(object, 9)
    action = catalog.find("PerformAction")
    values = catalog.parse_args(action, ["4574,3070", "9"])
    assert rpc.build(action.code, *values).endswith(b"\x02\t")
