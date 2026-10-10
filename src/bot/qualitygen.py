"""Build ``src/bot/data/room_gradings.json`` from the game's ``materials*.txt``.

Run as ``python -m src.bot.qualitygen "<data dir>"``. A room block lists ``BEGIN Grading
Type <T> ... END`` lines: the criteria of its quality grade (Room Quality in the game:
0-7 in the original game, 8-15 with the DLCs, user). ``Type`` is ``RoomSize`` (``Size``
squares), ``Item`` (``Id`` with ``Alt`` alternatives, ``Multi``), ``OutsideWindow``,
``HasWindow``, ``HasGlassWalls``, ``BadWalls`` (``Percent``), ``HasPASystem``, ``Floor``,
``MealQuality`` ... ``GradeEffect`` (default +1) is how much a met criterion moves the grade.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

DATA_FILES = ("materials.txt", "materials_dlc.txt")
OUT_PATH = Path(__file__).parent / "data" / "room_gradings.json"
_GRADING = re.compile(r"BEGIN Grading\s+(.*?)\s+END", re.S)
_NAME = re.compile(r"Name\s+(\w+)")


def _value(text: str) -> object:
    if text.lower() in ("true", "false"):
        return text.lower() == "true"
    try:
        return int(text)
    except ValueError:
        return text


def parse(text: str) -> dict[str, list[dict]]:
    """Room name -> its grading criteria (a room block runs to the next ``BEGIN Room``)."""
    out: dict[str, list[dict]] = {}
    for block in re.split(r"\nBEGIN Room\b", "\n" + text)[1:]:
        name = _NAME.search(block)
        if name is None:
            continue
        items = []
        for g in _GRADING.finditer(block):
            words = g.group(1).split()
            entry: dict = {}
            for key, value in zip(words[::2], words[1::2], strict=False):
                entry[key] = _value(value)
            if "Alt" in entry:
                entry["Alt"] = [a for a in str(entry["Alt"]).split(",") if a]
            if entry:
                items.append(entry)
        if items:
            out[name[1]] = items
    return out


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    rooms: dict[str, list[dict]] = {}
    for name in DATA_FILES:
        path = Path(argv[1]) / name
        if path.exists():
            rooms.update(parse(path.read_text(encoding="utf-8", errors="ignore")))
    OUT_PATH.write_text(
        json.dumps(rooms, indent=0, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"{len(rooms)} graded rooms -> {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
