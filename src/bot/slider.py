"""The game-speed slider: a prompt_toolkit Application drawn as a bar of stops."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from prompt_toolkit import Application
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
from prompt_toolkit.layout import Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl

from src.bot.speed import SPEED_HELP, SPEED_STOPS


def render_slider(stops: Sequence[str], index: int) -> FormattedText:
    """Draw the slider: a bar filled up to ``index``, the labels under it."""
    count = len(stops)
    width = max(len(label) for label in stops) + 2
    half = width // 2
    on, off = "fg:ansicyan", "fg:ansibrightblack"
    bar: list[tuple[str, str]] = []
    names: list[tuple[str, str]] = []
    for i, label in enumerate(stops):
        bar.append((on if i <= index else off, ("━" if i else " ") * half))
        dot = "◉" if i == index else "●" if i < index else "○"
        bar.append(
            ("bold fg:ansibrightcyan" if i == index else on if i < index else off, dot)
        )
        bar.append(
            (
                on if i < index else off,
                ("━" if i < count - 1 else " ") * (width - half - 1),
            )
        )
        style = "bold reverse fg:ansibrightcyan" if i == index else off
        names.append((style, label.center(width)))
    title = ("bold", "Game speed\n\n")
    return FormattedText([title, *bar, ("", "\n"), *names])


def plain(text: FormattedText) -> str:
    """The text of formatted text without styles."""
    return "".join(part[1] for part in text)


def handle_key(index: int, key: str, count: int) -> tuple[int, str | None]:
    """Apply a key: returns the new index and ``"submit"`` / ``"cancel"`` / None."""
    if key in ("left", "h"):
        return max(index - 1, 0), None
    if key in ("right", "l"):
        return min(index + 1, count - 1), None
    if key == "home":
        return 0, None
    if key == "end":
        return count - 1, None
    if key == "enter":
        return index, "submit"
    if key in ("escape", "q", "c-c"):
        return index, "cancel"
    return index, None


def pick_speed(index: int = 1, *, input: Any = None, output: Any = None) -> int | None:
    """Run the slider; the chosen stop's index, or None when cancelled."""
    state = {"index": index}
    keys = KeyBindings()
    names = ("left", "right", "enter", "escape", "home", "end", "c-c", "h", "l", "q")

    def make(name: str) -> Callable[[KeyPressEvent], None]:
        def handler(event: KeyPressEvent) -> None:
            state["index"], action = handle_key(state["index"], name, len(SPEED_STOPS))
            if action == "submit":
                event.app.exit(result=state["index"])
            elif action == "cancel":
                event.app.exit(result=None)

        return handler

    for name in names:
        keys.add(name, eager=True)(make(name))
    control = FormattedTextControl(
        lambda: FormattedText(
            [
                *render_slider([n for n, _ in SPEED_STOPS], state["index"]),
                ("", "\n\n"),
                ("fg:ansibrightblack", SPEED_HELP),
            ]
        )
    )
    app: Application[int | None] = Application(
        layout=Layout(Window(control, wrap_lines=True)),
        key_bindings=keys,
        input=input,
        output=output,
        erase_when_done=True,
    )
    return app.run()
