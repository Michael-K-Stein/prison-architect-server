"""Names for the game's magic numbers (RPC arguments, snapshot type ids).

The full tables are the game's own, read from the binary
(:mod:`src.protocol.game_tables`); every capture pair checked so far matches
(journal2 "Object, material and room tables (IDA)").
"""

from __future__ import annotations

from src.protocol.game_tables import (
    INTAKE_TYPES,
    JOB_TYPES,
    MATERIALS,
    OBJECTS,
    ROOMS,
    VEHICLES,
)

OBJECT_TYPES = OBJECTS
ROOM_TYPES = ROOMS

RESEARCH: dict[int, str] = {}
"""BeginResearch / ToggleResearchDesired id -> research name (not extracted yet)."""

STAFF = frozenset({"Workman", "Guard", "Doctor", "Cook", "Warden"})
"""Object type names that are staff. Partial (journal2, IDA object table)."""

__all__ = [
    "FOUNDATION_MATERIALS",
    "INTAKE_TYPES",
    "JOB_TYPES",
    "MATERIALS",
    "OBJECT_TYPES",
    "OBJECTS",
    "RESEARCH",
    "ROOM_TYPES",
    "ROOMS",
    "STAFF",
    "VEHICLES",
    "WALL_MATERIALS",
    "id_of",
    "name_of",
]

WALL_MATERIALS = {i: MATERIALS[i] for i in (46, 47)}
"""Wall materials seen or named for walls: ConcreteWall, BrickWall. Partial."""

FOUNDATION_MATERIALS = {59: MATERIALS[59]}
"""BuildingConcrete: run4's foundation job used Material 59."""


def name_of(table: dict[int, str], value: int) -> str:
    """``table[value]``, or ``#value`` when the name is unknown."""
    return table.get(value, f"#{value}")


def id_of(table: dict[int, str], name: str) -> int:
    """The id whose name is ``name`` (case-insensitive); KeyError if none."""
    wanted = name.lower()
    for ident, text in table.items():
        if text.lower() == wanted:
            return ident
    raise KeyError(name)
