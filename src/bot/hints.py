"""Hints for the agent playing through ``ctl``: game rules learned the hard way.

Shown with ``ctl action NAME``, in the replies of ``ctl send`` / ``build`` / ``hire``
(key ``hints``) and by ``ctl hints [topic]``, so a bot can steer itself. Each line is
a fact seen in a capture or told by the game's owner; see journal2 for the evidence.
"""

from __future__ import annotations

DOORS = (
    "Workmen CANNOT open a JailDoor (only guards and above can); a building whose only "
    "door is a JailDoor stays 'Requires Entrance' and its workmen wait outside for a guard.",
    "A StaffDoor can be opened by workmen, staff and guards, never by prisoners; a plain "
    "Door by everyone. Give a new building a Door or StaffDoor first, add JailDoors for "
    "prisoners later.",
    "Staff and prisoners cannot pass through walls (the 'Super Guards' toggle that allows it "
    "is off by default); walls only go up once a building has a door.",
)
POWER = (
    "A cable must touch each device; only Lights work a few cells from a cable, and walls "
    "cut that reach but doors do not. Cables pass under walls.",
    "Each generator (PowerStation, SolarPanels, WindTurbine, SolarWindHybrid) has its own "
    "Switch (ElectricalSwitch takes the object INDEX or a name from `ctl name`) and may "
    "arrive off. Capacity is per generator; Demand above it overloads the grid and ALL "
    "power is cut (Overloaded=1). A PowerStation and green sources on one network read "
    "Overloaded=3 (short circuit); keep them on separate cables.",
    "Battery and Transformer are indoor only; generators are outdoor.",
)
PEOPLE = (
    "Prisoners without a cell/bed can die or escape, which cuts reputation and income: "
    "pause intake (IntakeTypeChange None) when prisoners exceed beds.",
    "Research needs the matching staff member hired AND seated in his own Office room "
    "(`ctl research NAME`); one occupant per Office; check progress after a few seconds "
    "with `ctl refresh`, not just 'sent: true'.",
)
GRANTS = (
    "AcceptGrant takes the full objective name (Grant_GreenMachine); any spelling works "
    "in the bot (`ctl names grants`). A grant whose tasks are already met completes at once.",
    "target_* are the Green Energy Goals, a separate category from grants. target_PowerStation "
    "needs no PowerStation running for 10 game days; its Save Grants progress node shows the "
    "completion minute (GreenDeadline).",
)
BUILD = (
    "'sent: true' only means the bot sent the job. Confirm in `ctl state ConstructionSystem "
    "Jobs` or object counts; a job the host refuses is dropped silently.",
    "Objects arrive by supply truck: wait (`ctl wait`) and run at game speed 10 (the host "
    "clamps higher values).",
)

TOPICS: dict[str, tuple[str, ...]] = {
    "doors": DOORS,
    "power": POWER,
    "people": PEOPLE,
    "grants": GRANTS,
    "build": BUILD,
}

ACTION_HINTS: dict[str, tuple[str, ...]] = {
    "AcceptGrant": GRANTS,
    "CancelGrant": GRANTS[:1],
    "IntakeTypeChange": (
        "0 None (stops arrivals), 1 FillCapacity, 2 TotalPrisoners, 3 NumPerDay, "
        "4 AllAvailable. Pause intake when prisoners exceed cells.",
        *PEOPLE[:1],
    ),
    "ElectricalSwitch": POWER[1:2],
    "BeginResearch": PEOPLE[1:],
    "ToggleResearchDesired": PEOPLE[1:],
    "RemovePrisoner": (
        "Removing a prisoner costs 5000 (securitymenu_RemovedPrisoner).",
    ),
    "GameSpeedChange": ("The host accepts any value up to 10 and clamps higher ones.",),
}

OBJECT_HINTS: dict[str, tuple[str, ...]] = {
    "JailDoor": DOORS[:1],
    "Door": DOORS[1:2],
    "StaffDoor": DOORS[1:2],
    "Battery": POWER[2:],
    "Transformer": POWER[2:],
    "SolarPanels": POWER[1:2],
    "WindTurbine": POWER[1:2],
    "SolarWindHybrid": POWER[1:2],
    "PowerStation": (
        "Avoid it for target_PowerStation (the 10-day no-station clock) and never put it on "
        "the same network as green sources.",
        *POWER[1:2],
    ),
    "Capacitor": POWER[:1],
    "ElectricalCable": POWER[:1],
}

TOOL_HINTS: dict[str, tuple[str, ...]] = {
    "foundation": DOORS + BUILD,
    "room": BUILD[:1],
    "place": BUILD,
    "line": POWER[:1] + BUILD[:1],
    "hire": PEOPLE[1:],
    "demolish": (
        "Bulldozing removes terrain/walls/floors; objects (and often cables) stay.",
    ),
}


def for_action(name: str) -> list[str]:
    """Hints for RPC action ``name``."""
    return list(ACTION_HINTS.get(name, ()))


def for_jobs(specs: list[dict]) -> list[str]:
    """Hints for build job specs (by tool and by object/role name), without repeats."""
    out: list[str] = []
    for spec in specs:
        tool = str(spec.get("tool", "")).lower()
        names = [spec.get("object"), spec.get("role"), spec.get("kind")]
        for text in TOOL_HINTS.get(tool, ()):
            if text not in out:
                out.append(text)
        for name in names:
            for text in OBJECT_HINTS.get(str(name), ()):
                if text not in out:
                    out.append(text)
    return out
