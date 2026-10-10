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

from src.bot import rooms
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


def parse_objects(items: list[str]) -> list[tuple[str, int, int]]:
    """``["Bed:0:0", ...]`` -> ``[("Bed", 0, 0), ...]``; ``ValueError`` when malformed."""
    out = []
    for text in items:
        name, _, rest = text.partition(":")
        dx, _, dy = rest.partition(":")
        try:
            out.append((name, int(dx), int(dy)))
        except ValueError:
            raise ValueError(f"--obj {text!r}: expected Name:dx:dy") from None
        if not name:
            raise ValueError(f"--obj {text!r}: expected Name:dx:dy")
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


def _area(port: int, x: int, y: int, w: int, h: int) -> list[str]:
    status, data = call("GET", f"/area?x={x}&y={y}&w={w}&h={h}", port=port)
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
        call("POST", "/wait", {"seconds": 3}, port=port)
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
    typer.echo(
        json.dumps({"cleared": left == 0, "rows_with_leftovers": left, "area": rows})
    )


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
        typer.Option("--obj", help="Name:dx:dy, the object's top left cell (repeat)."),
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
                ok = _wait_for(
                    port,
                    lambda: all(
                        set(r) <= {"F"}
                        for r in _area(port, x + 1, y + 1, plan.w, plan.h)
                    ),
                    timeout,
                )
                if not ok:
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
            elif kind == "place" and plan.building and index == 1:
                ok = _wait_for(
                    port,
                    lambda: "W" in "".join(_area(port, x, y, outer_w, 1)),
                    timeout,
                )
                if not ok:
                    warnings.append("the walls did not go up (is the door usable?)")
    except OSError as exc:
        _fail(f"no control server: {exc}")
    typer.echo(
        json.dumps(
            {
                "built": plan.room,
                "at": [x, y],
                "interior": [plan.w, plan.h],
                "stages": done,
                "warnings": warnings,
                "next": "`ctl refresh`, then check `problems` for this room",
            },
            indent=1,
        )
    )
