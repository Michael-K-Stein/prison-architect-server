"""Names the bot gives to objects and rooms, used instead of index / uId.

A name maps to the ``ObjectId`` pair ``(uId, index)`` of one object or room in
one game. ``Main_Power_Station`` can then stand in for ``52`` or
``8444868,52`` in any command, and shows up next to that object in the state,
problems and event feed. Names are saved per game (room) in a JSON file so
they survive a bot restart; a name whose index now holds another uId (a
different save) is ignored.
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path

DEFAULT_FILE = Path("bot-names.json")
NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_\-]{0,47}$")
"""Letters, digits, ``_`` and ``-``; starts with a letter or ``_`` so it can't be
mistaken for an index (``52``, ``#52``) or a ``uId,index`` pair."""


class NameError_(ValueError):
    """A name is malformed or unknown."""


class ObjectNames:
    """Name -> ``(uId, index)``, per game, saved to a JSON file."""

    def __init__(self, path: Path | str | None = DEFAULT_FILE) -> None:
        self.path = Path(path) if path else None
        self.game = ""
        self._data: dict[str, dict[str, tuple[int, int]]] = {}
        self._lock = threading.RLock()
        self._load()

    def _load(self) -> None:
        if not self.path or not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self._data = {
                game: {n: (int(v[0]), int(v[1])) for n, v in names.items()}
                for game, names in raw.items()
            }
        except (OSError, ValueError, TypeError, IndexError):
            self._data = {}

    def _save(self) -> None:
        if self.path:
            self.path.write_text(json.dumps(self._data, indent=1), encoding="utf-8")

    def bind(self, game: str | None) -> None:
        """Select the game (room name) whose names are in use."""
        with self._lock:
            self.game = game or ""

    def _mine(self) -> dict[str, tuple[int, int]]:
        return self._data.setdefault(self.game, {})

    def set(self, name: str, uid: int, index: int) -> None:
        """Name ``(uid, index)``; the name moves if it was used before."""
        if not NAME_RE.match(name):
            raise NameError_(
                f"{name!r} is not a usable name (letters, digits, _ and -; "
                "starts with a letter or _)"
            )
        with self._lock:
            mine = self._mine()
            for other, pair in list(mine.items()):
                if pair == (uid, index) and other != name:
                    del mine[other]  # one name per object
            mine[name] = (int(uid), int(index))
            self._save()

    def remove(self, name: str) -> bool:
        """Forget ``name``; False if it was not set."""
        with self._lock:
            gone = self._mine().pop(name, None) is not None
            if gone:
                self._save()
            return gone

    def get(self, name: str) -> tuple[int, int] | None:
        """The ``(uId, index)`` named ``name``, or None."""
        with self._lock:
            return self._mine().get(name)

    def name_of(self, index: int, uid: int | None = None) -> str | None:
        """The name of object ``index`` (and ``uid`` when given), or None."""
        with self._lock:
            for name, (u, i) in self._mine().items():
                if i == index and (uid is None or u == uid):
                    return name
            return None

    def all(self) -> dict[str, tuple[int, int]]:
        """All names of the current game."""
        with self._lock:
            return dict(self._mine())
