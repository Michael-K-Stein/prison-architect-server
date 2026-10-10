"""The console pane: expandable entries, scrolling, packet colouring."""

from __future__ import annotations

import logging
from collections import deque

from src.cli.console import CommandTable, complete
from src.cli.packet_view import packet_view, style_summary
from src.cli.pane import ConsolePane, Entry, PaneHandler, wrap_line


def _pane(n: int, height: int = 5) -> ConsolePane:
    pane = ConsolePane()
    pane.clear()
    pane.width, pane.height = 40, height
    for i in range(n):
        pane.say(f"line {i}")
    return pane


def text(view) -> list[str]:
    return ["".join(t for _, t in row) for _, row in view]


def test_view_follows_tail_and_pads() -> None:
    assert text(_pane(2).view())[-1].endswith("line 1")
    assert len(_pane(2).view()) == 5
    assert text(_pane(20).view())[-1].endswith("line 19")


def test_scrolling_and_clamp() -> None:
    pane = _pane(20)
    pane.scroll(3)
    assert text(pane.view())[-1].endswith("line 16")
    pane.jump_top()
    assert text(pane.view())[0].endswith("line 0")
    pane.scroll(-999)
    assert pane.up == 0


def test_scrolled_view_stays_put_when_lines_arrive() -> None:
    pane = _pane(20)
    pane.scroll(3)
    pane.view()
    pane.say("new")
    assert text(pane.view())[-1].endswith("line 16")


def test_expand_shows_detail_lazily() -> None:
    calls: list[int] = []
    entry = Entry([[("", "head")]], lambda: calls.append(1) or ["Key: value", "  more"])
    assert len(entry.rows(40)) == 1 and not calls
    entry.toggle()
    assert len(entry.rows(40)) == 3 and calls == [1]
    entry.toggle()
    assert len(entry.rows(40)) == 1


def test_toggle_all() -> None:
    pane = _pane(1)
    pane.entries.append(Entry([[("", "x")]], ["d"]))
    assert pane.toggle_all() is True
    assert pane.toggle_all() is False


def test_wrap_keeps_indent() -> None:
    out = wrap_line("  " + "a" * 50, 20)
    assert all(len(part) <= 20 for part in out) and out[1].startswith("    ")


def test_packet_entry_from_log_record() -> None:
    entries: deque = deque()
    handler = PaneHandler(entries)
    log = logging.getLogger("packet-test")
    log.addHandler(handler)
    try:
        view = packet_view(
            7, True, ["Event 118 TransactionAdded x +5", "  more"], ["d"]
        )
        log.warning("ignored", extra={"pane": view})
    finally:
        log.removeHandler(handler)
    (entry,) = entries
    assert entry.expandable and len(entry.head) == 2
    assert entry.head[0][1] == ("bold fg:ansicyan", "→ ")


def test_summary_colours() -> None:
    styles = {t: s for s, t in style_summary("Event 118 Foo k=-3 +5 'a'")}
    assert styles["Event 118 Foo"] == "bold fg:ansiyellow"
    assert styles["k"] == "fg:ansicyan"
    assert styles["-3"] == "fg:ansired" and styles["+5"] == "fg:ansigreen"


def test_tab_completion() -> None:
    table = CommandTable()
    assert complete(table, "/he") == ("/help ", [])
    assert complete(table, "/")[1] == ["/exit", "/help", "/quit"]
    assert complete(table, "zzz") == ("zzz", [])
