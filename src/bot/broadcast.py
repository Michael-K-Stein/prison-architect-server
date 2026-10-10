"""The speakers ``ctl broadcast`` can choose from: the game's advisers.

The host shows a ``NewSpeechAdded`` from any client as a message from the adviser
whose index it names (``ADVISERS``); clients show it too when sent with broadcast.
"""

from __future__ import annotations

from src.protocol.enums import ADVISERS

SPEAKERS: dict[str, int] = {
    name.removeprefix("The "): index
    for index, name in sorted(ADVISERS.items())
    if index != 0  # 0 is "Unknown": not a speaker you can pick
}
"""Short name (``CEO``, ``Warden``...) -> adviser index."""


def speaker_index(name: str) -> int:
    """The adviser index for a speaker name, ignoring case and a leading "The"."""
    key = name.strip().removeprefix("The ").removeprefix("the ").lower()
    for short, index in SPEAKERS.items():
        if short.lower() == key:
            return index
    msg = f"unknown speaker {name!r}; one of {', '.join(SPEAKERS)}"
    raise ValueError(msg)
