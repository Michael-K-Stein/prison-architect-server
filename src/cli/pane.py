"""The console's message pane: entries that can be expanded, scrolled and cleared.

No terminal code here (``console.py`` draws it), so it is easy to test. An
:class:`Entry` is a few always-visible *head* rows plus optional *detail* lines
that appear when it is expanded (click, or Ctrl+O for all).
"""

from __future__ import annotations

import logging
import shutil
import sys
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field

from src.cli.frame import BEGIN, DIM, ECHO, banner

Frag = tuple[str, str]
"""A ``(prompt_toolkit style, text)`` piece of a row."""

Row = list[Frag]

PANE_ENTRIES = 2000
"""Entries kept in the pane; older ones drop off the top."""

TIME_WIDTH = 9
"""Width of the ``HH:MM:SS `` column in front of each entry."""

MARK_OPEN, MARK_CLOSED, MARK_NONE = "▾ ", "▸ ", "  "
DETAIL_INDENT = "    "

LEVEL_STYLES = {
    logging.DEBUG: DIM,
    logging.INFO: "fg:ansigreen",
    logging.WARNING: "fg:ansiyellow",
    logging.ERROR: "fg:ansired bold",
    logging.CRITICAL: "fg:ansired bold",
}
"""Pane colour for each log level, matching the terminal logger's look."""

DetailSource = Callable[[], list[str]] | list[str]


@dataclass
class PacketView:
    """Attach to a log record (``extra={"pane": view}``) to show it as an entry."""

    head: list[Row]
    detail: DetailSource | None = None
    expanded: bool = False


@dataclass
class Entry:
    """One pane item: ``head`` rows always, ``detail`` lines when ``expanded``."""

    head: list[Row]
    detail: DetailSource | None = None
    expanded: bool = False
    _lines: list[str] | None = field(default=None, repr=False)
    _cache: tuple[int, bool, list[Row]] | None = field(default=None, repr=False)

    @property
    def expandable(self) -> bool:
        return self.detail is not None

    def toggle(self) -> None:
        if self.expandable:
            self.expanded = not self.expanded

    def detail_lines(self) -> list[str]:
        """The detail text, rendered on first use (big snapshots are slow)."""
        if self._lines is None:
            try:
                source = self.detail() if callable(self.detail) else self.detail
                self._lines = list(source or [])
            except Exception as exc:  # a broken renderer must not kill the UI
                self._lines = [f"(could not render: {exc})"]
        return self._lines

    def rows(self, width: int) -> list[Row]:
        """Every row this entry occupies at ``width`` columns (cached)."""
        if self._cache and self._cache[:2] == (width, self.expanded):
            return self._cache[2]
        mark = MARK_NONE
        if self.expandable:
            mark = MARK_OPEN if self.expanded else MARK_CLOSED
        rows = [
            clip([(DIM, mark if i == 0 else MARK_NONE), *row], width)
            for i, row in enumerate(self.head)
        ]
        if self.expanded:
            for line in self.detail_lines():
                for part in wrap_line(line, width - len(DETAIL_INDENT)):
                    rows.append([(DIM, DETAIL_INDENT), *style_detail(part)])
        self._cache = (width, self.expanded, rows)
        return rows


def clip(row: Row, width: int) -> Row:
    """``row`` cut to ``width`` columns, ending in ``…`` when something was lost."""
    if width <= 0 or sum(len(t) for _, t in row) <= width:
        return row
    out: Row = []
    room = width - 1
    for style, text in row:
        if room <= 0:
            break
        out.append((style, text[:room]))
        room -= len(text)
    out.append((DIM, "…"))
    return out


def wrap_line(line: str, width: int) -> list[str]:
    """Hard-wrap ``line`` at ``width``; continuations keep (and extend) its indent."""
    if width <= 8 or len(line) <= width:
        return [line]
    pad = " " * min(len(line) - len(line.lstrip()) + 2, width // 2)
    out, rest = [line[:width]], line[width:]
    step = width - len(pad)
    while rest:
        out.append(pad + rest[:step])
        rest = rest[step:]
    return out


def style_detail(text: str) -> Row:
    """Colour the ``Name:`` at the start of a detail line."""
    body = text.lstrip()
    name, colon, rest = body.partition(":")
    if colon and name and " " not in name:
        pad = text[: len(text) - len(body)]
        return [("", pad), ("fg:ansicyan", name + colon), ("", rest)]
    return [("", text)]


def message_head(record: logging.LogRecord) -> list[Row]:
    """Rows for an ordinary log record: time, coloured level, message lines."""
    when = time.strftime("%H:%M:%S", time.localtime(record.created))
    level = LEVEL_STYLES.get(record.levelno, "")
    first, *more = record.getMessage().split("\n") or [""]
    rows: list[Row] = [
        [(DIM, f"{when} "), (level, f"{record.levelname:<8} "), ("", first)]
    ]
    pad = " " * (TIME_WIDTH + 9)
    rows.extend([("", pad + line)] for line in more)
    return rows


class PaneHandler(logging.Handler):
    """Sends log records into the console's message pane instead of stdout."""

    def __init__(self, entries: deque[Entry]) -> None:
        super().__init__()
        self.entries = entries

    def emit(self, record: logging.LogRecord) -> None:
        view: PacketView | None = getattr(record, "pane", None)
        if view is not None:
            when = time.strftime("%H:%M:%S ", time.localtime(record.created))
            head = [list(row) for row in view.head]
            head[0] = [(DIM, when), *head[0]]
            for row in head[1:]:
                row.insert(0, ("", " " * TIME_WIDTH))
            entry = Entry(head, view.detail, view.expanded)
        else:
            detail = None
            if record.exc_info:
                text = logging.Formatter().formatException(record.exc_info)
                detail = text.splitlines()
            entry = Entry(message_head(record), detail, expanded=detail is not None)
        self.entries.append(entry)


class ConsolePane:
    """Entries plus the scroll position; shown by ``run_console``.

    Create it right after logging is set up, so the startup lines land in it too.
    """

    def __init__(self, title: str = "Prison Architect") -> None:
        self.entries: deque[Entry] = deque(maxlen=PANE_ENTRIES)
        self.interactive = sys.stdin.isatty()
        self.up = 0
        """Rows scrolled up from the newest; 0 follows the tail."""
        self.attached: Callable[[], tuple[str, bool]] | None = None
        """Status-bar text for the attached game, and whether one is attached."""
        size = shutil.get_terminal_size()
        self.width, self.height = size.columns, max(size.lines - 4, 1)
        self._saved: list[logging.Handler] | None = None
        self._last_total = 0
        self._was_up = False
        for text in banner(title, min(size.columns, 60)):
            self.say(text, "bold fg:ansicyan")
        self.say("")

    # -- adding --------------------------------------------------------
    def say(self, text: str, style: str = "") -> None:
        self.entries.append(Entry([[(style, text)]]))

    def echo(self, line: str) -> None:
        self.entries.append(Entry([[(ECHO, f"{BEGIN}{line}")]]))

    def clear(self) -> None:
        self.entries.clear()
        self.up = 0

    # -- logging -------------------------------------------------------
    def install_logging(self) -> None:
        """Route log records here. Without a terminal nothing is shown, so nothing changes."""
        if not self.interactive or self._saved is not None:
            return
        root = logging.getLogger()
        self._saved = root.handlers[:]
        root.handlers = [PaneHandler(self.entries)]

    def restore_logging(self) -> None:
        if self._saved is not None:
            logging.getLogger().handlers = self._saved
            self._saved = None

    # -- expanding -----------------------------------------------------
    def toggle_all(self) -> bool:
        """Expand every expandable entry, or collapse all if all are open."""
        items = [e for e in list(self.entries) if e.expandable]
        opening = any(not e.expanded for e in items)
        for entry in items:
            entry.expanded = opening
        return opening

    # -- scrolling and viewing ----------------------------------------
    def scroll(self, rows: int) -> None:
        """Move the view ``rows`` up (negative: down); 0 rows below follows the tail."""
        self.up = max(0, self.up + rows)

    def follow(self) -> None:
        self.up = 0

    def jump_top(self) -> None:
        self.up = 10**9  # clamped by the next view()

    def view(self) -> list[tuple[Entry | None, Row]]:
        """Exactly ``height`` rows ``(entry, row)``, padded at the top when short."""
        entries = list(self.entries)
        sizes = [len(e.rows(self.width)) for e in entries]
        total = sum(sizes)
        if self._was_up and self.up and total > self._last_total:
            self.up += total - self._last_total  # keep what's on screen in place
        self._last_total = total
        self.up = min(self.up, max(0, total - self.height))
        self._was_up = self.up > 0
        start = max(0, total - self.height - self.up)
        out: list[tuple[Entry | None, Row]] = []
        seen = 0
        for entry, size in zip(entries, sizes):
            if seen + size > start and len(out) < self.height:
                rows = entry.rows(self.width)
                out.extend((entry, row) for row in rows[max(0, start - seen) :])
            seen += size
            if len(out) >= self.height:
                break
        out = out[: self.height]
        return [(None, [])] * (self.height - len(out)) + out

    def status(self) -> str:
        """Text for the bar above the input."""
        if self.up:
            return f"↑ scrolled up {self.up} rows — PgDn / Ctrl+End to follow"
        return f"{len(self.entries)} entries — click one to expand"
