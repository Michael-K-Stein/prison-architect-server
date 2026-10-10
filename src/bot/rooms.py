"""Plan a room that meets the game's requirements, and the build jobs for it.

:func:`plan_room` turns a room type's rules (:data:`~src.protocol.room_rules.ROOM_RULES`)
and the object footprints (``data/object_sizes.json``, built by :mod:`src.bot.sizegen`)
into a :class:`RoomPlan`: the interior size, the door and where each object goes.
:func:`stages` turns a plan into the ordered ``ctl build`` job specs for a map position.

Layout (interior coordinates, ``(0, 0)`` top left, objects anchored by their top left
cell, facing down): objects that attach to a wall (``wall`` in the size table: Bed,
Toilet...) sit in the top row against the top wall, the rest in rows below with one
free row between, the last row and the right-hand column stay free as a corridor and the
door is in the bottom wall at that column. Footprints come from the game data; the
anchor is the footprint's top left cell (journal2, PowerExportMeter at 28,43).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from src.protocol.game_tables import OBJECTS
from src.protocol.room_rules import ROOM_RULES

SIZES_PATH = Path(__file__).parent / "data" / "object_sizes.json"
VARIANTS = ("min", "lavish")
LAVISH_PREFER = ("Fancy", "Comfy", "Superior", "Oak", "Tall")
"""Alternatives containing one of these words are preferred in a lavish room."""
LAVISH_EXTRA = ("Plant", "Plant")
"""Decor added to every lavish indoor room."""
LAVISH_GROW = 2
"""Cells added to each side of a lavish room's minimum interior."""
MIN_BUILDING = 3
"""Smallest interior of a walled room with no object requirement."""
BUILDING_FREE = frozenset({"None", "ClearRooms"})
UNRELEASED = {
    "SuperiorCell": "not in the game client (it cannot be created there; its labels are "
    "code-like, e.g. roomgrading_SuperiorCell_Item): the host accepts the zone but "
    "refunds the SuperiorBed, so the room never meets its rules (journal2)"
}
"""Room types in the data files that the real game does not offer (unfinished content)."""
"""Rooms with no requirements at all: just a zone, no building."""


def _load_sizes() -> dict[str, dict[str, object]]:
    return json.loads(SIZES_PATH.read_text(encoding="utf-8"))["objects"]


SIZES = _load_sizes()


@dataclass(frozen=True)
class Placement:
    """One object: its type and top left cell inside the room."""

    name: str
    dx: int
    dy: int


@dataclass(frozen=True)
class RoomPlan:
    """A room's interior size, door column and objects."""

    room: str
    variant: str
    w: int
    h: int
    door: int
    """Interior column of the door in the bottom wall."""
    objects: tuple[Placement, ...]
    building: bool
    """True: a foundation with walls, floor and a door; False: just a zone."""
    flags: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    @property
    def outer(self) -> tuple[int, int]:
        """The foundation's size (interior plus the wall ring)."""
        return self.w + 2, self.h + 2


def size_of(name: str) -> tuple[int, int]:
    info = SIZES.get(name, {})
    return int(info.get("w", 1)), int(info.get("h", 1))  # type: ignore[call-overload]


def _usable(name: str) -> bool:
    return name in OBJECTS.values() and name in SIZES


def _choose(name: str, alternatives: tuple[str, ...], variant: str) -> str:
    """The object to place for a requirement: the smallest in a minimum room, a fancy
    one (``LAVISH_PREFER``) in a lavish room."""
    options = [n for n in (name, *alternatives) if _usable(n)]
    if not options:
        raise KeyError(f"no placeable object among {name} {alternatives}")
    if variant == "lavish":
        fancy = [n for n in options if any(w in n for w in LAVISH_PREFER)]
        if fancy:
            return fancy[0]
        return options[0]
    return min(options, key=lambda n: (size_of(n)[0] * size_of(n)[1], n != name))


def _pack(items: list[str], width: int) -> tuple[list[Placement], int] | None:
    """Rows of objects within ``width`` cells; (placements, rows' total height), or None
    when an object is wider than the row."""
    wall = [n for n in items if SIZES.get(n, {}).get("wall")]
    other = [n for n in items if n not in wall]
    placed: list[Placement] = []
    y = 0
    for group in (wall, other):
        x, row_h = 0, 0
        for name in group:
            w, h = size_of(name)
            if w > width:
                return None
            if x + w > width:
                y += row_h + 1  # a free row between rows of objects
                x, row_h = 0, 0
            placed.append(Placement(name, x, y))
            x += w
            row_h = max(row_h, h)
        if row_h:
            y += row_h + 1
    return placed, y


def plan_room(room: str, variant: str = "min") -> RoomPlan:
    """The layout for ``room`` (a key of ``ROOM_RULES``); ``variant`` is ``min`` or
    ``lavish``. Raises ``KeyError`` for an unknown room or unplaceable object."""
    if variant not in VARIANTS:
        raise KeyError(f"variant must be one of {', '.join(VARIANTS)}")
    min_size, flags, required = ROOM_RULES[room]
    items = [_choose(name, alts, variant) for name, alts in required]
    lavish = variant == "lavish"
    notes: list[str] = []
    if lavish:
        items += [n for n in LAVISH_EXTRA if _usable(n)]
        if "Table" in (n for n, _ in required):
            pass
    need_w, need_h = min_size or (1, 1)
    if lavish and min_size:
        need_w, need_h = need_w + LAVISH_GROW, need_h + LAVISH_GROW
    elif lavish:
        need_w, need_h = 3, 3
    outdoor = "Outdoor" in flags
    walled = "Indoor" in flags or "Enclosed" in flags or "Secure" in flags
    building = not outdoor and room not in BUILDING_FREE and (walled or bool(items))
    if building and not items:
        need_w, need_h = max(need_w, MIN_BUILDING), max(need_h, MIN_BUILDING)
    if "Secure" in flags:
        notes.append("Secure: its own walls count as the fence (journal2, Yard)")
    if "AdjacentObject" in flags:
        notes.append("AdjacentObject: a counter object must touch the zone")
    best: tuple[int, int, int, list[Placement]] | None = None
    for width in range(max(need_w, 2) + (1 if items else 0), 40):
        packed = _pack(items, width - 1) if items else ([], 0)
        if packed is None:
            continue
        placed, used = packed
        height = max(need_h, used + 1 if items else need_h)
        area = width * height
        squareness = abs(width - height)
        if best is None or (area, squareness) < (best[0], best[1]):
            best = (area, squareness, width, placed)
            best_h = height
        if best is not None and width > best[2] + 6:
            break
    if best is None:
        raise KeyError(f"cannot fit the objects of {room}")
    _, _, width, placed = best
    return RoomPlan(
        room=room,
        variant=variant,
        w=width,
        h=best_h,
        door=width - 1,
        objects=tuple(placed),
        building=building,
        flags=flags,
        notes=tuple(notes),
    )


def _letter(name: str, taken: dict[str, str]) -> str:
    used = set(taken.values())
    for ch in name.upper() + "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        if ch not in used and ch not in "#D.":
            return ch
    return "?"


def render(plan: RoomPlan) -> list[str]:
    """ASCII picture: ``#`` wall, ``D`` door, a letter per object type, ``.`` free
    floor. A zone-only room (``building`` false) has no walls and no door."""
    ring = 1 if plan.building else 0
    outer_w, outer_h = plan.w + 2 * ring, plan.h + 2 * ring
    grid = [["#"] * outer_w for _ in range(outer_h)]
    for y in range(plan.h):
        for x in range(plan.w):
            grid[y + ring][x + ring] = "."
    if plan.building:
        grid[plan.h + 1][plan.door + 1] = "D"
    letters: dict[str, str] = {}
    for obj in plan.objects:
        w, h = size_of(obj.name)
        letter = letters.get(obj.name) or _letter(obj.name, letters)
        letters[obj.name] = letter
        for j in range(h):
            for i in range(w):
                grid[obj.dy + j + ring][obj.dx + i + ring] = letter
    return ["".join(row) for row in grid] + [
        f"{letter} = {name}" for name, letter in letters.items()
    ]


def stages(plan: RoomPlan, x: int, y: int) -> list[list[dict]]:
    """The ``ctl build`` job specs, in the order they must be sent and finished:
    1. the foundation (or nothing for a zone-only room), 2. the door,
    3. the room zone, 4. the objects (after the floor is built)."""
    out: list[list[dict]] = []
    ix, iy = x + 1, y + 1
    if plan.building:
        ow, oh = plan.outer
        out.append([{"tool": "foundation", "x": x, "y": y, "width": ow, "height": oh}])
        out.append(
            [{"tool": "place", "object": "Door", "x": ix + plan.door, "y": y + oh - 1}]
        )
        zone_x, zone_y = ix, iy
    else:
        zone_x, zone_y = x, y
    out.append(
        [
            {
                "tool": "room",
                "kind": plan.room,
                "x": zone_x,
                "y": zone_y,
                "width": plan.w,
                "height": plan.h,
            }
        ]
    )
    if plan.objects:
        out.append(
            [
                {
                    "tool": "place",
                    "object": o.name,
                    "x": zone_x + o.dx,
                    "y": zone_y + o.dy,
                }
                for o in plan.objects
            ]
        )
    return out


def constraints(room: str) -> dict:
    """What a room type needs, with every object's footprint (no layout)."""
    min_size, flags, required = ROOM_RULES[room]

    def info(name: str) -> dict:
        w, h = size_of(name)
        entry: dict = {"name": name, "w": w, "h": h}
        if SIZES.get(name, {}).get("wall"):
            entry["wall"] = True
        io = SIZES.get(name, {}).get("io")
        if io is not None:
            entry["indoor_outdoor"] = {
                0: "indoor only",
                1: "outdoor only",
                2: "either",
            }.get(io, io)
        if not _usable(name):
            entry["unplaceable"] = True
        return entry

    return {
        "room": room,
        "min_interior": list(min_size) if min_size else None,
        "flags": list(flags),
        "needs_building": not (
            "Outdoor" in flags
            or room in BUILDING_FREE
            or not ("Indoor" in flags or "Enclosed" in flags or "Secure" in flags)
            and not required
        ),
        "required": [
            {"one_of": [info(n) for n in (name, *alts)]} for name, alts in required
        ],
        "notes": [
            *([f"UNRELEASED: {UNRELEASED[room]}"] if room in UNRELEASED else []),
            "Interior cells are numbered from the top left (0,0); an object's anchor is its "
            "top left cell and it covers w x h cells (facing down).",
            "The door is in the bottom wall at one interior column; keep that column and the "
            "row above the wall free so people can walk in.",
            *(
                ["Secure: the room's own walls count as the fence (journal2, Yard)"]
                if "Secure" in flags
                else []
            ),
            *(
                ["AdjacentObject: a counter object must touch the zone"]
                if "AdjacentObject" in flags
                else []
            ),
            *(
                ["Outdoor: zone on open ground, no foundation"]
                if "Outdoor" in flags
                else []
            ),
        ],
    }


def check(
    room: str, width: int, height: int, objects: list[tuple[str, int, int]]
) -> list[str]:
    """Rule violations of a layout (size, bounds, overlaps, required objects); the door
    is not looked at. Empty list: it meets the requirements."""
    min_size, _flags, required = ROOM_RULES[room]
    errors: list[str] = []
    if min_size and (width < min_size[0] or height < min_size[1]):
        errors.append(f"interior {width}x{height} is below the minimum {min_size}")
    taken: dict[tuple[int, int], str] = {}
    for name, dx, dy in objects:
        if not _usable(name):
            errors.append(f"{name}: not a placeable object (see `ctl names objects`)")
            continue
        w, h = size_of(name)
        for j in range(h):
            for i in range(w):
                cell = (dx + i, dy + j)
                if not (0 <= cell[0] < width and 0 <= cell[1] < height):
                    errors.append(f"{name} at {dx},{dy} leaves the room")
                    break
                if cell in taken:
                    errors.append(f"{name} overlaps {taken[cell]} at {cell}")
                taken[cell] = name
    names = {n for n, _, _ in objects}
    for name, alts in required:
        if not names & {name, *alts}:
            errors.append(
                f"needs {name} (or {', '.join(alts)})" if alts else f"needs {name}"
            )
    return errors


def design(
    room: str,
    width: int,
    height: int,
    door: int,
    objects: list[tuple[str, int, int]],
    variant: str = "custom",
) -> tuple[RoomPlan, list[str]]:
    """A player's own layout as a :class:`RoomPlan`, with the rule violations found
    (empty = it meets the requirements): size, door, bounds, overlaps, required objects."""
    _min_size, flags, _required = ROOM_RULES[room]
    errors = check(room, width, height, objects)
    placements = tuple(Placement(n, x, y) for n, x, y in objects)
    if not 0 <= door < width:
        errors.append(f"door column {door} is outside the interior (0..{width - 1})")
    taken = {
        (x + i, y + j)
        for n, x, y in objects
        if _usable(n)
        for j in range(size_of(n)[1])
        for i in range(size_of(n)[0])
    }
    if (door, height - 1) in taken:
        errors.append(f"the cell inside the door ({door},{height - 1}) is blocked")
    building = constraints(room)["needs_building"]
    plan = RoomPlan(
        room=room,
        variant=variant,
        w=width,
        h=height,
        door=door,
        objects=placements,
        building=bool(building),
        flags=flags,
    )
    return plan, errors
