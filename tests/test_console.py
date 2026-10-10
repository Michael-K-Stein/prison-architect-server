"""The server's bottom command line: parsing and dispatch, and switching captures."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.capture.recorder import SwitchableRecorder
from src.cli.console import Command, CommandTable, Quit


def _table(seen: list[list[str]]) -> CommandTable:
    def echo(args: list[str]) -> str:
        seen.append(args)
        return "echoed " + " ".join(args)

    return CommandTable({"echo": Command("echo WORDS", "repeat", echo)})


def test_blank_line_prints_nothing() -> None:
    assert _table([]).run("   ") == ""


def test_command_gets_quoted_arguments() -> None:
    seen: list[list[str]] = []
    out = _table(seen).run('echo "a b" c')
    assert seen == [["a b", "c"]]
    assert out == "echoed a b c"


def test_unknown_command_points_at_help() -> None:
    assert _table([]).run("nope") == "unknown command 'nope'; try help"


def test_help_lists_every_command() -> None:
    text = _table([]).run("help")
    for name in ("help", "quit", "echo WORDS"):
        assert name in text


def test_quit_raises() -> None:
    with pytest.raises(Quit):
        _table([]).run("quit")


def test_bad_arguments_are_reported_not_raised() -> None:
    def strict(args: list[str]) -> str:
        raise ValueError("expected one path")

    table = CommandTable({"strict": Command("strict PATH", "x", strict)})
    assert table.run("strict") == "strict PATH: expected one path"
    assert table.run('strict "unclosed').startswith("could not parse")


def test_switchable_recorder_idle_until_opened(tmp_path: Path) -> None:
    rec = SwitchableRecorder()
    assert rec.path is None
    assert rec.record(None, None, None) is None  # nothing open: nothing recorded
    rec.close()  # closing when idle is harmless


def test_switchable_recorder_moves_to_new_file(tmp_path: Path) -> None:
    first = tmp_path / "a" / "one.sqlite"
    second = tmp_path / "two.sqlite"
    with SwitchableRecorder(first) as rec:
        assert rec.path == first
        assert first.exists()
        rec.open(second)
        assert rec.path == second
        assert second.exists()
    assert rec.path is None
    for path in (first, second):
        db = sqlite3.connect(path)
        try:
            (fmt,) = db.execute("SELECT value FROM meta WHERE key='format'").fetchone()
        finally:
            db.close()
        assert fmt


def test_failed_open_keeps_the_current_file(tmp_path: Path) -> None:
    good = tmp_path / "good.sqlite"
    rec = SwitchableRecorder(good)
    blocked = tmp_path / "not-a-dir"
    blocked.write_text("file in the way", encoding="utf-8")
    with pytest.raises(OSError):
        rec.open(blocked / "x.sqlite")
    assert rec.path == good
    rec.close()
