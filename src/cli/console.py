"""A fixed input line at the bottom of a running server's terminal.

Log lines print above it (``patch_stdout``); typed lines go to a command table.
Without a terminal (piped stdin, a service) there is no input line and the
process just waits for Ctrl+C, as before.
"""

from __future__ import annotations

import logging
import shlex
import shutil
import sys
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from src.cli.frame import BEGIN, DIM, ECHO, EDGE, RULE, banner

CommandFn = Callable[[list[str]], str]
"""Takes the arguments after the command name, returns a line to print."""


class Quit(Exception):
    """Raised by a command to end the console loop."""


@dataclass(frozen=True)
class Command:
    """One entry of the command table."""

    usage: str
    summary: str
    run: CommandFn


def loglevel_command() -> Command:
    """``loglevel [LEVEL]``: show or change the logging level while running."""
    from src.logs import LOG_LEVELS, current_log_level, set_log_level

    def run(args: list[str]) -> str:
        if not args:
            return f"log level {current_log_level()} (choose: {', '.join(LOG_LEVELS)})"
        if len(args) != 1:
            raise ValueError("expected one level")
        return f"log level {set_log_level(args[0])}"

    return Command("loglevel [LEVEL]", "show or change the log level", run)


class CommandTable:
    """Parses a typed line and runs the matching command. Has no I/O of its own."""

    def __init__(self, commands: dict[str, Command] | None = None) -> None:
        self.commands: dict[str, Command] = {
            "help": Command("help", "list the commands", self._help),
            "quit": Command("quit", "stop the server", self._quit),
            "exit": Command("exit", "same as quit", self._quit),
        }
        self.commands.update(commands or {})

    def run(self, line: str) -> str:
        """Run one typed line and return what to print ("" for a blank line)."""
        try:
            words = shlex.split(line)
        except ValueError as exc:
            return f"could not parse: {exc}"
        if not words:
            return ""
        command = self.commands.get(words[0].lower())
        if command is None:
            return f"unknown command {words[0]!r}; try help"
        try:
            return command.run(words[1:])
        except (ValueError, OSError) as exc:
            return f"{command.usage}: {exc}"

    def _help(self, _args: list[str]) -> str:
        return "\n".join(f"  {c.usage:<24} {c.summary}" for c in self.commands.values())

    def _quit(self, _args: list[str]) -> str:
        raise Quit

    def bottom_hint(self) -> str:
        """The one-line summary shown above the input line."""
        return "type a command, help for the list, quit to stop"


PANE_LINES = 500
"""Lines kept in the console's message pane."""


LEVEL_STYLES = {
    logging.DEBUG: DIM,
    logging.INFO: "fg:ansigreen",
    logging.WARNING: "fg:ansiyellow",
    logging.ERROR: "fg:ansired bold",
    logging.CRITICAL: "fg:ansired bold",
}
"""Pane colour for each log level, matching the terminal logger's look."""


class PaneHandler(logging.Handler):
    """Sends log records into the console's message pane instead of stdout."""

    def __init__(self, lines: deque[list[tuple[str, str]]]) -> None:
        super().__init__()
        self.lines = lines

    def emit(self, record: logging.LogRecord) -> None:
        when = time.strftime("%H:%M:%S", time.localtime(record.created))
        level = LEVEL_STYLES.get(record.levelno, "")
        row = [
            (DIM, f"{when} "),
            (level, f"{record.levelname:<8} "),
            ("", record.getMessage()),
        ]
        if record.exc_info:
            row.append(
                (
                    "fg:ansired",
                    "\n" + logging.Formatter().formatException(record.exc_info),
                )
            )
        self.lines.append(row)


class ConsolePane:
    """The message pane: log records and command output, shown by run_console.

    Create it right after logging is set up, so the startup lines land in it too.
    """

    def __init__(self, title: str = "Prison Architect") -> None:
        self.lines: deque[list[tuple[str, str]]] = deque(maxlen=PANE_LINES)
        self.interactive = sys.stdin.isatty()
        self._saved: list[logging.Handler] | None = None
        width = min(shutil.get_terminal_size().columns, 60)
        for text in banner(title, width):
            self.lines.append([("bold fg:ansicyan", text)])
        self.lines.append([("", "")])

    def install_logging(self) -> None:
        """Route log records here. Without a terminal nothing is shown, so nothing changes."""
        if not self.interactive or self._saved is not None:
            return
        root = logging.getLogger()
        self._saved = root.handlers[:]
        root.handlers = [PaneHandler(self.lines)]

    def restore_logging(self) -> None:
        if self._saved is not None:
            logging.getLogger().handlers = self._saved
            self._saved = None


def run_console(commands: CommandTable, pane: ConsolePane | None = None) -> None:
    """Full-screen console: messages scroll in the pane, the input box stays at the bottom."""
    if not sys.stdin.isatty():
        _wait_for_ctrl_c()
        return
    pane = pane or ConsolePane()
    pane.install_logging()
    try:
        _run_app(commands, pane)
    finally:
        pane.restore_logging()


def _run_app(commands: CommandTable, pane: ConsolePane) -> None:
    from prompt_toolkit import Application
    from prompt_toolkit.buffer import Buffer
    from prompt_toolkit.document import Document
    from prompt_toolkit.filters import Condition
    from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
    from prompt_toolkit.layout import HSplit, Layout, VSplit, Window
    from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
    from prompt_toolkit.layout.processors import AfterInput, ConditionalProcessor
    from prompt_toolkit.styles import Style

    log = pane.lines
    hint = commands.bottom_hint()
    fresh = [True]  # the hint is the placeholder until the first command
    history: list[str] = []  # commands entered, oldest first
    recall = [0]  # index into history; len(history) means "the new line"

    def on_accept(buf: Buffer) -> None:
        line = buf.text
        if line:
            history.append(line)
        recall[0] = len(history)
        buf.reset()
        fresh[0] = False
        log.append([(ECHO, f"{BEGIN}{line}")])
        try:
            out = commands.run(line)
        except Quit:
            app.exit()
            return
        log.extend([("", text)] for text in out.splitlines())

    buffer = Buffer(multiline=False, accept_handler=on_accept)
    keys = KeyBindings()

    @keys.add("enter")
    def _(event: KeyPressEvent) -> None:
        buffer.validate_and_handle()

    def show_recalled(index: int) -> None:
        recall[0] = index
        text = history[index] if index < len(history) else ""
        buffer.document = Document(text, len(text))

    # Up/down step through the commands entered so far; down past the newest clears.
    @keys.add("up", eager=True)
    def _(event: KeyPressEvent) -> None:
        if recall[0] > 0:
            show_recalled(recall[0] - 1)

    @keys.add("down", eager=True)
    def _(event: KeyPressEvent) -> None:
        if recall[0] < len(history):
            show_recalled(recall[0] + 1)

    @keys.add("c-c")
    @keys.add("c-d")
    def _(event: KeyPressEvent) -> None:
        event.app.exit()

    height = [0]  # the pane's visible rows, learned from the last render

    def scroll(window: Window) -> int:
        height[0] = window.render_info.window_height if window.render_info else 0
        return max(0, len(log) - height[0])

    def lines() -> list[tuple[str, str]]:
        # A short pane is padded at the top, so the newest line sits just above the box.
        pad = [("", "\n")] * max(0, height[0] - len(log))
        return pad + [frag for line in log for frag in (*line, ("", "\n"))]

    messages = Window(
        FormattedTextControl(lines), wrap_lines=False, get_vertical_scroll=scroll
    )
    entry = VSplit(
        [
            Window(
                BufferControl(
                    buffer,
                    input_processors=[
                        ConditionalProcessor(
                            AfterInput(lambda: [(DIM, hint)]),
                            filter=Condition(lambda: fresh[0] and not buffer.text),
                        )
                    ],
                ),
                height=1,
                get_line_prefix=lambda *_: [("bold", BEGIN)],
            ),
            Window(width=1, char=EDGE, style=DIM),
        ]
    )
    rule = Window(height=1, char=RULE, style=DIM)
    app: Application[None] = Application(
        layout=Layout(HSplit([messages, rule, entry, rule]), focused_element=buffer),
        key_bindings=keys,
        style=Style.from_dict({"echo": ECHO}),
        full_screen=True,
        mouse_support=False,
        refresh_interval=0.25,
    )
    app.run()


def _wait_for_ctrl_c() -> None:
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return
