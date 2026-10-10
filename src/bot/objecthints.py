"""Object hints from the game's own help texts, shown to the bot in short doses.

The data is ``data/object_hints.json`` (built by :mod:`src.bot.hintgen`). It is
loaded once, lazily. :class:`ObjectHintTracker` decides which hints go into a reply:
an object's hint is returned the first time the bot uses that object in a session,
then again only as a reminder (after ``repeat_after_calls`` further ``take`` calls,
or ``repeat_after_seconds`` since it was last shown). At most ``MAX_PER_CALL``
hints are returned per call, never-shown objects first, then the oldest reminders.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterable
from functools import cache
from pathlib import Path
from typing import Any

DATA_PATH = Path(__file__).resolve().parent / "data" / "object_hints.json"
MAX_PER_CALL = 3


@cache
def _document() -> dict[str, Any]:
    """The whole JSON document, read once."""
    if not DATA_PATH.is_file():
        return {"objects": {}, "rooms": {}}
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


@cache
def _index() -> dict[str, dict[str, Any]]:
    """Lower-cased object name -> its entry (the JSON keys are game names)."""
    return {k.lower(): v for k, v in _document().get("objects", {}).items()}


def lookup(name: str) -> dict[str, Any] | None:
    """The object's entry (``name``, ``hint``, ``extra``), matched case-insensitively."""
    entry = _index().get(str(name).strip().lower())
    return dict(entry) if entry is not None else None


class ObjectHintTracker:
    """Hands out each object's hint when it is first needed, and again as a reminder.

    Thread-safe: the control server calls :meth:`take` from several request threads.
    """

    def __init__(
        self,
        first_only: bool = True,
        repeat_after_calls: int = 25,
        repeat_after_seconds: float = 1800.0,
    ) -> None:
        """Configure the reminder rules (see the module docstring)."""
        self.first_only = first_only
        self.repeat_after_calls = repeat_after_calls
        self.repeat_after_seconds = repeat_after_seconds
        self._calls = 0
        self._shown: dict[str, tuple[int, float]] = {}  # key -> (call no., time)
        self._lock = threading.Lock()

    def take(self, names: Iterable[str], now: float | None = None) -> list[str]:
        """Hints due for ``names`` on this call (at most :data:`MAX_PER_CALL`)."""
        now = time.monotonic() if now is None else now
        with self._lock:
            self._calls += 1
            due: list[tuple[float, int, str, str]] = []
            seen: set[str] = set()
            for order, name in enumerate(names):
                key = str(name).strip().lower()
                entry = _index().get(key)
                if entry is None or not entry.get("hint") or key in seen:
                    continue
                seen.add(key)
                last = self._shown.get(key)
                if last is None:
                    due.append((float("-inf"), order, key, entry["hint"]))
                elif not self.first_only or self._reminder_due(last, now):
                    due.append((last[1], order, key, entry["hint"]))
            due.sort()
            out = []
            for _, _, key, text in due[:MAX_PER_CALL]:
                self._shown[key] = (self._calls, now)
                out.append(text)
            return out

    def _reminder_due(self, last: tuple[int, float], now: float) -> bool:
        call_no, at = last
        return (
            self._calls - call_no >= self.repeat_after_calls
            or now - at >= self.repeat_after_seconds
        )
