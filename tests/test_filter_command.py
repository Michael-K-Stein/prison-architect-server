"""The runtime /filter and /hide commands: they edit the proxy's hidden list in place."""

from __future__ import annotations

from src.cli.console import CommandTable
from src.cli.filter_command import filter_commands
from src.protocol.events import is_hidden


def _table(hidden: list[str]) -> CommandTable:
    return CommandTable(filter_commands(hidden))


def test_no_args_lists_active_labels() -> None:
    hidden = ["RaiseEvent:DirectoryData:World"]
    assert _table(hidden).run("/filter") == "hiding RaiseEvent:DirectoryData:World"


def test_empty_list_says_nothing_hidden() -> None:
    assert "hiding nothing" in _table([]).run("/filter")


def test_hide_adds_labels_and_is_shared_with_the_proxy_list() -> None:
    hidden: list[str] = []
    table = _table(hidden)
    table.run("/filter hide TriggerPositionedSoundEvent")
    table.run("/hide RaiseEvent:DirectoryData:ObjectData")
    assert hidden == [
        "TriggerPositionedSoundEvent",
        "RaiseEvent:DirectoryData:ObjectData",
    ]


def test_hide_is_idempotent_across_spellings() -> None:
    hidden: list[str] = []
    table = _table(hidden)
    table.run("/hide RaiseEvent:SystemState")  # legacy name for DirectoryData
    table.run("/hide RaiseEvent:DirectoryData")
    assert hidden == ["RaiseEvent:DirectoryData"]


def test_canonical_spelling_is_what_is_hidden() -> None:
    hidden: list[str] = []
    _table(hidden).run("/hide RaiseEvent:SystemState:World")
    assert is_hidden("RaiseEvent:DirectoryData:World", hidden)
    assert is_hidden("RaiseEvent:DirectoryData:World:x", hidden)
    assert not is_hidden("RaiseEvent:DirectoryData:Other", hidden)


def test_show_removes_matching_labels_in_any_spelling() -> None:
    hidden = ["RaiseEvent:DirectoryData", "RaiseEvent:ObjectAdded"]
    out = _table(hidden).run("/filter show RaiseEvent:SystemState")
    assert hidden == ["RaiseEvent:ObjectAdded"]
    assert out == "hiding RaiseEvent:ObjectAdded"


def test_show_does_not_remove_parent_of_a_label() -> None:
    hidden = ["RaiseEvent:DirectoryData"]
    _table(hidden).run("/filter show RaiseEvent:DirectoryData:World")
    assert hidden == ["RaiseEvent:DirectoryData"]


def test_clear_removes_all() -> None:
    hidden = ["RaiseEvent:DirectoryData", "RaiseEvent:ObjectAdded"]
    out = _table(hidden).run("/filter clear")
    assert hidden == []
    assert "hiding nothing" in out


def test_reset_restores_the_cli_initial_set() -> None:
    hidden = ["RaiseEvent:DirectoryData"]
    table = _table(hidden)
    table.run("/filter hide RaiseEvent:ObjectAdded")
    table.run("/filter clear")
    table.run("/filter reset")
    assert hidden == ["RaiseEvent:DirectoryData"]


def test_reset_does_not_track_later_changes() -> None:
    hidden = ["RaiseEvent:DirectoryData"]
    table = _table(hidden)
    table.run("/filter clear")
    table.run("/filter hide RaiseEvent:ObjectAdded")
    table.run("/filter reset")
    assert hidden == ["RaiseEvent:DirectoryData"]


def test_bad_input_reports_usage() -> None:
    table = _table([])
    assert table.run("/filter hide").startswith("/filter")
    assert "expected one or more labels" in table.run("/filter hide")
    assert "expected one or more labels" in table.run("/hide")
    assert "unknown action 'nope'" in table.run("/filter nope X")
    assert "clear takes no labels" in table.run("/filter clear X")
    assert "reset takes no labels" in table.run("/filter reset X")


def test_help_lists_both_commands() -> None:
    text = _table([]).run("/help")
    assert "/filter [hide|show LABEL..." in text
    assert "/hide LABEL..." in text
