"""Build ``src/bot/data/object_sizes.json`` from the game's ``materials*.txt``.

Run as ``python -m src.bot.sizegen "<data dir>"`` (the folder holding
``materials.txt`` and ``materials_dlc.txt``). For every ``BEGIN Object`` block it
keeps ``Width`` / ``Height`` (default 1x1), ``AttachToWall`` (``wall``) and the
``IndoorOutdoor`` value (``0`` indoor only, ``1`` outdoor only, ``2`` either;
omitted when the game gives none). Later files override earlier ones.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

DATA_FILES = ("materials.txt", "materials_dlc.txt")
OUT_PATH = Path(__file__).parent / "data" / "object_sizes.json"

_NAME = re.compile(r"\n\s*Name\s+(\w+)")
_WIDTH = re.compile(r"\n\s*Width\s+(\d+)")
_HEIGHT = re.compile(r"\n\s*Height\s+(\d+)")
_WALL = re.compile(r"\n\s*AttachToWall\s+true")
_INDOOR = re.compile(r"\n\s*IndoorOutdoor\s+(\d)")


def parse(text: str) -> dict[str, dict[str, object]]:
    """Object name -> ``{"w", "h"[, "wall"][, "io"]}`` for each Object block."""
    out: dict[str, dict[str, object]] = {}
    for block in re.split(r"\nBEGIN Object", text)[1:]:
        block = "\n" + block
        name = _NAME.search(block)
        if name is None:
            continue
        width, height = _WIDTH.search(block), _HEIGHT.search(block)
        entry: dict[str, object] = {
            "w": int(width[1]) if width else 1,
            "h": int(height[1]) if height else 1,
        }
        if _WALL.search(block):
            entry["wall"] = True
        indoor = _INDOOR.search(block)
        if indoor:
            entry["io"] = int(indoor[1])
        out[name[1]] = entry
    return out


def build(data_dir: Path) -> dict[str, object]:
    objects: dict[str, dict[str, object]] = {}
    for name in DATA_FILES:
        path = data_dir / name
        if path.exists():
            objects.update(parse(path.read_text(encoding="utf-8", errors="ignore")))
    return {"generated_from": ", ".join(DATA_FILES), "objects": objects}


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    data = build(Path(argv[1]))
    OUT_PATH.write_text(
        json.dumps(data, indent=0, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"{len(data['objects'])} objects -> {OUT_PATH}")  # type: ignore[arg-type]
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
