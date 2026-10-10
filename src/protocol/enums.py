"""Names for the game's magic numbers (RPC arguments, snapshot type ids).

Each table maps a wire value to the game's name. A value is listed only with
evidence: a capture (journal2) or the binary / data files (IDA). Tables are
partial where marked.
"""

from __future__ import annotations

VEHICLES: dict[int, str] = {
    # NewVehicleCallout (43): captures/bot-goal.sqlite, a Squads entry of this
    # Type appears right after each callout (journal2 "Bot actions, live").
    1: "FireEngine",
    3: "RiotPolice",
}

OBJECT_TYPES: dict[int, str] = {
    # ObjectData ``t`` / ObjectAdded type. Partial: ids are assigned at load,
    # these pairs come from the captures (save ``Objects.Type`` by uId).
    14: "Chair",
    41: "StaffDoor",
    132: "Warden",
    231: "OfficeDesk",
    233: "FilingCabinet",
    241: "PowerStation",
}

RESEARCH: dict[int, str] = {}
"""BeginResearch / ToggleResearchDesired id -> research name."""

ROOM_TYPES: dict[int, str] = {}
"""CreateRoom type -> room name."""

STAFF = frozenset({"Workman", "Warden", "Guard", "Cook"})
"""Object type names that are staff (save ``Objects.Type``). Partial: from the
captures (``Workman``, ``Warden``) and the first grant's ``RequiredId``s."""


def name_of(table: dict[int, str], value: int) -> str:
    """``table[value]``, or ``#value`` when the name is unknown."""
    return table.get(value, f"#{value}")
