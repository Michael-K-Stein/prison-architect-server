from __future__ import annotations

from src.bot import catalog
from src.bot.state import GameState
from src.protocol.grants import GRANTS, canonical


def test_canonical_grant_names():
    assert canonical("greenmachine") == "Grant_GreenMachine"
    assert canonical("GreenMachine") == "Grant_GreenMachine"
    assert canonical("Grant_GreenMachine") == "Grant_GreenMachine"
    assert canonical("bootstraps") == "Grant_bootstraps"
    assert canonical("administration") == "Grant_Administration"
    assert canonical("target_PassReform") == "target_PassReform"
    assert canonical("SomethingNew") == "Grant_SomethingNew"  # the host decides


def test_table_has_the_base_and_dlc_grants():
    assert GRANTS["Grant_bootstraps"]["start"] == 20000
    assert GRANTS["Grant_bootstraps"]["completion"] == 10000
    assert ("Completed", "Grant_bootstraps", 0) in GRANTS["Grant_FirstCellBlock"][
        "requires"
    ]
    assert "Grant_GreenMachine" in GRANTS


def test_accept_grant_takes_any_spelling():
    action = catalog.find("AcceptGrant")
    state = GameState()
    for typed in ("greenMachine", "Grant_GreenMachine"):
        assert catalog.parse_args(action, [typed], state) == ["Grant_GreenMachine"]
    labels = [c.label for c in catalog.choices(action.args[0], state)]
    assert "Grant_GreenMachine: Green Machine" in labels
