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
ENTRANCE = (
    "Every foundation/room needs a VALID entrance, placed right after it: a door in its "
    "edge, reachable from outside (not blocked by another building, fence or object). A "
    "building with no usable door is 'Requires Entrance' and nothing gets built or used.",
    "Choose the door for who it serves: workmen building it need a Door or StaffDoor "
    "(never only a JailDoor); staff rooms (offices, kitchens, staffrooms, power halls) a "
    "StaffDoor or Door; rooms where PRISONERS must go (cells, dormitories, canteen, "
    "shower, yard) a Door or JailDoor, and prisoners cannot open a StaffDoor; guards open "
    "any door. A mixed room needs one door each group can open, or two doors.",
    "After the first door the walls go up; check with `ctl area X Y W H` that the edge is "
    "W (wall) with the door cell open, and that `ctl staff`/workmen are not queuing at it.",
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
    "`ctl staff` shows every staff member's EnergyLevel and RestState; workmen at 0 are "
    "exhausted and work badly until they can rest in a Staffroom.",
    "Prisoners without a cell/bed can die or escape, which cuts reputation and income: "
    "pause intake (IntakeTypeChange Closed) when prisoners exceed beds.",
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
    "entrance": ENTRANCE,
    "power": POWER,
    "people": PEOPLE,
    "grants": GRANTS,
    "build": BUILD,
}

ACTION_HINTS: dict[str, tuple[str, ...]] = {
    "AcceptGrant": GRANTS,
    "CancelGrant": GRANTS[:1],
    "IntakeTypeChange": (
        "Closed (stops arrivals), Fill Capacity, Total Prisoners, Num Per Day, All "
        "Available (0-4). Pause intake when prisoners exceed cells. TODO: per-category "
        "intake controls (MinSec / Normal / MaxSec) are not wired yet.",
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
    "JailDoor": DOORS[:1] + ENTRANCE[1:2],
    "Door": DOORS[1:2] + ENTRANCE[1:2],
    "StaffDoor": DOORS[1:2] + ENTRANCE[1:2],
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
    "foundation": ENTRANCE + DOORS + BUILD,
    "room": ENTRANCE[:2] + BUILD[:1],
    "place": BUILD,
    "line": POWER[:1] + BUILD[:1],
    "hire": PEOPLE[1:]
    + (
        "Exhausted staff (EnergyLevel 0) stop working: check `ctl staff`; they need a "
        "Staffroom (`ctl rules Staffroom`: 4x4 indoor, seats, DrinkMachine) to rest.",
    ),
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


STAFF_ACTIONS = frozenset(
    {
        "BeginResearch",
        "ToggleResearchDesired",
        "ToggleStaffKeys",
        "AssignGuardToPrisoner",
        "StartReformProgram",
        "ScheduleProgram",
    }
)
"""Actions after which the reply may carry ``staff_status`` (sporadically)."""


def is_staff_job(specs: list[dict]) -> bool:
    """Whether the build specs hire staff or place staff-run rooms/objects."""
    return any(str(s.get("tool", "")).lower() == "hire" for s in specs)
