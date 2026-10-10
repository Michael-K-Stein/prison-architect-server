"""``bot ctl room``: the constraints of a room type, and building a designed room.

``room plan ROOM`` prints the rules and the footprint of every object the room needs (no
layout: the player designs it). ``room build ROOM X Y --size WxH --door COL --obj
Name:dx:dy ...`` checks the design against the rules, then builds it in stages. Without
any design option, or with ``--auto min|lavish``, it builds the bot's own plain layout
(:func:`~src.bot.rooms.plan_room`).
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Annotated

import typer

from src.bot import building, prefabs, rooms
from src.bot.control import call
from src.protocol.room_rules import ROOM_RULES

room_app = typer.Typer(help="Constraints of room types and building designed rooms.")

STAGE_TIMEOUT_MAX = 240
"""Seconds one wait may last (the blocking-call limit in TODO.md is 9 minutes)."""


def _fail(message: str, **extra: object) -> None:
    typer.echo(json.dumps({"error": message, **extra}, indent=1))
    raise typer.Exit(1)


def _kind(room: str) -> str:
    names = {n.lower(): n for n in ROOM_RULES}
    if room.lower() not in names:
        _fail(f"unknown room {room!r}; one of {', '.join(sorted(ROOM_RULES))}")
    return names[room.lower()]


def parse_size(text: str | None) -> tuple[int, int] | None:
    """``"6x5"`` -> ``(6, 5)``; ``None`` for no text; ``ValueError`` when malformed."""
    if text is None:
        return None
    parts = text.lower().split("x")
    if len(parts) != 2 or not all(p.isdigit() and int(p) > 0 for p in parts):
        raise ValueError(f"--size {text!r}: expected WxH, e.g. 6x5")
    return int(parts[0]), int(parts[1])


def parse_objects(items: list[str]) -> list[tuple]:
    """``["Bed:0:0", "Chair:1:2:up"]`` -> ``[("Bed", 0, 0), ("Chair", 1, 2, "up")]``;
    ``ValueError`` when malformed."""
    out: list[tuple] = []
    for text in items:
        parts = text.split(":")
        try:
            if len(parts) not in (3, 4) or not parts[0]:
                raise ValueError
            out.append((parts[0], int(parts[1]), int(parts[2]), *parts[3:]))
        except ValueError:
            raise ValueError(f"--obj {text!r}: expected Name:dx:dy[:facing]") from None
    return out


def _design(
    kind: str,
    size: str | None,
    door: int | None,
    objects: list[str],
    auto: str | None,
) -> tuple[rooms.RoomPlan, list[str]]:
    """The plan to build and the rule violations found in it."""
    try:
        if auto or not (size or objects or door is not None):
            return rooms.plan_room(kind, auto or "min"), []
        dims = parse_size(size)
        if dims is None or door is None or not objects:
            raise ValueError(
                "give --size WxH, --door COL and at least one --obj Name:dx:dy "
                "(or --auto min|lavish); `ctl room plan ROOM` lists the constraints"
            )
        return rooms.design(kind, dims[0], dims[1], door, parse_objects(objects))
    except (ValueError, KeyError) as exc:
        _fail(str(exc))
        raise  # unreachable: _fail exits


@room_app.command("plan")
def room_plan(
    room: Annotated[str, typer.Argument(help="Room type, e.g. Library (`ctl rules`).")],
) -> None:
    """The constraints of a room type and the footprint of every object it needs.

    Design the layout yourself; then check it with `ctl room build ROOM X Y --size
    WxH --door COL --obj Name:dx:dy ... --dry-run`.
    """
    typer.echo(json.dumps(rooms.constraints(_kind(room)), indent=1))


SWAPPABLE = ("StaffDoor", "Door")
"""Door types the swap may remove: only the construction door (or a plain Door) is touched."""


def swap_door(port: int, x: int, y: int, kind: str) -> str:
    """Replace the door on cell (x, y) with ``kind``: a client's ``ObjectRemoved`` deletes the
    old one on the host (journal2, the pump), then the new door is installed.

    Destructive, so it only removes a ``StaffDoor`` / ``Door`` standing exactly on that
    cell, and refuses when it cannot find exactly one. Returns what happened.
    """
    call("POST", "/refresh", {"seconds": 5}, port=port, interrupts=False)
    status, data = call(
        "GET", "/state/Save/Objects?depth=1", port=port, interrupts=False
    )
    if status >= 400:
        return f"cannot read the objects: {data}"
    found = [
        v
        for v in data.values()
        if isinstance(v, dict)
        and v.get("Type") in SWAPPABLE
        and int(v.get("Pos.x", -1)) == x
        and int(v.get("Pos.y", -1)) == y
    ]
    if any(v.get("Type") == kind for v in found):
        return "already has that door"
    if len(found) != 1:
        return f"expected exactly one StaffDoor/Door at {x},{y}, found {len(found)}: not touched"
    door = found[0]
    call(
        "POST",
        "/send",
        {"action": "ObjectRemoved", "args": [f"{door['Id.u']},{door['Id.i']}"]},
        port=port,
        interrupts=False,
    )
    call("POST", "/wait", {"seconds": 4}, port=port, interrupts=False)
    status, data = call(
        "POST",
        "/build",
        {"jobs": [{"tool": "place", "object": kind, "x": x, "y": y}]},
        port=port,
        interrupts=False,
    )
    return (
        f"{door['Type']} -> {kind}"
        if status < 400
        else f"removed, but placing {kind} failed: {data}"
    )


def _jobs_done(port: int) -> bool:
    status, data = call(
        "GET", "/state/ConstructionSystem/Jobs?depth=0", port=port, interrupts=False
    )
    return status < 400 and int(data.get("Size", 1)) == 0


def _say(port: int, payload: dict) -> None:
    """Print a command's result with any staff alerts that arrived meanwhile."""
    status, data = call("GET", "/alerts?new=1", port=port)
    if status < 400 and data.get("alerts"):
        payload = {**payload, "alerts_new": data["alerts"]}
    typer.echo(json.dumps(payload, indent=1))


def _area(port: int, x: int, y: int, w: int, h: int) -> list[str]:
    status, data = call(
        "GET", f"/area?x={x}&y={y}&w={w}&h={h}", port=port, interrupts=False
    )
    if status >= 400:
        raise RuntimeError(str(data))
    return data["rows"]


def wall_runs(rows: list[str], x: int, y: int) -> list[tuple[int, int, int, int]]:
    """Straight runs ``(x, y, w, h)`` of existing wall cells in ``rows`` (top left at
    ``x, y``): the walls a new foundation would turn into floor if it overlapped them."""
    cells = {
        (x + i, y + j) for j, r in enumerate(rows) for i, c in enumerate(r) if c == "W"
    }
    runs: list[tuple[int, int, int, int]] = []
    used: set[tuple[int, int]] = set()
    for cx, cy in sorted(cells, key=lambda c: (c[1], c[0])):
        if (cx, cy) in used:
            continue
        w = 1
        while (cx + w, cy) in cells and (cx + w, cy) not in used:
            w += 1
        h = 1
        while w == 1 and (cx, cy + h) in cells and (cx, cy + h) not in used:
            h += 1
        runs.append((cx, cy, w, h))
        used |= {(cx + i, cy + j) for i in range(w) for j in range(h)}
    return runs


def _wait_for(port: int, check: Callable[[], bool], timeout: float) -> bool:
    """Poll ``check()`` between 3 s waits, for at most ``timeout`` real seconds."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if check():
            return True
        call("POST", "/wait", {"seconds": 3}, port=port, interrupts=False)
    return check()


@room_app.command("clear")
def room_clear(
    ctx: typer.Context,
    x: Annotated[int, typer.Argument(help="Left cell.")],
    y: Annotated[int, typer.Argument(help="Top cell.")],
    width: Annotated[int, typer.Argument(help="Cells wide.")],
    height: Annotated[int, typer.Argument(help="Cells high.")],
    timeout: Annotated[
        int, typer.Option(help=f"Seconds per wait (at most {STAGE_TIMEOUT_MAX}).")
    ] = 120,
) -> None:
    """Clear a leftover building: bulldoze, DemolishWalls, ClearIndoorArea, each waited for.

    Use it on a half-built or unwanted foundation before building there again.
    """
    port = ctx.obj
    timeout = min(timeout, STAGE_TIMEOUT_MAX)
    steps = ("Demolish", "DemolishWalls", "ClearIndoorArea")
    try:
        call("POST", "/send", {"action": "GameSpeedChange", "args": ["10"]}, port=port)
        for step in steps:
            spec = {
                "tool": "demolish",
                "x": x,
                "y": y,
                "width": width,
                "height": height,
            }
            status, data = call(
                "POST", "/build", {"jobs": [{**spec, "material": step}]}, port=port
            )
            if status >= 400:
                _fail(f"{step} refused", detail=data)
            _wait_for(
                port,
                lambda: (
                    not any(
                        set(r) & set("WFB") for r in _area(port, x, y, width, height)
                    )
                ),
                timeout if step != "Demolish" else min(timeout, 60),
            )
        rows = _area(port, x, y, width, height)
    except OSError as exc:
        _fail(f"no control server: {exc}")
    left = sum(len(set(r) & set("WFB")) > 0 for r in rows)
    _say(port, {"cleared": left == 0, "rows_with_leftovers": left, "area": rows})


@room_app.command("build")
def room_build(
    ctx: typer.Context,
    room: Annotated[str, typer.Argument(help="Room type, e.g. Library.")],
    x: Annotated[int, typer.Argument(help="Top left cell of the building.")],
    y: Annotated[int, typer.Argument(help="Top left cell.")],
    size: Annotated[
        str | None,
        typer.Option(help="Interior size WxH (cells inside the walls), e.g. 6x5."),
    ] = None,
    door: Annotated[
        int | None, typer.Option(help="Interior column of the door in the bottom wall.")
    ] = None,
    obj: Annotated[
        list[str] | None,
        typer.Option(
            "--obj",
            help="Name:dx:dy[:facing], the top left cell and up/down/left/right (repeat).",
        ),
    ] = None,
    dry_run: Annotated[
        bool, typer.Option(help="Only check and show the design.")
    ] = False,
    auto: Annotated[
        str | None, typer.Option(help="The bot's own plain layout: min or lavish.")
    ] = None,
    timeout: Annotated[
        int, typer.Option(help=f"Seconds per wait (at most {STAGE_TIMEOUT_MAX}).")
    ] = 150,
) -> None:
    """Build a room from your design (--size, --door, --obj) or the bot's (--auto).

    Rooms may share a wall: put the next building's edge on a neighbour's wall
    column. The design is checked against the game's rules first and refused with
    the problems listed. Then: foundation, wait for the floor, door, wait for the walls,
    zone, objects. Blocks for minutes; the area must be empty ground (objects, cables
    and pipes underneath are not checked: look at `ctl state Save Objects` first).
    """
    port = ctx.obj
    timeout = min(timeout, STAGE_TIMEOUT_MAX)
    plan, errors = _design(_kind(room), size, door, obj or [], auto)
    picture = rooms.render(plan)
    if errors:
        typer.echo(json.dumps({"refused": errors, "picture": picture}, indent=1))
        raise typer.Exit(1)
    if dry_run:
        typer.echo(json.dumps({"ok": True, "picture": picture}, indent=1))
        return
    outer_w, outer_h = plan.outer if plan.building else (plan.w, plan.h)
    done: list[str] = []
    warnings: list[str] = []
    try:
        ring = 1 if plan.building else 0
        rows = _area(port, x, y, outer_w, outer_h)
        # the new walls may be an existing neighbour's wall (rooms share walls); the
        # inside of the room must be empty ground
        shared = wall_runs(rows, x, y)
        inside = [r[ring : outer_w - ring] for r in rows[ring : outer_h - ring]]
        if any(set(r) & set("WFB") for r in inside) or any(
            set(c) & set("FB") for r in rows for c in r
        ):
            _fail(
                "the area has floor/frames, or walls inside the room; pick empty "
                "ground (a neighbour's wall on the edge is fine) or `ctl room clear`"
            )
        call("POST", "/send", {"action": "GameSpeedChange", "args": ["10"]}, port=port)
        for index, jobs in enumerate(rooms.stages(plan, x, y)):
            kind = jobs[0]["tool"]
            status, data = call("POST", "/build", {"jobs": jobs}, port=port)
            if status >= 400:
                _fail(f"stage {kind} refused", detail=data, done=done)
            done.append(kind)
            if kind == "foundation":
                # only wait for the job to start: its middle stalls until a door exists
                _wait_for(
                    port,
                    lambda: any(
                        set(r) & set("BF") for r in _area(port, x, y, outer_w, outer_h)
                    ),
                    min(timeout, 60),
                )
            elif kind == "place" and plan.building and index == 1:
                floored = _wait_for(
                    port,
                    lambda: all(
                        set(r) <= {"F"}
                        for r in _area(port, x + 1, y + 1, plan.w, plan.h)
                    ),
                    timeout,
                )
                if not floored:
                    warnings.append("the floor was not finished in time")
                for sx, sy, sw, sh in shared:  # a foundation floors a wall it overlaps
                    call(
                        "POST",
                        "/build",
                        {
                            "jobs": [
                                {
                                    "tool": "wall",
                                    "x": sx,
                                    "y": sy,
                                    "width": sw,
                                    "height": sh,
                                }
                            ]
                        },
                        port=port,
                    )
                if shared:
                    done.append(f"re-walled {len(shared)} shared wall run(s)")
                ok = _wait_for(
                    port,
                    lambda: "W" in "".join(_area(port, x, y, outer_w, 1)),
                    timeout,
                )
                if not ok:
                    warnings.append("the walls did not go up (is the door usable?)")
        final = rooms.door_kind(plan.room)
        if plan.building and rooms.needs_swap(plan.room):
            _wait_for(port, lambda: _jobs_done(port), timeout)
            done.append(
                "door: " + swap_door(port, x + 1 + plan.door, y + plan.h + 1, final)
            )
    except OSError as exc:
        _fail(f"no control server: {exc}")
    _say(
        port,
        {
            "built": plan.room,
            "at": [x, y],
            "interior": [plan.w, plan.h],
            "stages": done,
            "warnings": warnings,
            "next": "`ctl refresh`, then check `problems` for this room",
        },
    )


door_app = typer.Typer(
    help="Swap a door for another type (destructive: removes the old one)."
)


@door_app.command("swap")
def door_swap(
    ctx: typer.Context,
    x: Annotated[int, typer.Argument(help="Door cell x.")],
    y: Annotated[int, typer.Argument(help="Door cell y.")],
    kind: Annotated[
        str, typer.Argument(help="JailDoor, StaffDoor, SecureDoor, SolitaryDoor, Door.")
    ],
) -> None:
    """Replace the StaffDoor / Door on a cell with another door type (see `rooms.DOOR_KINDS`)."""
    if kind not in rooms.SIZES or "Door" not in kind:
        _fail(f"{kind!r} is not a door type")
    _say(ctx.obj, {"cell": [x, y], "result": swap_door(ctx.obj, x, y, kind)})


building_app = typer.Typer(
    help="Plan and build a whole building: one foundation, then internal walls, rooms."
)


def _load_building(path: str) -> building.Building:
    try:
        with open(path, encoding="utf-8") as fh:
            spec = json.load(fh)
        return building.parse(spec)
    except (OSError, ValueError) as exc:
        _fail(f"{path}: {exc}")
        raise  # unreachable: _fail exits


@building_app.command("plan")
def building_plan(
    file: Annotated[
        str, typer.Argument(help="Building spec (JSON), see src/bot/building.py.")
    ],
) -> None:
    """Check a building spec against the rules and show it (nothing is built)."""
    b = _load_building(file)
    errors = building.validate(b)
    typer.echo(
        json.dumps(
            {"ok": not errors, "problems": errors, "picture": building.render(b)},
            indent=1,
        )
    )
    if errors:
        raise typer.Exit(1)


def run_building(
    port: int, b: building.Building, timeout: int, resume: bool = False
) -> None:
    """Build a validated building: stages in order with waits, door swaps, then print.

    ``resume``: the foundation is already there (a build that was cut off): skip that stage."""
    timeout = min(timeout, STAGE_TIMEOUT_MAX)
    done: list[str] = []
    warnings: list[str] = []
    inner_walls = building.walls(b) - {
        (x, y)
        for x in range(b.width)
        for y in range(b.height)
        if x in (0, b.width - 1) or y in (0, b.height - 1)
    }

    def read() -> list[str]:
        return _area(port, b.x, b.y, b.width, b.height)

    try:
        started = any(set(r) & set("WFB") for r in read())
        if started and not resume:
            _fail("the area has walls/floor/frames already; use `ctl room clear` first")
        call("POST", "/send", {"action": "GameSpeedChange", "args": ["10"]}, port=port)
        for name, jobs in building.stages(b):
            if name == "foundation" and resume and started:
                done.append("foundation (already there)")
                continue
            status, data = call("POST", "/build", {"jobs": jobs}, port=port)
            if status >= 400:
                _fail(f"stage {name} refused", detail=data, done=done)
            done.append(name)
            if name == "foundation":
                # only wait for the job to start: its middle stalls until a door exists
                _wait_for(
                    port,
                    lambda: any(set(r) & set("BF") for r in read()),
                    min(timeout, 60),
                )
            elif name == "entrances":
                floored = _wait_for(
                    port,
                    lambda: all(set(r[1:-1]) <= {"F"} for r in read()[1:-1]),
                    timeout,
                )
                if not floored:
                    warnings.append("the floor was not finished in time")
                if not _wait_for(port, lambda: "W" in "".join(read()[0]), timeout):
                    warnings.append(
                        "the outer walls did not go up (is an entrance usable?)"
                    )
            elif name == "walls":

                def built() -> bool:
                    rows = read()
                    return all(rows[y][x] == "W" for x, y in inner_walls)

                if not _wait_for(port, built, timeout):
                    warnings.append("some internal walls were not built in time")
        swaps = building.final_doors(b)
        if swaps:
            _wait_for(port, lambda: _jobs_done(port), timeout)
            for sx, sy, kind in swaps:
                done.append(f"door {sx},{sy}: " + swap_door(port, sx, sy, kind))
    except OSError as exc:
        _fail(f"no control server: {exc}")
    _say(
        port,
        {
            "built": [r.type for r in b.rooms],
            "at": [b.x, b.y],
            "stages": done,
            "warnings": warnings,
            "next": "`ctl refresh`, then check `problems` for these rooms",
        },
    )


@building_app.command("build")
def building_build(
    ctx: typer.Context,
    file: Annotated[str, typer.Argument(help="Building spec (JSON).")],
    timeout: Annotated[
        int, typer.Option(help=f"Seconds per wait (at most {STAGE_TIMEOUT_MAX}).")
    ] = 150,
    resume: Annotated[
        bool,
        typer.Option(
            help="Continue a cut-off build: skip the foundation if it is there."
        ),
    ] = False,
) -> None:
    """Build a planned building: foundation, entrance doors, internal walls, internal
    doors, room zones, objects, waiting for each stage. Blocks for minutes.

    The whole area must be empty ground; the plan is validated first.
    """
    b = _load_building(file)
    errors = building.validate(b)
    if errors:
        typer.echo(
            json.dumps({"refused": errors, "picture": building.render(b)}, indent=1)
        )
        raise typer.Exit(1)
    run_building(ctx.obj, b, timeout, resume)


@room_app.command("prefabs")
def room_prefabs(
    room: Annotated[str | None, typer.Argument(help="Room type, or all.")] = None,
) -> None:
    """The game's own room layouts (prefabs), largest first: name, outer size, room type."""
    kind = _kind(room) if room else None
    out = [
        {
            "prefab": name,
            "room": prefabs.PREFABS[name]["room"],
            "outer": [prefabs.PREFABS[name]["w"], prefabs.PREFABS[name]["h"]],
            "objects": len(prefabs.PREFABS[name]["objects"]),
        }
        for name in prefabs.for_room(kind)
    ]
    typer.echo(json.dumps(out, indent=1))


@room_app.command("prefab")
def room_prefab(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Prefab name (`ctl room prefabs`).")],
    x: Annotated[int, typer.Argument(help="Top left cell of the building.")],
    y: Annotated[int, typer.Argument(help="Top left cell.")],
    dry_run: Annotated[bool, typer.Option(help="Only check and show it.")] = False,
    timeout: Annotated[
        int, typer.Option(help=f"Seconds per wait (at most {STAGE_TIMEOUT_MAX}).")
    ] = 150,
    resume: Annotated[
        bool,
        typer.Option(
            help="Continue a cut-off build: skip the foundation if it is there."
        ),
    ] = False,
) -> None:
    """Build the game's own layout for a room (a standard / lavish design with the right
    facing and doors): it is checked against the rules like any building first."""
    if name not in prefabs.PREFABS:
        _fail(f"unknown prefab {name!r}; see `ctl room prefabs`")
    try:
        b = building.parse(prefabs.to_spec(name, x, y))
    except ValueError as exc:
        _fail(str(exc))
        raise
    errors = building.validate(b)
    if errors or dry_run:
        typer.echo(
            json.dumps(
                {"ok": not errors, "problems": errors, "picture": building.render(b)},
                indent=1,
            )
        )
        raise typer.Exit(1 if errors else 0)
    run_building(ctx.obj, b, timeout, resume)
