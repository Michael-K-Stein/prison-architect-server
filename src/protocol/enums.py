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

RESEARCH: dict[int, str] = dict(
    enumerate(
        "None Warden Maintainance Security Legal MentalHealth Finance Cctv "
        "RemoteAccess Health Cleaning GroundsKeeping Deployment Patrols Dogs "
        "PrisonLabour Education LandExpansion Contraband Policy Armoury BodyArmour "
        "Tazers TazersForEveryone BankLoans LowerTaxes1 LowerTaxes2 ExtraGrant "
        "AdvancedManagement Deathrow PermanentPunishment RemoveMinCellSize "
        "ReduceExecutionLiability LegalPrep LegalDefense".split()
    )
)
"""BeginResearch / ToggleResearchDesired id -> name: static array at
``0x140DF4A20`` filled by ``sub_140096B10`` (IDA). Spelling is the game's."""

INTAKE_MODES: dict[int, str] = {
    0: "Closed",
    1: "Fill Capacity",
    2: "Total Prisoners",
    3: "Num Per Day",
    4: "All Available",
}
"""``IntakeTypeChange`` argument as the game's intake screen labels it (user, MKS2); the
binary's enum names are in ``INTAKE_TYPES`` (0 is called ``None`` there). TODO: the
intake screen also has per-category controls (``Intake/cat`` MinSec / Normal / MaxSec
ratios, pools); not wired yet."""

ADVISERS: dict[int, str] = {
    0: "Unknown",
    1: "The CEO",
    2: "The Warden",
    3: "The Governor",
    4: "The Chief",
    5: "The Doctor",
    6: "The KingPin",
    7: "Edward (shooter)",
    8: "Edward (sinner)",
    9: "Edward (inmate)",
    10: "Edward's Wife Susan",
    11: "The Priest",
    12: "Don Palermo",
    13: "Don Palermo (angry)",
    14: "Nico Tamoretti",
    15: "Nico Tamoretti (shower)",
    16: "Nico Tamoretti (suited)",
    17: "Nico Tamoretti (infirmary)",
    18: "Sonny Palermo",
    19: "Sonny Palermo (suited)",
    20: "Sonny Palermo (strangled)",
}
"""``NewSpeechAdded`` first argument: the adviser who speaks. The order is the game's
adviser registry (static initializer ``sub_14004EA80``: name + portrait pairs, 0 =
Unknown ... 20 = SonnyStrangled; journal2 "Adviser indices"). 7-11 are the Death Row
campaign (Edward, Susan, the Priest), 12-20 the Food campaign (the Palermos). Only
1 = The CEO was confirmed live (``help_warning_prisonerreleased`` came with 1 and the
user saw it as a call from "The CEO", MKS2 packet 7372)."""

STAFF_TYPES = frozenset(
    {
        "Workman",
        "Guard",
        "RiotGuard",
        "ArmedGuard",
        "Doctor",
        "Cook",
        "Warden",
        "Janitor",
        "Gardener",
        "Foreman",
        "Chief",
        "Lawyer",
        "Accountant",
        "Psychologist",
        "DogHandler",
        "Orderly",
        "Sniper",
        "ParoleOfficer",
        "ParoleLawyer",
        "Farmer",
    }
)
"""Object type names of every staff member (all have EnergyLevel ``el`` and RestState ``rs``)."""

STAFF = frozenset({"Workman", "Guard", "Doctor", "Cook", "Warden"})
"""Object type names that are staff. Partial (journal2, IDA object table)."""

__all__ = [
    "ADVISERS",
    "STAFF_TYPES",
    "INTAKE_MODES",
    "ELECTRICAL",
    "FOUNDATION_MATERIALS",
    "ROOM_ERRORS",
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

ELECTRICAL = frozenset(
    {"Capacitor", "Cctv", "CctvMonitor", "Cooker", "DoorControlSystem", "DoorTimer"}
    | {"ElectricChair", "Fridge", "LargeTv", "LaundryMachine", "Light"}
    | {"LogicBridge", "LogicCircuit", "MetalDetector", "PhoneMonitor", "PowerStation"}
    | {"PowerSwitch", "PressurePad", "Servo", "StatusLight", "Tv", "WaterBoiler"}
    | {"WaterPumpStation", "WorkshopPress", "WorkshopSaw"}
)
"""Objects with ``Properties Electrical`` in the game's ``data/materials.txt``:
they need power (a powered one has ``Powered=True`` in the save)."""

ROOM_ERRORS: dict[int, str] = {
    1: "roomerror_nokitchen",
    2: "roomerror_noprisoners",
    3: "roomerror_nocanteen_kitchen",
    4: "roomerror_nocanteen_cells",
    5: "roomerror_deathrow_sharedcell",
    6: "roomerror_nonursery",
    7: "roomerror_laundryoverloaded",
}
"""Room ``RoomError`` -> text key: the UI's switch in ``sub_1401EB850`` (IDA)."""

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
