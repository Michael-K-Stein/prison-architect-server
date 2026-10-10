"""The game's own room layouts (prefabs), turned into building specs.

``data/prefabs.json`` (built by :mod:`src.bot.prefabgen`) holds each prefab's outer size
(walls included), objects with their facing and doors. :func:`to_spec` converts one into
the spec :mod:`src.bot.building` builds: a single-room building whose door cells are the
entrances, objects relative to the room's interior, ``orX/orY`` as ``up/down/left/right``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PREFABS_PATH = Path(__file__).parent / "data" / "prefabs.json"
FACING = {(0, 1): "down", (0, -1): "up", (1, 0): "right", (-1, 0): "left"}


def load() -> dict[str, dict[str, Any]]:
    return json.loads(PREFABS_PATH.read_text(encoding="utf-8"))


PREFABS = load()


SKIP = frozenset(
    {"Light", "Drain", "PipeSmall", "PipeLarge", "ElectricalCable", "DoorMat", "Window"}
)
"""Prefab objects the converter leaves out: lights are automatic, cables and pipes are laid
by ``ctl connect`` (a pipe has to end on the appliance, and a drain sits under it), a mat lies on
the door cell."""


def is_door(name: str) -> bool:
    return "Door" in name or "Gate" in name


def for_room(room: str | None = None) -> list[str]:
    """Names of the room prefabs (not outdoor areas) of a room type, largest first."""
    found = [
        (p["w"] * p["h"], name)
        for name, p in PREFABS.items()
        if not p["custom"] and p["room"] and (room is None or p["room"] == room)
    ]
    return [name for _, name in sorted(found, reverse=True)]


def to_spec(name: str, x: int, y: int) -> dict[str, Any]:
    """A building spec for prefab ``name`` placed with its top left corner at ``x, y``.

    Objects outside the interior (wall decorations) are left out; every door becomes an
    entrance and the first one is the room's door.
    """
    p = PREFABS[name]
    w, h = p["w"], p["h"]
    doors = [
        (o[1], o[2])
        for o in p["objects"]
        if is_door(o[0]) and (o[1] in (0, w - 1) or o[2] in (0, h - 1))
    ]  # doors inside the prefab (partitions) are not represented
    if not doors:
        raise ValueError(f"prefab {name} has no door")
    objects = []
    for kind, ox, oy, orx, ory in p["objects"]:
        if is_door(kind) or kind in SKIP:
            continue
        if 1 <= ox <= w - 2 and 1 <= oy <= h - 2:
            objects.append([kind, ox - 1, oy - 1, FACING.get((orx, ory), "down")])
    return {
        "x": x,
        "y": y,
        "width": w,
        "height": h,
        "entrances": [list(d) for d in doors],
        "rooms": [
            {
                "type": p["room"],
                "x": 1,
                "y": 1,
                "w": w - 2,
                "h": h - 2,
                "door": list(doors[0]),
                "objects": objects,
            }
        ],
    }
