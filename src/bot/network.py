"""Validate utility lines (cables, pipes): which networks carry what, and what is wrong.

The save keeps one node per utility (``Electricity``, ``Water``) listing the cells
that hold a cable / pipe. The line's kind is not saved: the game colours it by what
feeds it. :func:`analyze` rebuilds that for any utility from the cells and the
objects touching them, driven by a :class:`Utility` spec:

* ``sources``: role -> object types that put something on a line (electricity:
  ``raw`` green generators, ``ac`` PowerStations);
* ``converters``: objects that sit between two lines and change what they carry
  (a Transformer); input and output must be on separate networks;
* ``passive``: parts that never count as consumers (batteries, meters);
* ``consumer``: tells which of the remaining objects draw from the line.

A utility supplies two hooks, :attr:`Utility.classify` (a network's kind from its
census) and :attr:`Utility.check` (its own rule violations). To validate another
utility, e.g. the hot and cold water of the advanced game mode (disabled for now),
add a :class:`Utility` to :data:`UTILITIES`; nothing else changes.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

Cell = tuple[int, int]
Network = dict[str, Any]

SIZES = {
    "SolarPanels": (3, 2),
    "WindTurbine": (2, 3),
    "SolarWindHybrid": (3, 3),
    "Transformer": (2, 2),
}
"""Footprints (w, h) from ``materials*.txt``; any other object counts as 1x1."""
REACH = ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1))
"""A cell and its four neighbours: an object touches a line when its footprint is there."""


@dataclass(frozen=True)
class Utility:
    """What a kind of line is made of and how to judge its networks."""

    name: str
    node: str
    """Save node whose children (``"x y 1"``) are the cells holding a line."""
    sources: dict[str, frozenset[str]]
    """Role -> types that feed a line with that role."""
    converters: frozenset[str] = frozenset()
    passive: frozenset[str] = frozenset()
    consumer: Callable[[dict[str, Any]], bool] = lambda obj: "Powered" in obj
    """True for an object that draws from the line (sources, converters and passive
    parts are excluded before this is asked)."""
    classify: Callable[[Network], str] = lambda net: "stray"
    """Kind of a network from its census (``roles``, ``converters``, ``consumers``)."""
    check: Callable[[Network, str], list[str]] = lambda net, where: []
    """Problems of one network; ``where`` names it for the message."""


def footprint(obj: dict[str, Any]) -> set[Cell]:
    """The cells an object covers (``Pos`` is its centre)."""
    w, h = SIZES.get(obj.get("Type", ""), (1, 1))
    x0 = round(obj["Pos.x"] - w / 2)
    y0 = round(obj["Pos.y"] - h / 2)
    return {(x0 + i, y0 + j) for i in range(w) for j in range(h)}


def components(cells: set[Cell]) -> list[list[Cell]]:
    """Groups of 4-connected line cells, largest first."""
    seen: set[Cell] = set()
    out = []
    for start in sorted(cells):
        if start in seen:
            continue
        seen.add(start)
        stack, comp = [start], []
        while stack:
            x, y = stack.pop()
            comp.append((x, y))
            for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if n in cells and n not in seen:
                    seen.add(n)
                    stack.append(n)
        out.append(comp)
    return sorted(out, key=len, reverse=True)


def analyze(
    cells: set[Cell], objects: list[dict[str, Any]], utility: Utility
) -> dict[str, Any]:
    """The utility's networks with what touches them, and a list of problems."""
    placed = [(o, footprint(o)) for o in objects if "Pos.x" in o and "Pos.y" in o]
    every_source = frozenset().union(*utility.sources.values())
    networks: list[Network] = []
    problems: list[str] = []
    joins: dict[Any, set[int]] = {}
    # converter id -> the networks it touches (its two sides must differ)
    for n, comp in enumerate(components(cells)):
        reach = {(x + dx, y + dy) for x, y in comp for dx, dy in REACH}
        touching: Counter[str] = Counter()
        consumers: Counter[str] = Counter()
        unpowered = 0
        for obj, cover in placed:
            if not cover & reach:
                continue
            kind = obj.get("Type", "?")
            touching[kind] += 1
            if kind in utility.converters:
                joins.setdefault(obj.get("Id.i"), set()).add(n)
            elif kind not in every_source | utility.passive and utility.consumer(obj):
                consumers[kind] += 1
                unpowered += not obj.get("Powered", True)
        xs, ys = [c[0] for c in comp], [c[1] for c in comp]
        net: Network = {
            "id": n,
            "cells": len(comp),
            "box": [min(xs), min(ys), max(xs), max(ys)],
            "roles": {
                role: sum(touching[t] for t in types)
                for role, types in utility.sources.items()
            },
            "converters": sum(touching[t] for t in utility.converters),
            "consumers": sum(consumers.values()),
            "unpowered": unpowered,
            "consumer_types": dict(consumers),
            "touching": dict(touching),
        }
        net["kind"] = utility.classify(net)
        networks.append(net)
        where = (
            f"network {n} ({len(comp)} cells, x{net['box'][0]}-{net['box'][2]} "
            f"y{net['box'][1]}-{net['box'][3]})"
        )
        problems.extend(utility.check(net, where))
    for cid, nets in joins.items():
        if len(nets) < 2:
            problems.append(
                f"Converter #{cid} touches only network {min(nets)}: its input and "
                "output must be on separate networks"
            )
    return {
        "utility": utility.name,
        "networks": networks,
        "problems": problems,
        "ok": not problems,
    }


def _electricity_kind(net: Network) -> str:
    raw, ac = net["roles"]["raw"], net["roles"]["ac"]
    if raw and ac:
        return "short-circuit"
    if raw:
        return "raw-green"
    if ac or net["converters"]:
        return "ac"
    return "unfed" if net["consumers"] else "stray"


def _electricity_check(net: Network, where: str) -> list[str]:
    out = []
    if net["kind"] == "short-circuit":
        out.append(f"{where}: a PowerStation and raw green sources share cables")
    if net["roles"]["raw"] and net["consumers"]:
        out.append(
            f"{where}: raw green energy runs on the same cables as {net['consumers']} "
            f"consumers ({net['unpowered']} unpowered): consumers need the AC output "
            "side of a Transformer, on cables that touch neither the generators nor "
            "the Transformer's input"
        )
    if net["kind"] == "unfed":
        out.append(f"{where}: {net['consumers']} consumers, no source")
    if net["converters"] > 1:
        out.append(f"{where}: {net['converters']} Transformers on one circuit")
    return out


ELECTRICITY = Utility(
    name="electricity",
    node="Electricity",
    sources={
        "raw": frozenset({"SolarPanels", "WindTurbine", "SolarWindHybrid"}),
        "ac": frozenset({"PowerStation"}),
    },
    converters=frozenset({"Transformer"}),
    passive=frozenset({"Battery", "Capacitor", "PowerExportMeter"}),
    classify=_electricity_kind,
    check=_electricity_check,
)
"""Raw green (blue) lines need a Transformer before they can feed consumers (green)."""

UTILITIES: dict[str, Utility] = {ELECTRICITY.name: ELECTRICITY}
"""Utilities ``ctl network`` can validate, by name."""
