"""A full-screen console for a running server: scrollable, expandable message pane
above a fixed input box.

Log lines and command output go into a :class:`~src.cli.pane.ConsolePane`;
typed lines go to a command table. Without a terminal (piped stdin, a service)
there is no screen and the process just waits for Ctrl+C, as before.

Keys: mouse wheel / PgUp / PgDn scroll, drag selects and copies (Ctrl+C copies, Esc clears), Ctrl+End follows the newest line, a click
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
from typing import Any
from pathlib import Path

from src.cli.frame import BEGIN, DIM, ECHO, EDGE, RULE
from src.cli.pane import ConsolePane

CommandFn = Callable[[list[str]], str]
"""Takes the arguments after the command name, returns a line to print."""


class Quit(Exception):
    """Raised by a command to end the console loop."""


class Choose(Exception):
    """Raised by a command to have the user pick one of ``options``; the pick
    replaces the input line with ``template.format(pick)`` for them to finish."""

    def __init__(self, prompt: str, options: list[str], template: str) -> None:
        super().__init__(prompt)
        self.prompt, self.options, self.template = prompt, options, template


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
        if not line.strip():
            return ""
        if not line.lstrip().startswith("/"):
            return "commands start with /; try /help"
        try:
            words = shlex.split(line.lstrip()[1:])
        except ValueError as exc:
            return f"could not parse: {exc}"
        if not words:
            return "type a command after /; try /help"
        command = self.commands.get(words[0].lower())
        if command is None:
            return f"unknown command {words[0]!r}; try /help"
        try:
            return command.run(words[1:])
        except (ValueError, OSError) as exc:
            return f"/{command.usage}: {exc}"

    def _help(self, _args: list[str]) -> str:
        return "\n".join(
            f"  {'/' + c.usage:<25} {c.summary}" for c in self.commands.values()
        )

    def _quit(self, _args: list[str]) -> str:
        raise Quit

    def bottom_hint(self) -> str:
        """The one-line summary shown above the input line."""
        return "type /command, /help for the list, /quit to stop"


@dataclass(frozen=True)
class View:
    """A pane window plus the selection hooks the key bindings need."""

    window: object
    copy: Callable[..., bool]
    clear_selection: Callable[[], None]


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

KEYS_HINT = "click expand · drag select+copy · Ctrl+O all · wheel/PgUp/PgDn scroll · Ctrl+L clear"


def complete(commands: CommandTable, text: str) -> tuple[str, list[str]]:
    """Tab completion of ``/name``: ``(new text, ambiguous matches)``."""
    if not text.startswith("/") or " " in text:
        return text, []
    matches = sorted(
        "/" + n for n in commands.commands if ("/" + n).startswith(text.lower())
    )
    if not matches:
        return text, []
    if len(matches) == 1:
        return matches[0] + " ", []
    return os.path.commonprefix(matches), matches


def copy_to_clipboard(text: str, app: object) -> None:
    """Put text on the system clipboard (``clip`` on Windows) and via OSC 52."""
    import base64
    import subprocess

    if sys.platform == "win32":
        try:
            subprocess.run(
                ["clip"], input=text.encode("utf-16le"), check=False, timeout=5
            )
            return
        except (OSError, subprocess.SubprocessError):
            pass
    payload = base64.b64encode(text.encode()).decode()
    out = app.output  # type: ignore[attr-defined]
    out.write_raw(f"\x1b]52;c;{payload}\x07")
    out.flush()


def _run_app(commands: CommandTable, pane: ConsolePane) -> None:
    from prompt_toolkit import Application
    from prompt_toolkit.application import get_app
    from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
    from prompt_toolkit.buffer import Buffer
    from prompt_toolkit.completion import Completer, Completion
    from prompt_toolkit.document import Document
    from prompt_toolkit.filters import Condition
    from prompt_toolkit.history import FileHistory, InMemoryHistory
    from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
    from prompt_toolkit.layout import (
        ConditionalContainer,
        Dimension,
        Float,
        FloatContainer,
        HSplit,
        Layout,
        VSplit,
        Window,
    )
    from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
    from prompt_toolkit.layout.menus import CompletionsMenu
    from prompt_toolkit.layout.processors import AfterInput, ConditionalProcessor
    from prompt_toolkit.mouse_events import MouseEvent, MouseEventType
    from prompt_toolkit.styles import Style

    hint = commands.bottom_hint()
    pick: list[dict[str, Any] | None] = [None]  # the open choice list, if any
    fresh = [True]  # the hint is the placeholder until the first command

    def on_accept(buf: Buffer) -> bool:
        line = buf.text
        fresh[0] = False
        output.say("")
        output.echo(line)
        output.follow()
        try:
            out = commands.run(line)
        except Quit:
            app.exit()
            return False
        except Choose as ask:
            pick[0] = {"ask": ask, "index": 0}
            output.say("")
            return False
        for text in out.splitlines():
            output.say(text)
        output.say("")
        return False  # the buffer resets itself, after saving the line to history

    try:
        history = FileHistory(str(HISTORY_FILE))
    except OSError:
        history = InMemoryHistory()

    class CommandCompleter(Completer):
        """Offers ``/name`` (with its summary) while a command name is being typed."""

        def get_completions(self, document, complete_event):  # type: ignore[no-untyped-def]
            text = document.text_before_cursor
            if not text.startswith("/") or " " in text:
                return
            for name, command in sorted(commands.commands.items()):
                if ("/" + name).startswith(text.lower()):
                    yield Completion(
                        "/" + name,
                        start_position=-len(text),
                        display_meta=command.summary,
                    )

    buffer = Buffer(
        completer=CommandCompleter(),
        complete_while_typing=True,
        multiline=False,
        accept_handler=on_accept,
        history=history,
        auto_suggest=AutoSuggestFromHistory(),
    )
    keys = KeyBindings()
    output = ConsolePane(show_banner=False)
    views: list[View] = []

    @keys.add("enter")
    def _(event: KeyPressEvent) -> None:
        buffer.validate_and_handle()

    @keys.add("up", eager=True)
    def _(event: KeyPressEvent) -> None:
        if buffer.complete_state:
            buffer.complete_previous()
        else:
            buffer.history_backward()

    @keys.add("down", eager=True)
    def _(event: KeyPressEvent) -> None:
        if buffer.complete_state:
            buffer.complete_next()
        else:
            buffer.history_forward()

    @keys.add("tab")
    def _(event: KeyPressEvent) -> None:
        text, _matches = complete(commands, buffer.text)
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
        output.clear()

    @keys.add("c-c")
    def _(event: KeyPressEvent) -> None:
        copied = False
        for view in views:  # Ctrl+C copies a selection, like Claude Code
            copied = view.copy(event.app) or copied
        if not copied:
            event.app.exit()

    @keys.add("c-d")
    def _(event: KeyPressEvent) -> None:
        event.app.exit()

    @keys.add("escape", eager=True)
    def _(event: KeyPressEvent) -> None:
        for view in views:
            view.clear_selection()

    picking = Condition(lambda: pick[0] is not None)

    def move(step: int) -> None:
        state = pick[0]
        if state is not None:
            count = len(state["ask"].options)
            state["index"] = (state["index"] + step) % count

    @keys.add("up", eager=True, filter=picking)
    def _(event: KeyPressEvent) -> None:
        move(-1)

    @keys.add("down", eager=True, filter=picking)
    @keys.add("tab", filter=picking)
    def _(event: KeyPressEvent) -> None:
        move(1)

    @keys.add("enter", filter=picking)
    def _(event: KeyPressEvent) -> None:
        state = pick[0]
        pick[0] = None
        if state is not None:
            ask = state["ask"]
            text = ask.template.format(ask.options[state["index"]])
            buffer.document = Document(text, len(text))

    @keys.add("escape", eager=True, filter=picking)
    @keys.add("c-c", filter=picking)
    def _(event: KeyPressEvent) -> None:
        pick[0] = None

    def pick_text():  # type: ignore[no-untyped-def]
        state = pick[0]
        if state is None:
            return []
        ask = state["ask"]
        out = [(DIM, f" {ask.prompt}: ↑/↓ choose · Enter select · Esc cancel\n")]
        for i, option in enumerate(ask.options):
            on = i == state["index"]
            mark = "›" if on else " "
            out.append(("bold fg:ansigreen" if on else "", f" {mark} {option}\n"))
        return out

    def build_view(pane: ConsolePane) -> Window:
        window: list[Window] = []
        shown: list[tuple[object, str]] = []  # (entry, plain text) per visible row
        sel: list[tuple[int, int] | None] = [None, None]  # anchor, cursor as (row, col)
        dragged = [False]

        def selection() -> tuple[tuple[int, int], tuple[int, int]] | None:
            a, b = sel
            if a is None or b is None or a == b:
                return None
            return (a, b) if a <= b else (b, a)

        def selected_text() -> str:
            span = selection()
            if span is None:
                return ""
            (r0, c0), (r1, c1) = span
            out = []
            for r in range(r0, min(r1, len(shown) - 1) + 1):
                text = shown[r][1]
                lo = c0 if r == r0 else 0
                hi = c1 if r == r1 else len(text)
                out.append(text[lo:hi].rstrip())
            return "\n".join(out)

        def copy_selection(app_: Application[None]) -> bool:
            text = selected_text()
            if not text:
                return False
            copy_to_clipboard(text, app_)
            output.say(f"copied {len(text)} characters", DIM)
            return True

        def copy(app_: Application[None]) -> bool:
            if selection() is None:
                return False
            copy_selection(app_)
            sel[:] = [None, None]
            return True

        def clear_selection() -> None:
            sel[:] = [None, None]

        class PaneControl(FormattedTextControl):
            """Wheel scrolls, drag selects and copies, a plain click expands an entry."""

            def mouse_handler(self, mouse_event: MouseEvent):  # type: ignore[no-untyped-def]
                kind = mouse_event.event_type
                if kind == MouseEventType.SCROLL_UP:
                    sel[:] = [None, None]
                    pane.scroll(WHEEL_ROWS)
                    return None
                if kind == MouseEventType.SCROLL_DOWN:
                    sel[:] = [None, None]
                    pane.scroll(-WHEEL_ROWS)
                    return None
                pos = (mouse_event.position.y, mouse_event.position.x)
                if kind == MouseEventType.MOUSE_DOWN:
                    sel[:] = [pos, pos]
                    dragged[0] = False
                    return None
                if kind == MouseEventType.MOUSE_MOVE and sel[0] is not None:
                    sel[1] = pos
                    dragged[0] = pos != sel[0]
                    return None
                if kind == MouseEventType.MOUSE_UP:
                    if sel[0] is not None:
                        sel[1] = pos
                    if selection() is not None:
                        copy_selection(get_app())
                        return None
                    sel[:] = [None, None]
                    if 0 <= pos[0] < len(shown):
                        entry = shown[pos[0]][0]
                        if entry is not None and entry.expandable:  # type: ignore[attr-defined]
                            entry.toggle()  # type: ignore[attr-defined]
                    return None
                return NotImplemented

        def lines():  # type: ignore[no-untyped-def]
            info = window[0].render_info
            if info is not None:  # the size is learned from the previous render
                pane.width, pane.height = info.window_width, info.window_height
            span = selection()
            view = pane.view()
            shown[:] = [(e, "".join(t for _, t in row)) for e, row in view]
            out = []
            for r, (_entry, row) in enumerate(view):
                col = 0
                for style, text in row:
                    if span is None or not (span[0][0] <= r <= span[1][0]):
                        out.append((style, text))
                    else:
                        lo = span[0][1] if r == span[0][0] else 0
                        hi = span[1][1] if r == span[1][0] else 1 << 30
                        a, b = max(lo - col, 0), min(max(hi - col, 0), len(text))
                        if a >= b:
                            out.append((style, text))
                        else:
                            out.append((style, text[:a]))
                            out.append((f"{style} reverse", text[a:b]))
                            out.append((style, text[b:]))
                    col += len(text)
                out.append(("", "\n"))
            return out

        window.append(Window(PaneControl(lines), wrap_lines=False))
        views.append(View(window[0], copy, clear_selection))
        return window[0]

    def status():  # type: ignore[no-untyped-def]
        style = "fg:ansiyellow" if pane.up else DIM
        frags = []
        if pane.attached is not None:
            text, on = pane.attached()
            frags.append(("bold fg:ansigreen" if on else DIM, f" {text}  ·"))
        return [*frags, (style, f" {pane.status()}"), (DIM, f"  ·  {KEYS_HINT}")]

    messages = build_view(pane)
    results = build_view(output)
    results.height = Dimension(min=3, preferred=8, max=12)
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
            FloatContainer(
                HSplit(
                    [
                        messages,
                        Window(height=1, char=RULE, style=DIM),
                        results,
                        Window(FormattedTextControl(status), height=1),
                        rule,
                        ConditionalContainer(
                            Window(FormattedTextControl(pick_text)), filter=picking
                        ),
                        entry_box,
                        rule,
                    ]
                ),
                floats=[
                    Float(
                        xcursor=True,
                        ycursor=True,
                        content=CompletionsMenu(max_height=8),
                    )
                ],
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
