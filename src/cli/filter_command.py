"""``/filter`` and ``/hide``: change the hidden packet labels while the proxy runs.

The labels are the ones the ``--hide`` option takes, matched with ``is_hidden``.
The list passed in is the one the proxy's ``show`` reads, so a change applies to
packets shown after the command. Hiding only affects the screen: packets are
still forwarded and recorded.
"""

from __future__ import annotations

from src.cli.console import Command
from src.protocol.events import _canonical


def filter_commands(hidden: list[str]) -> dict[str, Command]:
    """``filter`` and ``hide`` commands editing ``hidden`` in place."""
    initial = list(hidden)

    def listing() -> str:
        if not hidden:
            return "hiding nothing (/filter hide LABEL... adds labels)"
        return "hiding " + ", ".join(hidden)

    def add(labels: list[str]) -> None:
        if not labels:
            raise ValueError("expected one or more labels")
        for label in labels:
            canon = _canonical(label)
            if not any(_canonical(h) == canon for h in hidden):
                hidden.append(canon)

    def remove(labels: list[str]) -> None:
        if not labels:
            raise ValueError("expected one or more labels")
        gone = {_canonical(label) for label in labels}
        hidden[:] = [h for h in hidden if _canonical(h) not in gone]

    def filter_command(args: list[str]) -> str:
        if not args:
            return listing()
        action, labels = args[0].lower(), args[1:]
        if action == "hide":
            add(labels)
        elif action == "show":
            remove(labels)
        elif action == "clear":
            if labels:
                raise ValueError("clear takes no labels")
            hidden.clear()
        elif action == "reset":
            if labels:
                raise ValueError("reset takes no labels")
            hidden[:] = initial
        else:
            raise ValueError(f"unknown action {args[0]!r} (hide, show, clear, reset)")
        return listing()

    def hide_command(args: list[str]) -> str:
        add(args)
        return listing()

    return {
        "filter": Command(
            "filter [hide|show LABEL... | clear | reset]",
            "list, hide or show packet labels while running (alias /hide)",
            filter_command,
        ),
        "hide": Command(
            "hide LABEL...",
            "hide packets with these labels (same as /filter hide)",
            hide_command,
        ),
    }
