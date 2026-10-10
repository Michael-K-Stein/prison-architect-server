"""A fixed input line at the bottom of a running server's terminal.

Log lines print above it (``patch_stdout``); typed lines go to a command table.
Without a terminal (piped stdin, a service) there is no input line and the
process just waits for Ctrl+C, as before.
"""

from __future__ import annotations

import shlex
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass

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


class CommandTable:
    """Parses a typed line and runs the matching command. Has no I/O of its own."""

    def __init__(self, commands: dict[str, Command] | None = None) -> None:
        self.commands: dict[str, Command] = {
            "help": Command("help", "list the commands", self._help),
            "quit": Command("quit", "stop the server", self._quit),
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


def run_console(commands: CommandTable, prompt: str = "> ") -> None:
    """Show the input line and run commands until ``quit`` or Ctrl+C."""
    if not sys.stdin.isatty():
        _wait_for_ctrl_c()
        return
    from prompt_toolkit import PromptSession
    from prompt_toolkit.patch_stdout import patch_stdout

    session: PromptSession[str] = PromptSession(prompt)
    print(commands.bottom_hint())
    with patch_stdout(raw=True):
        try:
            while True:
                line = session.prompt()
                try:
                    out = commands.run(line)
                except Quit:
                    return
                if out:
                    print(out)
        except (KeyboardInterrupt, EOFError):
            return


def _wait_for_ctrl_c() -> None:
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return
