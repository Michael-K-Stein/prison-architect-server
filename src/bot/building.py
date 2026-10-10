"""A whole building with several rooms, planned first and built in the right order.

Real builders plan every room, lay ONE foundation for the whole building, and only then
put up the internal walls. A spec (JSON) gives the building's outer rectangle and its
rooms; :func:`validate` checks it (each room against the game's rules, no overlaps, doors
on a wall, every room reachable from an entrance) and :func:`stages` returns the build
jobs in order::

    {"x": 20, "y": 90, "width": 12, "height": 8,        # outer size, walls included
     "entrances": [[6, 7]],                              # door cells on the outer wall
     "rooms": [
       {"type": "Cell", "x": 1, "y": 1, "w": 3, "h": 4,  # interior, building coordinates
        "door": [2, 5],                                  # a cell of the room's wall ring
        "objects": [["Bed", 0, 0], ["Toilet", 1, 0]]},    # top left cell inside the room
       ...]}

All coordinates inside the spec are relative to the building's top left cell (0, 0); a
room's walls are the ring of cells around its interior, so two rooms may share a wall
and the cells between rooms that belong to no room are corridors.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from src.bot import rooms
from src.protocol.room_rules import ROOM_RULES

Cell = tuple[int, int]


@dataclass(frozen=True)
class RoomSpec:
    type: str
    x: int
    y: int
    w: int
    h: int
    door: Cell
    objects: tuple[tuple[str, int, int], ...]

    def interior(self) -> set[Cell]:
        return {(self.x + i, self.y + j) for i in range(self.w) for j in range(self.h)}

    def ring(self) -> set[Cell]:
        """The wall cells around the interior, corners included."""
        return {
            (x, y)
            for x in range(self.x - 1, self.x + self.w + 1)
            for y in range(self.y - 1, self.y + self.h + 1)
        } - self.interior()


@dataclass(frozen=True)
class Building:
    x: int
    y: int
    width: int
    height: int
    entrances: tuple[Cell, ...]
    rooms: tuple[RoomSpec, ...]


def parse(spec: dict) -> Building:
    """The typed building from a spec dict; ``ValueError`` for a malformed one."""
    try:
        rooms_ = tuple(
            RoomSpec(
                type=str(r["type"]),
                x=int(r["x"]),
                y=int(r["y"]),
                w=int(r["w"]),
                h=int(r["h"]),
                door=(int(r["door"][0]), int(r["door"][1])),
                objects=tuple(
                    (str(n), int(a), int(b)) for n, a, b in r.get("objects", [])
                ),
            )
            for r in spec["rooms"]
        )
        return Building(
            int(spec["x"]),
            int(spec["y"]),
            int(spec["width"]),
            int(spec["height"]),
            tuple((int(a), int(b)) for a, b in spec.get("entrances", [])),
            rooms_,
        )
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        raise ValueError(f"malformed building spec: {exc!r}") from None


def _outer_ring(b: Building) -> set[Cell]:
    return {
        (x, y)
        for x in range(b.width)
        for y in range(b.height)
        if x in (0, b.width - 1) or y in (0, b.height - 1)
    }


def walls(b: Building) -> set[Cell]:
    """Every wall cell: the outer ring and each room's ring, minus the doors."""
    cells = _outer_ring(b)
    for r in b.rooms:
        cells |= r.ring()
    return cells - doors(b)


def doors(b: Building) -> set[Cell]:
    return set(b.entrances) | {r.door for r in b.rooms}


def validate(b: Building) -> list[str]:
    """Problems of the plan (empty list: it can be built and every room works)."""
    errors: list[str] = []
    if b.width < 3 or b.height < 3:
        errors.append("the building is smaller than 3x3")
    inner = {(x, y) for x in range(1, b.width - 1) for y in range(1, b.height - 1)}
    outer = _outer_ring(b)
    for cell in b.entrances:
        if cell not in outer or cell in {
            (0, 0),
            (b.width - 1, 0),
            (0, b.height - 1),
            (b.width - 1, b.height - 1),
        }:
            errors.append(f"entrance {cell} must be on the outer wall, not a corner")
    if not b.entrances:
        errors.append("give at least one entrance on the outer wall")
    interiors: dict[Cell, int] = {}
    for n, r in enumerate(b.rooms):
        label = f"room {n} ({r.type} at {r.x},{r.y})"
        if r.type not in ROOM_RULES:
            errors.append(f"{label}: unknown room type")
            continue
        if not r.interior() <= inner:
            errors.append(f"{label}: interior leaves the building's inside")
        for cell in r.interior():
            if cell in interiors:
                errors.append(f"{label}: overlaps room {interiors[cell]}")
                break
            interiors[cell] = n
        for e in rooms.check(r.type, r.w, r.h, list(r.objects)):
            errors.append(f"{label}: {e}")
        if r.door not in r.ring() or r.door in _corners(r):
            errors.append(
                f"{label}: door {r.door} must be on its wall ring, not a corner"
            )
        elif _inside_of(r, r.door) in _object_cells(r):
            errors.append(f"{label}: an object blocks the cell inside the door")
    for n, r in enumerate(b.rooms):
        for m, other in enumerate(b.rooms):
            if n != m and r.ring() & other.interior():
                errors.append(f"room {n} walls run through room {m}")
                break
    if not errors:
        errors.extend(_unreachable(b))
    return errors


def _object_cells(r: RoomSpec) -> set[Cell]:
    """Building coordinates of every cell an object of the room covers."""
    return {
        (r.x + dx + i, r.y + dy + j)
        for name, dx, dy in r.objects
        for i in range(rooms.size_of(name)[0])
        for j in range(rooms.size_of(name)[1])
    }


def _corners(r: RoomSpec) -> set[Cell]:
    return {
        (r.x - 1, r.y - 1),
        (r.x + r.w, r.y - 1),
        (r.x - 1, r.y + r.h),
        (r.x + r.w, r.y + r.h),
    }


def _inside_of(r: RoomSpec, door: Cell) -> Cell:
    """The interior cell next to a door on the room's ring."""
    x, y = door
    x = min(max(x, r.x), r.x + r.w - 1)
    y = min(max(y, r.y), r.y + r.h - 1)
    return x, y


def _unreachable(b: Building) -> list[str]:
    """Rooms nobody can walk into from an entrance (doors open a wall cell)."""
    blocked = walls(b)
    start = set()
    for x, y in b.entrances:
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 1 <= nx < b.width - 1 and 1 <= ny < b.height - 1:
                start.add((nx, ny))
    seen: set[Cell] = set(start)
    queue = deque(start)
    while queue:
        x, y = queue.popleft()
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if (
                (nx, ny) not in seen
                and 0 <= nx < b.width
                and 0 <= ny < b.height
                and (nx, ny) not in blocked
            ):
                seen.add((nx, ny))
                queue.append((nx, ny))
    out = []
    for n, r in enumerate(b.rooms):
        if not r.interior() & seen:
            out.append(f"room {n} ({r.type}) cannot be reached from an entrance")
    return out


def _runs(cells: set[Cell]) -> list[tuple[int, int, int, int]]:
    """Cells as straight ``(x, y, w, h)`` runs (horizontal first, then vertical)."""
    left = set(cells)
    out = []
    for cell in sorted(cells, key=lambda c: (c[1], c[0])):
        if cell not in left:
            continue
        x, y = cell
        w = 1
        while (x + w, y) in left:
            w += 1
        if w > 1:
            out.append((x, y, w, 1))
            left -= {(x + i, y) for i in range(w)}
            continue
        h = 1
        while (x, y + h) in left:
            h += 1
        out.append((x, y, 1, h))
        left -= {(x, y + j) for j in range(h)}
    return out


def render(b: Building) -> list[str]:
    """ASCII picture: ``#`` wall, ``D`` door, objects by letter, ``.`` floor."""
    grid = [["." for _ in range(b.width)] for _ in range(b.height)]
    for x, y in walls(b):
        if 0 <= x < b.width and 0 <= y < b.height:
            grid[y][x] = "#"
    for x, y in doors(b):
        grid[y][x] = "D"
    letters: dict[str, str] = {}
    for r in b.rooms:
        for name, dx, dy in r.objects:
            letter = letters.get(name) or rooms._letter(name, letters)
            letters[name] = letter
            w, h = rooms.size_of(name)
            for j in range(h):
                for i in range(w):
                    grid[r.y + dy + j][r.x + dx + i] = letter
    return ["".join(row) for row in grid] + [f"{v} = {k}" for k, v in letters.items()]


def stages(b: Building) -> list[tuple[str, list[dict]]]:
    """``(name, jobs)`` in build order: foundation, entrance doors, internal walls,
    internal doors, room zones, objects. The caller waits for each to finish."""
    x0, y0 = b.x, b.y
    out: list[tuple[str, list[dict]]] = [
        (
            "foundation",
            [
                {
                    "tool": "foundation",
                    "x": x0,
                    "y": y0,
                    "width": b.width,
                    "height": b.height,
                }
            ],
        ),
        (
            "entrances",
            [
                {"tool": "place", "object": "Door", "x": x0 + x, "y": y0 + y}
                for x, y in b.entrances
            ],
        ),
    ]
    inner_walls = walls(b) - _outer_ring(b)
    out.append(
        (
            "walls",
            [
                {"tool": "wall", "x": x0 + x, "y": y0 + y, "width": w, "height": h}
                for x, y, w, h in _runs(inner_walls)
            ],
        )
    )
    internal = {r.door for r in b.rooms} - set(b.entrances)
    out.append(
        (
            "doors",
            [
                {"tool": "place", "object": "Door", "x": x0 + x, "y": y0 + y}
                for x, y in sorted(internal)
            ],
        )
    )
    out.append(
        (
            "rooms",
            [
                {
                    "tool": "room",
                    "kind": r.type,
                    "x": x0 + r.x,
                    "y": y0 + r.y,
                    "width": r.w,
                    "height": r.h,
                }
                for r in b.rooms
            ],
        )
    )
    out.append(
        (
            "objects",
            [
                {
                    "tool": "place",
                    "object": name,
                    "x": x0 + r.x + dx,
                    "y": y0 + r.y + dy,
                }
                for r in b.rooms
                for name, dx, dy in r.objects
            ],
        )
    )
    return [s for s in out if s[1]]
