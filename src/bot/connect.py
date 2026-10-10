"""Plan the cables / pipes that connect unpowered or unwatered objects to a fed network.

``plan`` finds every consumer that is not served (an electrical object with
``Powered`` false, or a water appliance with no pipe on its cell), and for each one the
shortest run of new cells from it to the nearest cell of a *fed* network (electricity:
``ac``, a Transformer's output side; water: a network with a pump). Runs found earlier
count as fed for the later ones, so neighbours share a trunk. A run never enters the
footprint of a source or converter, and a cable never touches the raw green network (that
would short it with the generators, see :mod:`src.bot.network`). A cable ends on a cell
next to the consumer; a pipe ends ON a cell the appliance covers.
"""

from __future__ import annotations

from collections import deque
from typing import Any

from src.bot import network
from src.bot.network import Cell

LINE_OBJECT = {"electricity": "ElectricalCable", "water": "PipeSmall"}
LARGE_PIPE = "PipeLarge"
LARGE_TYPE = 1
"""``PipeType`` of a PipeLarge cell in ``Save Water`` (PipeSmall is 2)."""
SMALL_MAX = 12
"""Most PipeSmall cells in a row between a PipeLarge and an appliance. The game says a small
pipe "can run for a limited length before the pressure becomes too low" (user: a toilet 47
small cells from the main got no water); the real limit is not in the game data, so this is
a cautious guess: lay PipeLarge for the long part and PipeSmall only at the end."""
FED_KIND = {"electricity": "ac", "water": "pumped"}
RAW_KINDS = {"raw-green", "short-circuit"}
SOLID = frozenset(
    {
        "SolarPanels",
        "WindTurbine",
        "SolarWindHybrid",
        "Transformer",
        "PowerStation",
        "Battery",
        "Capacitor",
        "PowerExportMeter",
        "WaterPumpStation",
        "WaterBoiler",
    }
)
"""Objects a new cable or pipe never runs through."""
NEIGHBOURS = ((1, 0), (-1, 0), (0, 1), (0, -1))


def _runs(path: list[Cell]) -> list[tuple[int, int, int, int]]:
    """A path of adjacent cells as straight ``(x, y, w, h)`` runs."""
    runs: list[tuple[int, int, int, int]] = []
    i = 0
    while i < len(path):
        j = i
        if i + 1 < len(path):
            dx, dy = path[i + 1][0] - path[i][0], path[i + 1][1] - path[i][1]
            while j + 1 < len(path) and (
                path[j + 1][0] - path[j][0],
                path[j + 1][1] - path[j][1],
            ) == (dx, dy):
                j += 1
        (x0, y0), (x1, y1) = path[i], path[j]
        runs.append((min(x0, x1), min(y0, y1), abs(x1 - x0) + 1, abs(y1 - y0) + 1))
        i = j + 1 if j > i else i + 1
    return runs


def plan(
    utility_name: str,
    cells: set[Cell],
    objects: list[dict[str, Any]],
    width: int,
    height: int,
    kinds: dict[Cell, int] | None = None,
    small_max: int = SMALL_MAX,
) -> dict[str, Any]:
    """The runs that connect every unserved consumer: ``{"targets", "jobs", "skipped"}``.

    Water: ``kinds`` maps pipe cells to their ``PipeType``; a pipe run is PipeLarge except
    for its last ``small_max`` cells (PipeSmall), and it only joins a small pipe that
    still has pressure left (see :data:`SMALL_MAX`).
    """
    utility = network.UTILITIES[utility_name]
    report = network.analyze(cells, objects, utility, with_cells=True)
    fed: set[Cell] = set()
    raw: set[Cell] = set()
    for net in report["networks"]:
        if net["kind"] == FED_KIND[utility_name]:
            fed.update(map(tuple, net["cell_list"]))
        elif net["kind"] in RAW_KINDS:
            raw.update(map(tuple, net["cell_list"]))
    kinds = kinds or {}
    small_dist = _small_distances(fed, kinds) if utility_name == "water" else {}
    placed = [(o, network.footprint(o)) for o in objects if "Pos.x" in o]
    blocked: set[Cell] = set()
    for o, cover in placed:
        if o.get("Type") in SOLID:
            blocked |= cover
    near_raw = raw | {(x + dx, y + dy) for x, y in raw for dx, dy in NEIGHBOURS}
    unfed_reach = {(x + dx, y + dy) for x, y in fed for dx, dy in NEIGHBOURS} | fed
    targets = []
    for o, cover in placed:
        kind = o.get("Type")
        if kind in SOLID or not utility.consumer(o):
            continue
        if utility_name == "electricity":
            if o.get("Powered") or cover & unfed_reach:
                continue
        elif cover & fed:
            if kinds and min(small_dist.get(c, 0) for c in cover & fed) > small_max:
                targets.append((o, cover))  # piped, but too far from a large pipe
            continue
        targets.append((o, cover))
    targets.sort(key=lambda t: (t[0].get("Pos.y", 0), t[0].get("Pos.x", 0)))
    jobs: list[dict[str, Any]] = []
    skipped: list[str] = []
    for o, cover in targets:
        label = f"{o.get('Type')} #{o.get('Id.i')} at {o.get('Pos.x')},{o.get('Pos.y')}"
        if cover & (unfed_reach if utility_name == "electricity" else fed):
            if not (
                utility_name == "water"
                and kinds
                and min(small_dist.get(c, 0) for c in cover & fed) > small_max
            ):
                continue  # an earlier run already serves it
            boost = _boost(
                cover, fed, kinds, small_dist, small_max, blocked, width, height
            )
            if boost is None:
                skipped.append(f"{label}: no free route for a large pipe nearby")
                continue
            for x, y, w, h in _runs(boost):
                jobs.append(
                    {
                        "tool": "line",
                        "object": LARGE_PIPE,
                        "x": x,
                        "y": y,
                        "width": w,
                        "height": h,
                    }
                )
            fed.update(boost)
            kinds.update({c: LARGE_TYPE for c in boost})
            small_dist.clear()
            small_dist.update(_small_distances(fed, kinds))
            continue
        if utility_name == "water":
            starts = {c for c in cover if c not in blocked}
        else:
            starts = {
                (x + dx, y + dy) for x, y in cover for dx, dy in NEIGHBOURS
            } - cover
        starts = {
            c
            for c in starts
            if 0 <= c[0] < width and 0 <= c[1] < height and c not in blocked
        }
        if utility_name == "electricity":
            starts -= near_raw
        goals = fed
        if utility_name == "water" and kinds:
            goals = {c for c in fed if small_dist.get(c, 0) < small_max}
        path = _shortest(
            starts,
            goals,
            blocked,
            near_raw if utility_name == "electricity" else set(),
            width,
            height,
        )
        if path is None:
            skipped.append(f"{label}: no free route to a fed network")
            continue
        parts = [(LINE_OBJECT[utility_name], path)]
        if utility_name == "water" and kinds:
            parts, path = _split_pipes(
                path,
                goals,
                small_dist,
                small_max,
                starts,
                fed,
                kinds,
                blocked,
                width,
                height,
            )
            if not parts:
                skipped.append(f"{label}: no free route to a fed network")
                continue
        fed.update(path)
        unfed_reach.update(path)
        unfed_reach.update((x + dx, y + dy) for x, y in path for dx, dy in NEIGHBOURS)
        for object_name, cells_ in parts:
            for x, y, w, h in _runs(cells_):
                jobs.append(
                    {
                        "tool": "line",
                        "object": object_name,
                        "x": x,
                        "y": y,
                        "width": w,
                        "height": h,
                    }
                )
    return {
        "utility": utility_name,
        "targets": len(targets),
        "jobs": jobs,
        "skipped": skipped,
    }


def _boost(
    cover: set[Cell],
    fed: set[Cell],
    kinds: dict[Cell, int],
    small_dist: dict[Cell, int],
    small_max: int,
    blocked: set[Cell],
    width: int,
    height: int,
) -> list[Cell] | None:
    """New PipeLarge cells that bring pressure to within ``small_max`` small cells of an
    appliance that is already piped but far from any large pipe: a path from a free cell
    beside the appliance's own pipe chain to the nearest PipeLarge cell."""
    chain: dict[Cell, int] = {c: 0 for c in cover & fed}
    queue = deque(chain)
    while queue:
        cell = queue.popleft()
        if chain[cell] >= small_max:
            continue
        for dx, dy in NEIGHBOURS:
            nxt = (cell[0] + dx, cell[1] + dy)
            if nxt in fed and nxt not in chain and kinds.get(nxt) != LARGE_TYPE:
                chain[nxt] = chain[cell] + 1
                queue.append(nxt)
    starts = {
        (x + dx, y + dy)
        for x, y in chain
        for dx, dy in NEIGHBOURS
        if (x + dx, y + dy) not in fed
        and 0 <= x + dx < width
        and 0 <= y + dy < height
        and (x + dx, y + dy) not in blocked
    }
    large = {c for c in fed if kinds.get(c) == LARGE_TYPE}
    path = _shortest(starts, large, blocked | fed, set(), width, height)
    return path


def _small_distances(fed: set[Cell], kinds: dict[Cell, int]) -> dict[Cell, int]:
    """For every cell of a fed pipe network: how many PipeSmall cells lie between it and
    the nearest PipeLarge cell (0 for a large cell)."""
    dist: dict[Cell, int] = {}
    queue: deque[Cell] = deque()
    for cell in fed:
        if kinds.get(cell) == LARGE_TYPE:
            dist[cell] = 0
            queue.append(cell)
    while queue:
        cell = queue.popleft()
        for dx, dy in NEIGHBOURS:
            nxt = (cell[0] + dx, cell[1] + dy)
            if nxt in fed and nxt not in dist:
                dist[nxt] = dist[cell] + (0 if kinds.get(nxt) == LARGE_TYPE else 1)
                queue.append(nxt)
    return dist


def _split_pipes(
    path: list[Cell],
    goals: set[Cell],
    small_dist: dict[Cell, int],
    small_max: int,
    starts: set[Cell],
    fed: set[Cell],
    kinds: dict[Cell, int],
    blocked: set[Cell],
    width: int,
    height: int,
) -> tuple[list[tuple[str, list[Cell]]], list[Cell]]:
    """Split a pipe path (target end first) into PipeSmall (the last ``small_max`` cells
    counted from the pressure source) and PipeLarge (the rest). A path that needs a large
    part must join a PipeLarge cell, so it is searched again against those only."""

    def attach(p: list[Cell], from_goals: set[Cell]) -> int:
        last = p[-1]
        near = [
            g
            for g in (last, *((last[0] + dx, last[1] + dy) for dx, dy in NEIGHBOURS))
            if g in from_goals
        ]
        return min((small_dist.get(g, 0) for g in near), default=0)

    allowed = max(0, small_max - attach(path, goals))
    if len(path) > allowed:
        large_goals = {c for c in fed if kinds.get(c) == LARGE_TYPE}
        again = _shortest(starts, large_goals, blocked, set(), width, height)
        if again is None:
            return [], []
        path = again
        allowed = small_max
    small, large = path[:allowed], path[allowed:]
    parts: list[tuple[str, list[Cell]]] = []
    if large:
        parts.append((LARGE_PIPE, large))
    if small:
        parts.append((LINE_OBJECT["water"], small))
    base = attach(path, goals) if not large else 0
    for j, cell in enumerate(reversed(small), 1):
        small_dist[cell] = base + j
    for cell in large:
        small_dist[cell] = 0
    return parts, path


def _shortest(
    starts: set[Cell],
    fed: set[Cell],
    blocked: set[Cell],
    avoid: set[Cell],
    width: int,
    height: int,
) -> list[Cell] | None:
    """Shortest path of new cells from any start to a cell touching ``fed`` (or on it)."""
    parent: dict[Cell, Cell | None] = {c: None for c in starts}
    queue = deque(sorted(starts))
    while queue:
        cell = queue.popleft()
        touches = cell in fed or any(
            (cell[0] + dx, cell[1] + dy) in fed for dx, dy in NEIGHBOURS
        )
        if touches:
            path = []
            at: Cell | None = cell
            while at is not None:
                path.append(at)
                at = parent[at]
            path.reverse()
            return [c for c in path if c not in fed] or None
        for dx, dy in NEIGHBOURS:
            nxt = (cell[0] + dx, cell[1] + dy)
            if (
                nxt not in parent
                and 0 <= nxt[0] < width
                and 0 <= nxt[1] < height
                and nxt not in blocked
                and nxt not in avoid
            ):
                parent[nxt] = cell
                queue.append(nxt)
    return None
