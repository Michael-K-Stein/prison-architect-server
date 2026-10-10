"""A full-screen console for a running server: scrollable, expandable message pane
above a fixed input box.

Log lines and command output go into a :class:`~src.cli.pane.ConsolePane`;
typed lines go to a command table. Without a terminal (piped stdin, a service)
there is no screen and the process just waits for Ctrl+C, as before.

Keys: mouse wheel / PgUp / PgDn scroll, Ctrl+End follows the newest line, a click
on an event (or Ctrl+O for all) expands it, Ctrl+L clears, Tab completes a
command, Up/Down and the grey suggestion use the saved history.
"""

from __future__ import annotations

import os
import shlex
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from src.cli.frame import BEGIN, DIM, ECHO, EDGE, RULE
from src.cli.pane import ConsolePane

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


HISTORY_FILE = Path.home() / ".pa_console_history"
"""Commands typed in any console, kept between runs."""

WHEEL_ROWS = 3
"""Rows a mouse-wheel tick scrolls."""

KEYS_HINT = "click to expand · Ctrl+O all · wheel/PgUp/PgDn scroll · Ctrl+L clear"


def complete(commands: CommandTable, text: str) -> tuple[str, list[str]]:
    """Tab completion of the command name: ``(new text, ambiguous matches)``."""
    if " " in text:
        return text, []
    matches = sorted(n for n in commands.commands if n.startswith(text.lower()))
    if not matches:
        return text, []
    if len(matches) == 1:
        return matches[0] + " ", []
    return os.path.commonprefix(matches), matches


def _run_app(commands: CommandTable, pane: ConsolePane) -> None:
    from prompt_toolkit import Application
    from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
    from prompt_toolkit.buffer import Buffer
    from prompt_toolkit.document import Document
    from prompt_toolkit.filters import Condition
    from prompt_toolkit.history import FileHistory, InMemoryHistory
    from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
    from prompt_toolkit.layout import HSplit, Layout, VSplit, Window
    from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
    from prompt_toolkit.layout.processors import AfterInput, ConditionalProcessor
    from prompt_toolkit.mouse_events import MouseEvent, MouseEventType
    from prompt_toolkit.styles import Style

    hint = commands.bottom_hint()
    fresh = [True]  # the hint is the placeholder until the first command

    def on_accept(buf: Buffer) -> bool:
        line = buf.text
        fresh[0] = False
        pane.echo(line)
        pane.follow()
        try:
            out = commands.run(line)
        except Quit:
            app.exit()
            return False
        for text in out.splitlines():
            pane.say(text)
        return False  # the buffer resets itself, after saving the line to history

    try:
        history = FileHistory(str(HISTORY_FILE))
    except OSError:
        history = InMemoryHistory()
    buffer = Buffer(
        multiline=False,
        accept_handler=on_accept,
        history=history,
        auto_suggest=AutoSuggestFromHistory(),
    )
    keys = KeyBindings()

    @keys.add("enter")
    def _(event: KeyPressEvent) -> None:
        buffer.validate_and_handle()

    @keys.add("up", eager=True)
    def _(event: KeyPressEvent) -> None:
        buffer.history_backward()

    @keys.add("down", eager=True)
    def _(event: KeyPressEvent) -> None:
        buffer.history_forward()

    @keys.add("tab")
    def _(event: KeyPressEvent) -> None:
        text, matches = complete(commands, buffer.text)
        if matches:
            pane.say("  ".join(matches), DIM)
        buffer.document = Document(text, len(text))

    def page() -> int:
        return max(pane.height - 2, 1)

    @keys.add("pageup")
    def _(event: KeyPressEvent) -> None:
        pane.scroll(page())

    @keys.add("pagedown")
    def _(event: KeyPressEvent) -> None:
        pane.scroll(-page())

    @keys.add("c-home")
    def _(event: KeyPressEvent) -> None:
        pane.jump_top()

    @keys.add("c-end")
    def _(event: KeyPressEvent) -> None:
        pane.follow()

    @keys.add("c-o")
    def _(event: KeyPressEvent) -> None:
        pane.toggle_all()

    @keys.add("c-l")
    def _(event: KeyPressEvent) -> None:
        pane.clear()

    @keys.add("c-c")
    @keys.add("c-d")
    def _(event: KeyPressEvent) -> None:
        event.app.exit()

    class PaneControl(FormattedTextControl):
        """Turns the mouse wheel into scrolling; clicks go to the entries."""

        def mouse_handler(self, mouse_event: MouseEvent):  # type: ignore[no-untyped-def]
            if mouse_event.event_type == MouseEventType.SCROLL_UP:
                pane.scroll(WHEEL_ROWS)
                return None
            if mouse_event.event_type == MouseEventType.SCROLL_DOWN:
                pane.scroll(-WHEEL_ROWS)
                return None
            return super().mouse_handler(mouse_event)

    def toggler(entry):  # type: ignore[no-untyped-def]
        def handler(event: MouseEvent):  # type: ignore[no-untyped-def]
            if event.event_type != MouseEventType.MOUSE_UP:
                return NotImplemented
            entry.toggle()
            return None

        return handler

    def lines():  # type: ignore[no-untyped-def]
        info = messages.render_info
        if info is not None:  # the size is learned from the previous render
            pane.width, pane.height = info.window_width, info.window_height
        out = []
        for entry, row in pane.view():
            handler = toggler(entry) if entry is not None and entry.expandable else None
            out.extend((s, t, handler) if handler else (s, t) for s, t in row)
            out.append(("", "\n"))
        return out

    def status():  # type: ignore[no-untyped-def]
        style = "fg:ansiyellow" if pane.up else DIM
        frags = []
        if pane.attached is not None:
            text, on = pane.attached()
            frags.append(("bold fg:ansigreen" if on else DIM, f" {text}  ·"))
        return [*frags, (style, f" {pane.status()}"), (DIM, f"  ·  {KEYS_HINT}")]

    messages = Window(PaneControl(lines), wrap_lines=False)
    entry_box = VSplit(
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
        layout=Layout(
            HSplit(
                [
                    messages,
                    Window(FormattedTextControl(status), height=1),
                    rule,
                    entry_box,
                    rule,
                ]
            ),
            focused_element=buffer,
        ),
        key_bindings=keys,
        style=Style.from_dict({"echo": ECHO}),
        full_screen=True,
        mouse_support=True,
        refresh_interval=0.25,
    )
    app.run()


def _wait_for_ctrl_c() -> None:
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return
