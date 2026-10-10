"""The box and dim style shared by the terminal input lines (console and bot HUD)."""

from __future__ import annotations

DIM = "fg:ansibrightblack"
"""prompt_toolkit style for the box lines and hints."""

RULE = "─"
"""Horizontal line character for separators and box edges."""

ECHO = "fg:#ffffff bg:#3a3a3a"
"""White on gray: how a submitted command is echoed back."""

BEGIN = "❯ "
"""The marker in front of the input and of each echoed command."""

EDGE = ""
"""The right-hand edge of the input line."""


def banner(title: str, width: int) -> list[str]:
    """A title between two rules, to open a console's message pane."""
    rule = RULE * width
    return [rule, title.center(width).rstrip(), rule]
