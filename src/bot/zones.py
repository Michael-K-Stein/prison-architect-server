"""Named map zones: ``Food_Zone`` stands for a rectangle of cells.

Like :mod:`src.bot.names` for objects, but for areas. A zone is ``x, y, w, h``
(top-left cell and size); it is saved per game (room) in a JSON file so it
survives a bot restart. A build/area request may carry ``"zone": NAME`` instead
of coordinates (:meth:`Zones.resolve`), and ``area`` lists the zones it overlaps.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from src.bot.names import NAME_RE, NameError_

DEFAULT_FILE = Path("bot-zones.json")

Rect = tuple[int, int, int, int]


def bounds(rects: list[Rect]) -> Rect:
    """The smallest rectangle that holds all of ``rects``."""
    x0 = min(r[0] for r in rects)
    y0 = min(r[1] for r in rects)
    x1 = max(r[0] + r[2] for r in rects)
    y1 = max(r[1] + r[3] for r in rects)
    return x0, y0, x1 - x0, y1 - y0


def mask_rows(rows: list[str], x: int, y: int, rects: list[Rect]) -> list[str]:
    """``rows`` (a grid whose top-left cell is ``x, y``) with cells outside ``rects`` blank."""
    return [
        "".join(
            ch
            if any(
                rx <= x + i < rx + rw and ry <= y + j < ry + rh
                for rx, ry, rw, rh in rects
            )
            else " "
            for i, ch in enumerate(row)
        )
        for j, row in enumerate(rows)
    ]


class Zones:
    """Name -> ``(x, y, w, h)``, per game, saved to a JSON file."""

    def __init__(self, path: Path | str | None = DEFAULT_FILE) -> None:
        self.path = Path(path) if path else None
        self.game = ""
        self._data: dict[str, dict[str, Rect]] = {}
        self._lock = threading.RLock()
        if self.path and self.path.exists():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                self._data = {
                    g: {n: tuple(int(c) for c in r) for n, r in zs.items()}  # type: ignore[misc]
                    for g, zs in raw.items()
                }
            except (OSError, ValueError, TypeError):
                self._data = {}

    def bind(self, game: str | None) -> None:
        """Select the game (room name) whose zones are in use."""
        with self._lock:
            self.game = game or ""

    def _mine(self) -> dict[str, Rect]:
        return self._data.setdefault(self.game, {})

    def _save(self) -> None:
        if self.path:
            self.path.write_text(json.dumps(self._data, indent=1), encoding="utf-8")

    def set(self, name: str, x: int, y: int, w: int, h: int) -> None:
        """Name the rectangle (a leaf); the name moves if it was used before.

        ``:`` nests: ``CellBlock:Min:Showers`` is inside ``CellBlock:Min``. A name
        is either a leaf (has a rectangle) or a group (has children), not both.
        """
        if not name or not all(NAME_RE.match(part) for part in name.split(":")):
            raise NameError_(
                f"{name!r} is not a usable zone name (parts of letters, digits, _ and -, "
                "starting with a letter or _, joined by ':')"
            )
        if w < 1 or h < 1:
            raise NameError_("a zone is at least 1x1 cells")
        with self._lock:
            mine = self._mine()
            parts = name.split(":")
            for i in range(1, len(parts)):
                if ":".join(parts[:i]) in mine:
                    raise NameError_(
                        f"{':'.join(parts[:i])!r} is a rectangle, not a group"
                    )
            if any(n.startswith(name + ":") for n in mine):
                raise NameError_(f"{name!r} is a group; remove its children first")
            mine[name] = (int(x), int(y), int(w), int(h))
            self._save()

    def remove(self, name: str) -> bool:
        """Forget a leaf, or a group with everything in it; False if unknown."""
        with self._lock:
            mine = self._mine()
            gone = [n for n in mine if n == name or n.startswith(name + ":")]
            for n in gone:
                del mine[n]
            if gone:
                self._save()
            return bool(gone)

    def rects(self, name: str) -> list[Rect]:
        """The rectangles of a leaf, or of all leaves under a group; [] if unknown."""
        with self._lock:
            return [
                r
                for n, r in self._mine().items()
                if n == name or n.startswith(name + ":")
            ]

    def all(self) -> dict[str, dict[str, int]]:
        """All leaf zones of the current game as ``{name: {x, y, w, h}}``."""
        with self._lock:
            return {
                n: dict(zip("xywh", r, strict=True)) for n, r in self._mine().items()
            }

    def groups(self) -> list[str]:
        """The group names (every proper prefix of a leaf), sorted."""
        with self._lock:
            found: set[str] = set()
            for n in self._mine():
                parts = n.split(":")
                found.update(":".join(parts[:i]) for i in range(1, len(parts)))
            return sorted(found)

    def overlapping(self, x: int, y: int, w: int, h: int) -> list[str]:
        """Names of the leaf zones that share a cell with the rectangle."""
        with self._lock:
            return [
                n
                for n, (zx, zy, zw, zh) in self._mine().items()
                if zx < x + w and x < zx + zw and zy < y + h and y < zy + zh
            ]

    def resolve(self, spec: dict[str, Any]) -> list[dict[str, Any]]:
        """``spec`` as one spec per rectangle of its ``zone`` (or ``[spec]`` as is)."""
        name = spec.get("zone")
        if name is None:
            return [spec]
        rects = self.rects(str(name))
        if not rects:
            raise NameError_(f"no zone named {name!r} (`ctl zone list`)")
        base = {k: v for k, v in spec.items() if k != "zone"}
        return [
            base | {"x": x, "y": y, "width": w, "height": h} for x, y, w, h in rects
        ]
