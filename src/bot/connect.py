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
) -> dict[str, Any]:
    """The runs that connect every unserved consumer: ``{"targets", "jobs", "skipped"}``."""
    utility = network.UTILITIES[utility_name]
    report = network.analyze(cells, objects, utility, with_cells=True)
    fed: set[Cell] = set()
    raw: set[Cell] = set()
    for net in report["networks"]:
        if net["kind"] == FED_KIND[utility_name]:
            fed.update(map(tuple, net["cell_list"]))
        elif net["kind"] in RAW_KINDS:
            raw.update(map(tuple, net["cell_list"]))
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
            continue
        targets.append((o, cover))
    targets.sort(key=lambda t: (t[0].get("Pos.y", 0), t[0].get("Pos.x", 0)))
    jobs: list[dict[str, Any]] = []
    skipped: list[str] = []
    for o, cover in targets:
        label = f"{o.get('Type')} #{o.get('Id.i')} at {o.get('Pos.x')},{o.get('Pos.y')}"
        if cover & (unfed_reach if utility_name == "electricity" else fed):
            continue  # an earlier run already serves it
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
        path = _shortest(
            starts,
            fed,
            blocked,
            near_raw if utility_name == "electricity" else set(),
            width,
            height,
        )
        if path is None:
            skipped.append(f"{label}: no free route to a fed network")
            continue
        fed.update(path)
        unfed_reach.update(path)
        unfed_reach.update((x + dx, y + dy) for x, y in path for dx, dy in NEIGHBOURS)
        for x, y, w, h in _runs(path):
            jobs.append(
                {
                    "tool": "line",
                    "object": LINE_OBJECT[utility_name],
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
