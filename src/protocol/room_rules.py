"""Room requirements from the game's ``data/materials.txt`` (``BEGIN Room``).

Generated: each room's minimum size, flags (``Enclosed`` walls all round,
``Indoor`` floor under a roof, ``Secure`` fenced from the outside) and required
objects (any of the object or its alternatives). A room that misses one is
flagged in the game and its grant objective (``RequirementsMet``) stays open.
"""

from __future__ import annotations

ROOM_RULES: dict[
    str,
    tuple[
        tuple[int, int] | None, tuple[str, ...], tuple[tuple[str, tuple[str, ...]], ...]
    ],
] = {
    "None": (None, (), ()),
    "Cell": (
        (2, 3),
        ("Enclosed", "Indoor"),
        (
            (
                "Bed",
                ("Mattress", "ComfyBed", "CoffinBed", "OldBed", "CampBed", "NettedBed"),
            ),
            ("Toilet", ()),
        ),
    ),
    "SuperiorCell": (
        (4, 4),
        ("Enclosed", "Indoor"),
        (
            ("SuperiorBed", ("ComfyBed",)),
            ("Toilet", ()),
            ("ShowerHead", ()),
            ("OfficeDesk", ("FancyDesk",)),
            ("Tv", ()),
            ("Bookshelf", ()),
            ("Plant", ()),
        ),
    ),
    "HoldingCell": (
        (5, 5),
        ("Enclosed", "Indoor"),
        (("Toilet", ()), ("Bench", ("SmallBench", "OakBench", "JungleBench"))),
    ),
    "Dormitory": (
        (2, 3),
        ("Enclosed", "Indoor"),
        (
            (
                "Bed",
                (
                    "BunkBed",
                    "Mattress",
                    "ComfyBed",
                    "CoffinBed",
                    "OldBed",
                    "CampBed",
                    "NettedBed",
                ),
            ),
            ("Toilet", ()),
        ),
    ),
    "FamilyCell": (
        (4, 4),
        ("Enclosed", "Indoor"),
        (
            (
                "Bed",
                ("Mattress", "ComfyBed", "CoffinBed", "OldBed", "CampBed", "NettedBed"),
            ),
            ("Toilet", ()),
            ("Crib", ()),
            ("ShowerHead", ()),
        ),
    ),
    "Nursery": (
        None,
        (),
        (
            ("ServingTable", ("SmallServingTable", "JungleServingTable")),
            ("Table", ("SmallTable", "OakTable", "JungleTable")),
            ("Bench", ("SmallBench", "JungleBench")),
            ("Crib", ()),
            ("PlayMat", ()),
        ),
    ),
    "Canteen": (
        None,
        (),
        (
            ("ServingTable", ("SmallServingTable", "JungleServingTable")),
            (
                "Table",
                (
                    "SmallTable",
                    "OakTable",
                    "DiningTableLarge",
                    "DiningTableSmall",
                    "DinerBooth",
                    "JungleTable",
                ),
            ),
            (
                "Bench",
                ("SmallBench", "JungleBench", "OakBench", "DiningChair", "DinerBooth"),
            ),
        ),
    ),
    "Kitchen": (None, (), (("Cooker", ()), ("Fridge", ("TallFridge",)), ("Sink", ()))),
    "Shower": (None, (), (("ShowerHead", ()),)),
    "Yard": ((5, 5), ("Secure",), ()),
    "Storage": (None, (), ()),
    "Exports": ((1, 3), (), ()),
    "Deliveries": ((1, 3), (), ()),
    "Garbage": ((1, 3), (), ()),
    "Intake": (
        None,
        ("Indoor",),
        (
            ("OfficeDesk", ("FancyDesk",)),
            ("Table", ("SmallTable", "OakTable", "JungleTable")),
            ("Chair", ("OfficeChair", "ChairYellow", "SwivelChair")),
        ),
    ),
    "Execution": (None, ("Indoor",), (("ElectricChair", ()),)),
    "Workshop": (
        (5, 5),
        ("Enclosed",),
        (
            ("WorkshopSaw", ()),
            ("WorkshopPress", ()),
            ("Table", ("SmallTable", "OakTable", "JungleTable")),
        ),
    ),
    "Security": (
        (4, 4),
        (),
        (
            ("OfficeDesk", ("FancyDesk",)),
            (
                "Chair",
                (
                    "OfficeChair",
                    "WoodenStool",
                    "ChairYellow",
                    "SwivelChair",
                    "MetalStool",
                ),
            ),
            ("FilingCabinet", ("FilingCabinetFancy",)),
        ),
    ),
    "Office": (
        (4, 4),
        ("Indoor",),
        (
            ("OfficeDesk", ("FancyDesk",)),
            (
                "Chair",
                (
                    "OfficeChair",
                    "WoodenStool",
                    "ChairYellow",
                    "SwivelChair",
                    "MetalStool",
                ),
            ),
            ("FilingCabinet", ("FilingCabinetFancy",)),
        ),
    ),
    "MedicalWard": (None, ("Indoor",), (("MedicalBed", ()),)),
    "Morgue": (None, ("Indoor",), (("MorgueSlab", ()),)),
    "CommonRoom": (None, ("Indoor",), ()),
    "Laundry": (
        None,
        ("Indoor",),
        (
            ("LaundryMachine", ()),
            ("LaundryBasket", ()),
            ("IroningBoard", ("IroningBoardShort",)),
        ),
    ),
    "CleaningCupboard": ((3, 3), ("Indoor",), ()),
    "Visitation": (None, ("Indoor",), (("VisitorTable", ("VisitorTableSecure",)),)),
    "ParoleRoom": ((5, 5), ("Indoor",), (("VisitorTable", ()),)),
    "Solitary": (None, ("Enclosed",), ()),
    "Kennel": ((5, 5), ("Enclosed",), (("DogCrate", ()),)),
    "Armoury": (
        None,
        ("Indoor",),
        (
            ("WeaponRack", ()),
            ("GuardLocker", ()),
            ("Table", ("SmallTable", "OakTable", "JungleTable")),
        ),
    ),
    "Staffroom": (
        (4, 4),
        ("Indoor",),
        (
            (
                "SofaChairDouble",
                (
                    "WoodenStool",
                    "MetalStool",
                    "SofaChairBrown",
                    "SofaChairDoubleBrown",
                    "SofaChairSingle",
                ),
            ),
            ("DrinkMachine", ()),
        ),
    ),
    "Library": ((5, 5), ("Indoor",), (("LibraryBookshelf", ()), ("SortingTable", ()))),
    "Forestry": ((5, 5), ("Outdoor",), ()),
    "Classroom": ((5, 5), (), (("SchoolDesk", ()), ("OfficeDesk", ("FancyDesk",)))),
    "Chapel": ((6, 6), ("Indoor",), (("Altar", ()), ("Pews", ()), ("PrayerMat", ()))),
    "MailRoom": (
        (5, 5),
        ("Indoor", "Enclosed"),
        (("SortingTable", ()), ("Table", ("SmallTable", "OakTable", "JungleTable"))),
    ),
    "Shop": (
        (4, 4),
        ("Indoor", "AdjacentObject"),
        (("Table", ("SmallTable", "OakTable", "JungleTable")), ("ShopShelf", ())),
    ),
    "ClearRooms": (None, (), ()),
}
"""Room name -> (minimum size (x, y) or None, flags, ((object, alternatives), ...))."""


def describe(room: str) -> str | None:
    """One line of what ``room`` needs, or None for an unknown room."""
    rule = ROOM_RULES.get(room)
    if rule is None:
        return None
    size, flags, objs = rule
    parts = [f"at least {size[0]}x{size[1]}"] if size else []
    parts += [f.lower() for f in flags]
    parts += [o + (f" (or {', '.join(a)})" if a else "") for o, a in objs]
    return f"{room}: " + ("; ".join(parts) or "no requirements")
