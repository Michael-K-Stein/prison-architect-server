"""Build ``src/bot/data/prefabs.json`` from the game's ``prefabs*.txt``.

Run as ``python -m src.bot.prefabgen "<data dir>"``. A prefab is a room the game designed
itself (``BEGIN Prefab Name w h RoomType ... BEGIN Object Type X x Y y orX orY END``): its
outer size (walls included), the objects with the way they face and its doors. Prefabs
with ``CustomArea`` are outdoor areas (fences, grass) and are kept but flagged.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

DATA_FILES = ("prefabs.txt", "prefabs_dlc.txt")
OUT_PATH = Path(__file__).parent / "data" / "prefabs.json"

_OBJECT = re.compile(
    r"BEGIN Object\s+Type\s+(\w+)\s+x\s+(-?\d+)\s+y\s+(-?\d+)"
    r"(?:\s+orX\s+(-?\d+))?(?:\s+orY\s+(-?\d+))?"
)
_MATERIAL = re.compile(
    r"BEGIN Material\s+Type\s+(\w+)\s+x\s+(\d+)\s+y\s+(\d+)\s+w\s+(\d+)\s+h\s+(\d+)"
)


def parse(text: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for m in re.finditer(r"BEGIN Prefab\s+(.*?)\nEND", text, re.S):
        block = m.group(1)
        name = re.search(r"Name\s+(\w+)", block)
        w = re.search(r"\n\s*w\s+(\d+)", "\n" + block)
        h = re.search(r"\n\s*h\s+(\d+)", "\n" + block)
        if not (name and w and h):
            continue
        room = re.search(r"RoomType\s+(\w+)", block)
        out[name[1]] = {
            "w": int(w[1]),
            "h": int(h[1]),
            "room": room[1] if room else None,
            "custom": "CustomArea" in block,
            "objects": [
                [t, int(x), int(y), int(ox or 0), int(oy or 1)]
                for t, x, y, ox, oy in _OBJECT.findall(block)
            ],
            "materials": [
                [t, int(x), int(y), int(a), int(b)]
                for t, x, y, a, b in _MATERIAL.findall(block)
            ],
        }
    return out


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    prefabs: dict[str, dict] = {}
    for name in DATA_FILES:
        path = Path(argv[1]) / name
        if path.exists():
            prefabs.update(parse(path.read_text(encoding="utf-8", errors="ignore")))
    OUT_PATH.write_text(
        json.dumps(prefabs, indent=0, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"{len(prefabs)} prefabs -> {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
