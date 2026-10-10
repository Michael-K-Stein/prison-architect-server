"""The adviser speakers for ``ctl broadcast``."""

from __future__ import annotations

import pytest

from src.bot.broadcast import SPEAKERS, speaker_index
from src.protocol.enums import ADVISERS


def test_speakers_are_the_advisers_without_unknown() -> None:
    assert SPEAKERS["CEO"] == 1 and SPEAKERS["Warden"] == 2
    assert "Unknown" not in SPEAKERS
    assert sorted(SPEAKERS.values()) == [k for k in sorted(ADVISERS) if k != 0]


@pytest.mark.parametrize(
    ("name", "index"),
    [("CEO", 1), ("the warden", 2), ("The Governor", 3), ("  kingpin ", 6)],
)
def test_speaker_index_ignores_case_and_the(name: str, index: int) -> None:
    assert speaker_index(name) == index


def test_unknown_speaker_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown speaker"):
        speaker_index("Janitor")
