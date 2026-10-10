"""Room Quality: the grade (0-15) of a room and what raises or lowers it.

The game grades some rooms (cells, dormitories, common rooms, canteens, classrooms, the
yard, the gymnasium...): ``Save Rooms`` has the grade as ``Quality`` (0-7 in the original game,
8-15 with the DLCs: user). Each graded room type has criteria in ``materials*.txt``
(:mod:`src.bot.qualitygen`, ``data/room_gradings.json``): a room size threshold per point,
an item (with alternatives) that adds a point (``GradeEffect`` is +1 unless it says
otherwise, e.g. a Mattress or an OldBed is -1), windows, glass walls, a PA system...

:func:`evaluate` checks the criteria it can see from the room's cells and objects (size and
items) and marks the others ``unknown`` (windows, walls, cleanliness...). The save's own
``Quality`` is the authority; ``computed`` is what the visible criteria add up to, so the
difference points at the criteria that are not visible.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from src.protocol.game_text import TEXT

GRADINGS: dict[str, list[dict[str, Any]]] = json.loads(
    (Path(__file__).parent / "data" / "room_gradings.json").read_text(encoding="utf-8")
)
VISIBLE = (
    "RoomSize",
    "Item",
    "OutsideWindow",
    "HasWindow",
    "HasGlassWalls",
    "HasPASystem",
)
"""Criterion types the bot can evaluate from cells and objects (with a context, see
:func:`evaluate`)."""
MAX_GRADE = 15
WINDOW_TYPES = frozenset(
    {
        "Window",
        "WindowLarge",
        "WindowClassy",
        "WindowClassyLarge",
        "GlassWindow",
        "GlassWindowLarge",
        "WoodenWindowSmall",
        "WoodenWindowLarge",
        "StainGlassWindow",
    }
)
"""Object types that count as a window (``HasWindow`` / ``OutsideWindow``)."""


def _text(room: str, key: str, fallback: str) -> str:
    found = TEXT.get(f"roomgrading_{room}_{key}") or TEXT.get(
        f"roomgrading_{room.lower()}_{key}"
    )
    return found or fallback


def _name(object_id: str) -> str:
    return (
        TEXT.get(f"object_{object_id}")
        or TEXT.get(f"object_{object_id.lower()}")
        or object_id
    )


def describe(room: str, crit: dict[str, Any]) -> str:
    """One readable line for a criterion (the game's own wording where the texts have it)."""
    kind = crit["Type"]
    if kind == "RoomSize":
        text = _text(room, "roomsize", "[*E] Room size at least *X Squares")
        return text.replace("[*E]", "").replace("*X", str(crit.get("Size", ""))).strip()
    if kind == "Item":
        names = [_name(crit["Id"]), *(_name(a) for a in crit.get("Alt", []))]
        text = _text(room, "item", "[*E] Item : *X")
        return text.replace("[*E]", "").replace("*X", " / ".join(names[:4])).strip()
    return f"{kind}" + (f" {crit['Percent']}%" if "Percent" in crit else "")


def _context_met(crit: dict[str, Any], context: dict[str, Any]) -> bool:
    """Whether a window / wall / PA criterion holds, from the room's context (see
    :func:`evaluate`). ``HasGlassWalls`` holds when glass walls are ``Percent`` of the edge.
    ``BadWalls`` ("depressing walls") is not visible yet: concrete is NOT depressing."""
    kind = crit["Type"]
    windows = context.get("windows", [])
    if kind == "OutsideWindow":
        large = bool(crit.get("Large"))
        return any(w["outdoor"] and (w["large"] or not large) for w in windows)
    if kind == "HasWindow":
        return len(windows) == int(crit.get("Quantity", 0))
    if kind == "HasGlassWalls":
        walls = context.get("walls", {})
        total = walls.get("total", 0)
        if not total:
            return False
        return walls.get("GlassWall", 0) * 100 >= int(crit.get("Percent", 50)) * total
    if kind == "HasPASystem":
        return bool(context.get("pa"))
    return False


def evaluate(
    room: str,
    cells: int,
    object_types: Iterable[str],
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate a room's criteria: ``{"criteria": [...], "computed", "max"}``.

    ``context`` (from :func:`src.bot.state.room_quality`) makes the wall and window criteria
    visible: ``windows`` (a list of ``{"large": bool, "outdoor": bool}``, one per window on the
    room's edge), ``walls`` (``{"total": n, "GlassWall": n}`` over the edge
    cells) and ``pa`` (a PASystem is in the room). Without it those criteria stay unknown.
    """
    present = Counter(object_types)
    items = []
    computed = 0
    best = 0
    for crit in GRADINGS.get(room, []):
        effect = int(crit.get("GradeEffect", 1))
        entry: dict[str, Any] = {
            "type": crit["Type"],
            "effect": effect,
            "text": describe(room, crit),
        }
        if crit.get("Multi"):
            entry["multi"] = True
        if crit["Type"] == "RoomSize":
            met = cells >= int(crit.get("Size", 0))
        elif crit["Type"] == "Item":
            found = [n for n in (crit["Id"], *crit.get("Alt", [])) if present.get(n)]
            met = bool(found)
            if found:
                entry["found"] = found
        elif context is not None and crit["Type"] in VISIBLE:
            met = _context_met(crit, context)
        else:
            entry["met"] = None  # not visible from cells and objects
            items.append(entry)
            if effect > 0:
                best += effect
            continue
        entry["met"] = met
        computed += effect if met else 0
        if effect > 0:
            best += effect
        items.append(entry)
    return {"criteria": items, "computed": computed, "max": min(best, MAX_GRADE)}
