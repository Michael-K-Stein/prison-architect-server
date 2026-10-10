"""Pure helpers that reproduce what the in-game Todo list shows, from save data.

Input is plain ``dict`` nodes as ``python main.py bot ctl state Save Objects`` prints
them: the ``Objects`` node maps ``"/[i N]"`` to one object dict (``Type``, ``Damage``,
``Energy``, ``RestState``, ``/Bio``, ``/Needs`` ...), ``Rooms`` likewise. A key the
game omits because it equals the default is read as its default (``Damage`` 0,
``RestState`` OK). Nothing here touches the network or the bot's state.

Every rule says in its docstring how sure it is:

* **confirmed**: read from the decompile of Prison Architect64.exe (addresses in
  ``journal/journal2.md``, section "In-game Todo list").
* **inferred**: the decompile gives the shape, but a field name or a constant was
  matched by hand (save name for a struct offset, type-flag meaning ...).
* **unknown**: not decoded; the function says so and returns ``None`` or a guess.

The game keeps its Todo numbers as counters on the Prison object (``Prison+18024``
medical, ``+18076`` dead, ``+18136`` exhausted ...), recomputed every tick from the
object table. They are not in the save, so this module recounts them.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from typing import Any

from src.protocol.enums import STAFF_TYPES
from src.protocol.game_text import TEXT

Node = Mapping[str, Any]

DEAD_DAMAGE = 1.0
"""``Damage`` at or above this is a dead body (``obj+104 >= 1.0``; confirmed)."""

MEDICAL_DAMAGE = 0.25
"""``Damage`` above this (and below ``DEAD_DAMAGE``) needs medical attention (confirmed)."""

PERSON_TYPES = frozenset(
    {"Prisoner", "Visitor", "Dog", "Paramedic", "Fireman", "Soldier", "EliteOps"}
) | frozenset(STAFF_TYPES)
"""Object types that count for the incident counters. The game tests a type flag
(``type+152 & 2``); which types carry it is inferred (living things with ``Damage``)."""

CATEGORIES = (
    "MinSec",
    "Normal",
    "MaxSec",
    "Protected",
    "SuperMax",
    "DeathRow",
    "Insane",
)
"""Prisoner category in game order (confirmed, enum 1..7 at ``Prisoner+2612``). The
binary calls the second one ``MedSec``; the save says ``Normal``."""

NEXT_PAROLE = ("None", "Half", "ThreeQuarters", "Failed", "Succeeded")
"""``Bio.NextParole`` enum order (confirmed, ``sub_140052B90``)."""

PAROLE_FRACTION = {"Half": 0.5, "ThreeQuarters": 0.75}
"""A prisoner is up for parole once ``Served >= SentenceF * fraction`` (confirmed)."""

REST_STATES = (
    "RestStateOK",
    "RestStateRequired",
    "RestStateResting",
    "RestStateExhausted",
)
"""``RestState`` enum order (confirmed, ``sub_140060640``); live ``rs`` is the index."""

NEEDS = (
    "Nothing Bladder Bowels Sleep Food Safety Hygiene Exercise Family Recreation Comfort "
    "Environment Warmth Privacy Freedom Clothing Drugs Alcohol Spirituality Literacy "
    "BabySleep BabyPlay Luxuries Hydration"
).split()
"""Need names of a prisoner (``sub_14008AD20`` order, staff needs left out)."""

RAISES_TEMP = frozenset(
    "Bladder Bowels Sleep Food Hygiene Exercise Family Recreation Freedom Warmth".split()
)
"""Needs with the ``RaisesTemp`` property in ``data/needs.txt``. The bucket code tests
property bit 4; that ``RaisesTemp`` is bit 4 (declaration order) is inferred."""


# ---------------------------------------------------------------- object access


def iter_nodes(node: Node | Iterable[Node] | None) -> Iterator[Node]:
    """The child dicts of a save array node (``"/[i N]"`` keys), or of a plain list."""
    if not node:
        return
    if isinstance(node, Mapping):
        for key, value in node.items():
            if isinstance(value, Mapping) and key.startswith("/["):
                yield value
    else:
        yield from node


def _get(obj: Node, long: str, short: str | None = None, default: Any = 0) -> Any:
    """Field by save name, falling back to the live short key (``Damage`` / ``da``)."""
    if long in obj:
        return obj[long]
    if short is not None and short in obj:
        return obj[short]
    return default


def type_of(obj: Node) -> str:
    return str(_get(obj, "Type", "name", ""))


def damage(obj: Node) -> float:
    """``Damage`` 0..1; the save leaves the key out at 0."""
    return float(_get(obj, "Damage", "da", 0.0) or 0.0)


def is_alive(obj: Node) -> bool:
    """``Damage < 1.0``. (The game also keeps a body that a type flag marks as
    non-dead, ``obj+2536 & 0x4000000``; that flag is not in the save and is ignored.)"""
    return damage(obj) < DEAD_DAMAGE


def prisoners(objects: Node | Iterable[Node] | None, alive: bool = True) -> list[Node]:
    """Prisoner objects, by default only the living ones (confirmed: every prisoner
    statistic skips ``Damage >= 1.0``)."""
    return [
        o
        for o in iter_nodes(objects)
        if type_of(o) == "Prisoner" and (is_alive(o) or not alive)
    ]


def category_of(prisoner: Node) -> str:
    """``MinSec`` .. ``Insane`` (a missing ``Category`` reads as ``MinSec``)."""
    return str(prisoner.get("Category") or "MinSec")


# ---------------------------------------------------------------- incident reports


def medical_attention(objects: Node | Iterable[Node] | None) -> int:
    """ "N require medical attention" (``objective_incident_medical``).

    Confirmed: the per-tick loop of ``sub_1407B8BF0`` counts persons whose
    ``Damage`` (obj+104) is above 0.25 and below 1.0 into ``Prison+18024``; the line
    shows when that counter is above 0. Inferred: which types count as persons.
    """
    return sum(
        1
        for o in iter_nodes(objects)
        if type_of(o) in PERSON_TYPES and MEDICAL_DAMAGE < damage(o) < DEAD_DAMAGE
    )


def dead_bodies(objects: Node | Iterable[Node] | None) -> int:
    """ "N dead bodies" (``objective_incident_dead``): persons with ``Damage >= 1.0``
    (confirmed, ``Prison+18076``; same type caveat as ``medical_attention``)."""
    return sum(
        1
        for o in iter_nodes(objects)
        if type_of(o) in PERSON_TYPES and damage(o) >= DEAD_DAMAGE
    )


def incident_counts(
    objects: Node | Iterable[Node] | None,
    solitary: int = 0,
    solitary_queue: int = 0,
    lockdown: int = 0,
) -> dict[str, Any]:
    """The whole "Incident Reports" item (objective type ``ActionRequired``, 22).

    ``solitary`` / ``solitary_queue`` / ``lockdown`` are the punishment counters
    (``Prison+3932`` / ``+3936`` / ``+3928``); their source is not decoded (see
    journal), pass what you know. The item is *hidden* when lockdown, solitary,
    queued and medical are all 0 (confirmed, ``sub_14066E4D0``); dead bodies alone do
    not keep it open, but the line is drawn when it is open.
    """
    medical = medical_attention(objects)
    dead = dead_bodies(objects)
    visible = bool(solitary or solitary_queue or lockdown or medical)
    lines: list[str] = []
    if solitary and solitary_queue:
        lines.append(
            _fmt("objective_punishment_solitary_mix", X=solitary, Y=solitary_queue)
        )
    elif solitary_queue:
        lines.append(_fmt("objective_punishment_solitary_queue", X=solitary_queue))
    elif solitary:
        lines.append(_fmt("objective_punishment_solitary", X=solitary))
    if lockdown:
        lines.append(_fmt("objective_punishment_lockdown", X=lockdown))
    if medical:
        lines.append(_fmt("objective_incident_medical", X=medical))
    if dead:
        lines.append(_fmt("objective_incident_dead", X=dead))
    return {
        "id": "ActionRequired",
        "title": TEXT.get("objective_actionrequired", "Incident Reports"),
        "visible": visible,
        "medical": medical,
        "dead": dead,
        "lines": lines if visible else [],
    }


# ---------------------------------------------------------------- parole / release


def parole_fraction(prisoner: Node) -> float | None:
    """The share of the sentence after which the next parole hearing is due, from
    ``Bio.NextParole`` (Half 0.5, ThreeQuarters 0.75; anything else: no hearing)."""
    bio = prisoner.get("/Bio") or {}
    return PAROLE_FRACTION.get(str(bio.get("NextParole", "None")))


def parole_due(objects: Node | Iterable[Node] | None) -> list[Node]:
    """Prisoners counted by "N prisoners up for parole" (``objective_parole_count``).

    Confirmed (``sub_1407CD710``): a living prisoner (``Damage < 1``) who is not
    category ``Insane`` (state 7), with ``SentenceF > 1.0`` and ``NextParole`` Half or
    ThreeQuarters, is listed when ``SentenceF * (0.5 | 0.75) <= Served``. ``Failed``,
    ``Succeeded`` and ``None`` never are. (A ThreeQuarters prisoner whose sentence is
    at most 2.0 is switched to Failed by that function; that is the same as not due
    here as long as the caller does not re-run it.) Item 23 is hidden when this list
    and the release counter are both empty (``sub_14066E4D0``).
    """
    due = []
    for p in prisoners(objects):
        if category_of(p) == "Insane":
            continue
        bio = p.get("/Bio") or {}
        sentence = float(bio.get("SentenceF", 0.0) or 0.0)
        served = float(bio.get("Served", 0.0) or 0.0)
        fraction = parole_fraction(p)
        if fraction is None or sentence <= 1.0:
            continue
        if bio.get("NextParole") == "ThreeQuarters" and sentence <= 2.0:
            continue  # the game turns it into Failed
        if sentence * fraction <= served:
            due.append(p)
    return due


def due_for_release(
    objects: Node | Iterable[Node] | None, horizon: float = 1.0
) -> list[Node]:
    """UNKNOWN: "N prisoners due for release soon" (``objective_outgoing_count``).

    The game shows ``Prison+6716`` (a counter in the Intake system, offset +708 of
    ``Prison+6008``) and the timer text ``objective_outgoing_timer`` is not referenced
    by the exe at all. Who writes that counter was not found. This is a guess: living
    prisoners with at most ``horizon`` sentence units left (``SentenceF - Served``).
    Do not rely on it.
    """
    out = []
    for p in prisoners(objects):
        bio = p.get("/Bio") or {}
        sentence = float(bio.get("SentenceF", 0.0) or 0.0)
        served = float(bio.get("Served", 0.0) or 0.0)
        if sentence > 0 and 0 <= sentence - served <= horizon:
            out.append(p)
    return out


def prisoner_name(prisoner: Node) -> str:
    bio = prisoner.get("/Bio") or {}
    return f"{bio.get('Forname', '')} {bio.get('Surname', '')}".strip()


# ---------------------------------------------------------------- staff exhaustion


def rest_state(obj: Node) -> int:
    """``RestState`` as the enum index 0..3 (save string ``RestStateRequired`` or the
    live ``rs`` integer; missing is 0)."""
    value = _get(obj, "RestState", "rs", 0)
    if isinstance(value, str):
        return REST_STATES.index(value) if value in REST_STATES else 0
    return int(value or 0)


def staff(objects: Node | Iterable[Node] | None) -> list[Node]:
    """Staff objects that take part in the rest counters: staff types except ``Dog``
    (the rest code skips type 121, the dog; confirmed) and the dead."""
    return [
        o
        for o in iter_nodes(objects)
        if type_of(o) in STAFF_TYPES and type_of(o) != "Dog" and is_alive(o)
    ]


def exhausted_staff(
    objects: Node | Iterable[Node] | None, prisoner_count: int | None = None
) -> dict[str, int]:
    """ "N staff members are exhausted. (M are resting)" (objective type 25).

    Confirmed (``sub_14053E3B0``, ``sub_140539CD0``): each tick every staff member
    with ``RestState != OK`` bumps ``Prison+18136`` (exhausted); a staff member who is
    standing in a staff room bumps ``Prison+18132`` (resting) and gets state 2
    (Resting). So resting is a subset of exhausted. The state turns 1 (Required) when
    ``Energy`` drops to 5 or below. The counting code only runs while the prison has
    prisoners (``Prison+1560 -> +436 > 0``), so with none both are 0. Inferred: the
    resting count is the people whose saved state is ``RestStateResting``.
    """
    people = staff(objects)
    if prisoner_count is None:
        prisoner_count = len(prisoners(objects))
    if prisoner_count <= 0:
        return {"exhausted": 0, "resting": 0, "staff": len(people)}
    exhausted = sum(1 for o in people if rest_state(o) != 0)
    resting = sum(1 for o in people if rest_state(o) == 2)
    return {"exhausted": exhausted, "resting": resting, "staff": len(people)}


def exhausted_percent(
    objects: Node | Iterable[Node] | None, prisoner_count: int | None = None
) -> int | None:
    """Category ``ExhaustedStaffPercent``: ``int(exhausted / Prison+18008 * 100)``.
    Confirmed formula; inferred that ``Prison+18008`` is the number of staff (its
    writer was not found). ``None`` when there is no staff."""
    counts = exhausted_staff(objects, prisoner_count)
    if not counts["staff"]:
        return None
    return int(counts["exhausted"] / counts["staff"] * 100)


def has_staff_room(rooms: Node | Iterable[Node] | None) -> bool:
    """Whether a room of type 26 (``Staffroom``) exists (confirmed: ``sub_1402D9B40``
    counts rooms with ``type == 26``; not checked whether it is functional)."""
    return any(r.get("RoomType") == "Staffroom" for r in iter_nodes(rooms))


def staff_exhausted_item(
    objects: Node | Iterable[Node] | None,
    rooms: Node | Iterable[Node] | None,
    prisoner_count: int | None = None,
) -> dict[str, Any]:
    """The "Staff Exhausted" item (hidden when nobody is exhausted; confirmed)."""
    counts = exhausted_staff(objects, prisoner_count)
    lines: list[str] = []
    if counts["exhausted"] > 0:
        lines.append(_fmt("objective_reststaff_exhausted", X=counts["exhausted"]))
        if has_staff_room(rooms):
            lines.append(_fmt("objective_reststaff_resting", X=counts["resting"]))
        else:
            lines.append(TEXT.get("objective_reststaff_needstaffroom", ""))
    return {
        "id": "StaffRested",
        "title": TEXT.get("objective_staffexhausted", "Staff Exhausted"),
        "visible": counts["exhausted"] > 0,
        **counts,
        "lines": lines,
    }


# ---------------------------------------------------------------- intake


def category_counts(objects: Node | Iterable[Node] | None) -> dict[str, int]:
    """Living prisoners per category (confirmed ``sub_1407C4700``; the Death Row item
    is hidden when the ``DeathRow`` count is 0)."""
    counts = dict.fromkeys(CATEGORIES, 0)
    for p in prisoners(objects):
        name = category_of(p)
        counts[name] = counts.get(name, 0) + 1
    return counts


def intake_closed(intake: Node | None) -> bool:
    """``Intake.IntakeType == 0`` ("Your prison is closed to new inmates"). The panel
    also closes during a riot or staff strike (not in this node). Confirmed for
    type 0 (``sub_140663720``)."""
    return not (intake or {}).get("IntakeType", 0)


def intake_arrival_time(intake: Node | None) -> str:
    """The "Y" of "X Prisoners arriving at Y": ``DailyScheduledTime`` as ``HH:00``
    (confirmed, ``%02i:00`` of ``Prison+6740`` = ``Intake+732``)."""
    hour = int((intake or {}).get("DailyScheduledTime", 0) or 0)
    return f"{hour:02d}:00"


# ---------------------------------------------------------------- needs


def need_bucket(
    charge: float, action_point: float, raises_temp: bool
) -> dict[str, float]:
    """Where one prisoner's one need falls (confirmed, ``sub_14061D410``).

    ``charge`` is the need's level (``Need.Charge``, 100 = fully unmet) and
    ``action_point`` its ``ActionPoint``; both field matches are inferred from the
    save names. Buckets (the game's vector slots 1 / 4 / 7 / 10): ``critical`` when
    ``charge >= 100`` and the need ``RaisesTemp``; ``high`` when ``charge >=
    ap + 0.8 * (100 - ap)``; ``mid`` when ``ap <= charge`` below that; ``low`` below
    ``ap`` (split into low/mid between 0.6 ap and ap).
    """
    out = {"critical": 0.0, "high": 0.0, "mid": 0.0, "low": 0.0}
    ap = action_point
    if charge >= 100.0 and raises_temp:
        out["critical"] = 1.0
    elif charge < ap + (100.0 - ap) * 0.8:
        if charge < ap:
            if charge >= ap * 0.6:
                span = ap - ap * 0.7
                f = (charge - ap * 0.7) / span if span else 1.0
                f = min(1.0, max(0.0, f))
                out["low"] = 1.0 - f
                out["mid"] = f
            else:
                out["low"] = 1.0
        else:
            out["mid"] = 1.0
    else:
        out["high"] = 1.0
    return out


def _need_items(prisoner: Node) -> Iterator[Node]:
    needs = (prisoner.get("/Needs") or {}).get("/Needs") or {}
    yield from iter_nodes(needs)


def needs_percent(
    objects: Node | Iterable[Node] | None, need: str, kind: str = "critical"
) -> int | None:
    """``CriticalNeedsPercent`` / ``HighNeedsPercent`` of one need, 0..100.

    Confirmed formulas (``sub_14067B710``): critical = ``critical / total``; high =
    ``(high + critical) / total`` with ``total = critical + high + mid + low`` summed
    over the living prisoners that have the need, then ``int(x * 100)``. ``kind`` is
    ``"critical"`` or ``"high"``. ``None`` with no data. The prisoner's special
    current-action adjustments (cases 7 / 12 / 27 of ``sub_14061D410``) are ignored.
    """
    totals = {"critical": 0.0, "high": 0.0, "mid": 0.0, "low": 0.0}
    for p in prisoners(objects):
        for item in _need_items(p):
            if item.get("Type") != need:
                continue
            b = need_bucket(
                float(item.get("Charge", 0.0) or 0.0),
                float(item.get("ActionPoint", 0.0) or 0.0),
                need in RAISES_TEMP,
            )
            for k, v in b.items():
                totals[k] += v
    total = sum(totals.values())
    if not total:
        return None
    num = totals["critical"] + (totals["high"] if kind == "high" else 0.0)
    return int(num / total * 100.0)


# ---------------------------------------------------------------- measures


def prisoners_per_guard(objects: Node | Iterable[Node] | None) -> int | None:
    """Category ``PrisonersPerGuard``: ``int(count(Prisoner) / (count(Guard) +
    count(ArmedGuard)))`` over the object-type count table (confirmed formula; the
    table counts every object of the type, so dead prisoners are probably included,
    inferred). ``None`` without guards (the game divides by zero and the comparison
    then fails)."""
    nodes = list(iter_nodes(objects))
    n_prisoners = sum(1 for o in nodes if type_of(o) == "Prisoner")
    guards = sum(1 for o in nodes if type_of(o) in ("Guard", "ArmedGuard"))
    return int(n_prisoners / guards) if guards else None


def object_count(objects: Node | Iterable[Node] | None, *names: str) -> int:
    return sum(1 for o in iter_nodes(objects) if type_of(o) in names)


# ---------------------------------------------------------------- alert objectives

OPERATORS = {
    "Below": lambda a, b: a < b,
    "Above": lambda a, b: a > b,
    "AtLeast": lambda a, b: a >= b,
    "AtMost": lambda a, b: a <= b,
    "Equal": lambda a, b: a == b,
}
"""The ``Requirement.property`` of a *generic* requirement (confirmed). For the
indexed categories (``CriticalNeedsPercent`` ... ) the property is the item (the need
name) and the test is always ``>= value``."""

INDEXED = frozenset({"CriticalNeedsPercent", "HighNeedsPercent", "TotalRoomTypeCount"})

# name -> (extras, main, objects, invert, adviser)
#   extras: requirements that must all hold first (category, property, value)
#   main: the requirement that signals the problem (category, property, value)
#   objects: (types that satisfy it, count) for the "Objects" kind (objective type 3)
#   invert: fire when the main/objects requirement is NOT met (clone shown inverted)
#   adviser: id passed to the staff-alert list (132..137, the speaking adviser)
# Extracted from sub_140393C80 (confirmed). Entries the game builds elsewhere
# (POWER01, WATER01, ROOMS01, CONTRABAND01, ...) are not listed.
_DAY14 = ("TimeIndex", "Above", 20160)
ALERTS: dict[str, dict[str, Any]] = {
    "MONEY01": {"extras": [_DAY14], "main": ("Cash", "Below", 5000), "adviser": 137},
    "PRISONERS02": {
        "extras": [("Prisoners", "AtLeast", 50)],
        "main": ("PrisonersPerGuard", "Above", 8),
        "adviser": 133,
    },
    "CONTRABAND02": {
        "main": ("ContrabandSupply", "Narcotics", 75),
        "invert": True,
        "adviser": 133,
    },
    "NEEDS01": {"main": ("HighNeedsPercent", "Bladder", 50), "adviser": 135},
    "NEEDS02": {"main": ("HighNeedsPercent", "Bowels", 50), "adviser": 135},
    "NEEDS03": {"main": ("CriticalNeedsPercent", "Sleep", 30), "adviser": 135},
    "NEEDS04": {"main": ("CriticalNeedsPercent", "Food", 30), "adviser": 135},
    "NEEDS05": {"main": ("CriticalNeedsPercent", "Family", 40), "adviser": 135},
    "NEEDS06": {"main": ("HighNeedsPercent", "Environment", 40), "adviser": 135},
    "NEEDS07": {"main": ("HighNeedsPercent", "Safety", 40), "adviser": 135},
    "NEEDS08": {"main": ("CriticalNeedsPercent", "Hygiene", 30), "adviser": 135},
    "NEEDS09": {"main": ("CriticalNeedsPercent", "Exercise", 40), "adviser": 135},
    "NEEDS10": {"main": ("CriticalNeedsPercent", "Recreation", 40), "adviser": 135},
    "NEEDS11": {"main": ("HighNeedsPercent", "Comfort", 40), "adviser": 135},
    "NEEDS12": {"main": ("HighNeedsPercent", "Privacy", 40), "adviser": 135},
    "NEEDS13": {"main": ("CriticalNeedsPercent", "Freedom", 40), "adviser": 135},
    "NEEDS14": {"main": ("HighNeedsPercent", "Clothing", 40), "adviser": 135},
    "NEEDS15": {"main": ("HighNeedsPercent", "Drugs", 40), "adviser": 135},
    "NEEDS16": {"main": ("CriticalNeedsPercent", "Alcohol", 40), "adviser": 135},
    "NEEDS18": {"main": ("HighNeedsPercent", "Spirituality", 40), "adviser": 135},
    "NEEDS19": {"main": ("HighNeedsPercent", "Literacy", 40), "adviser": 135},
    "INFORMANTS01": {
        "main": ("InformantSuspicion", "AtLeast", 80),
        "adviser": 133,
    },
    "HOLDINGCELL01": {
        "extras": [("TotalRoomTypeCount", "HoldingCell", 1)],
        "main": ("PrisonerOverflowPercent", "AtLeast", 25),
        "adviser": 133,
    },
    "CELLS01": {
        "extras": [
            ("Prisoners", "AtLeast", 50),
            ("PrisonerOccupancyPercent", "Below", 75),
        ],
        "main": ("PrisonerOccupancyPercent", "AtMost", 75),
        "adviser": 133,
    },
    "POWER02": {"main": ("HighestGenCapacity", "AtLeast", 85), "adviser": 134},
    "STAFF01": {"main": ("ExhaustedStaffPercent", "AtLeast", 50), "adviser": 132},
    "PRISONERS03": {
        "main": ("PrisonerCellQualityPercent", "Below", 25),
        "adviser": 132,
    },
    "DEATHROW01": {
        "extras": [_DAY14, ("Cash", "Below", 100000)],
        "adviser": 132,
    },
    "OBJECTS04": {
        "extras": [_DAY14],
        "objects": (("Servo",), 1),
        "invert": True,
        "adviser": 133,
    },
    "DOCTOR01": {
        "extras": [("TotalRoomTypeCount", "MedicalWard", 1)],
        "objects": (("Doctor",), 1),
        "invert": True,
        "adviser": 132,
    },
    "OBJECTS01": {
        "extras": [_DAY14, ("Prisoners", "AtLeast", 25)],
        "objects": (("Sprinkler",), 1),
        "invert": True,
        "adviser": 132,
    },
    "OBJECTS03": {
        "extras": [_DAY14, ("Prisoners", "AtLeast", 25), ("FogOfWar", None, 1)],
        "objects": (("Cctv", "CctvCamo"), 8),
        "invert": True,
        "adviser": 133,
    },
    "OBJECTS02": {
        "extras": [_DAY14, ("Prisoners", "AtLeast", 25)],
        "objects": (("Bin", "RecyclingBin"), 1),
        "invert": True,
        "adviser": 132,
    },
}


ADVISER_TYPES = {
    132: "Warden",
    133: "Chief",
    134: "Foreman",
    135: "Psychologist",
    136: "Psychiatrist",
    137: "Accountant",
}
"""The ``adviser`` id of an alert is the object type of the staff member who speaks
(132 is ``Warden`` in the object table; confirmed ids, names by that table). The alert
system checks (``sub_140396850``) that such a staff member exists before it raises
the alert (inferred from the call; the check itself was not decoded)."""


def adviser_present(name: str, save: Node) -> bool:
    """Whether the staff member who would raise alert ``name`` is hired (inferred)."""
    spec = ALERTS.get(name) or {}
    who = ADVISER_TYPES.get(spec.get("adviser", 0))
    return who is not None and object_count(save.get("/Objects"), who) > 0


def measure(category: str, prop: str | None, save: Node) -> float | None:
    """The number the game compares for one requirement, or ``None`` when this
    module cannot compute it (unsupported category, missing data).

    ``save`` is the root ``Save`` dict (``/Objects``, ``/Rooms``, ``TimeIndex``,
    ``Balance`` ...). Supported: TimeIndex, Cash, Prisoners, PrisonersPerGuard,
    ExhaustedStaff(Percent), Critical/HighNeedsPercent, TotalRoomTypeCount, Doctors.
    Prisoners is the living prisoner count (inferred: ``Prison+1560 -> +436``).
    """
    objects = save.get("/Objects")
    if category == "TimeIndex":
        return float(save.get("TimeIndex", 0.0))
    if category == "Cash":
        return min(float(save.get("Balance", 0.0)), 2000000000.0)
    if category == "Prisoners":
        return float(len(prisoners(objects)))
    if category == "PrisonersPerGuard":
        value = prisoners_per_guard(objects)
        return None if value is None else float(value)
    if category == "ExhaustedStaff":
        return float(exhausted_staff(objects)["exhausted"])
    if category == "ExhaustedStaffPercent":
        value = exhausted_percent(objects)
        return None if value is None else float(value)
    if category == "TotalRoomTypeCount" and prop:
        return float(
            sum(1 for r in iter_nodes(save.get("/Rooms")) if r.get("RoomType") == prop)
        )
    if category in INDEXED and prop:
        value = needs_percent(
            objects, prop, "critical" if category.startswith("Critical") else "high"
        )
        return None if value is None else float(value)
    if category == "Doctors":
        return float(object_count(objects, "Doctor"))
    return None


def _holds(category: str, prop: str | None, value: float, save: Node) -> bool | None:
    got = measure(category, prop, save)
    if got is None:
        return None
    if category in INDEXED or category == "TotalRoomTypeCount":
        return got >= value
    op = OPERATORS.get(prop or "AtLeast")
    return None if op is None else bool(op(got, value))


def evaluate_alert(name: str, save: Node) -> bool | None:
    """Whether the staff alert ``name`` (``NEEDS08`` ...) is raised now.

    Confirmed: the alert system (``sub_140391DD0``) evaluates the extra requirements
    one by one and, when all hold, the main objective; an alert whose objective is
    built with ``invert`` (the "missing object" ones) is raised when the main
    requirement is *not* met. The 30 s / 8 h spacing, the urgent state after a day and
    the adviser queue are not modelled. Inferred: the problem-when-met reading for the
    non-inverted ones (it matches every title in ``d11_staffalert_title_*``).
    Returns ``None`` when a needed measure is unsupported (see ``measure``).
    """
    spec = ALERTS.get(name)
    if spec is None:
        return None
    for category, prop, value in spec.get("extras", []):
        if category == "FogOfWar":
            continue  # a game option, assumed on
        ok = _holds(category, prop, value, save)
        if ok is None:
            return None
        if not ok:
            return False
    if "objects" in spec:
        types, count = spec["objects"]
        have = object_count(save.get("/Objects"), *types) >= count
        return have != spec.get("invert", False)
    if "main" not in spec:
        return None  # DEATHROW01: the main requirement is not in the decompiled setup
    category, prop, value = spec["main"]
    met = _holds(category, prop, value, save)
    if met is None:
        return None
    return met != spec.get("invert", False)


def active_alerts(save: Node) -> dict[str, list[str]]:
    """Evaluate every known alert.

    ``raised``: condition met and the adviser is hired; ``no_adviser``: condition met
    but nobody to speak; ``clear``; ``unknown``: a measure is unsupported. This is the
    *condition*; the game shows alerts one at a time, at least 30 game minutes apart
    (confirmed constants in ``sub_140391DD0``), so fewer appear in the Todo list.
    """
    result: dict[str, list[str]] = {
        "raised": [],
        "no_adviser": [],
        "clear": [],
        "unknown": [],
    }
    for name in ALERTS:
        state = evaluate_alert(name, save)
        if state is None:
            key = "unknown"
        elif not state:
            key = "clear"
        else:
            key = "raised" if adviser_present(name, save) else "no_adviser"
        result[key].append(name)
    return result


# ---------------------------------------------------------------- text


def _fmt(key: str, **values: Any) -> str:
    """The game text of ``key`` with ``*X`` / ``*Y`` replaced (language files use
    ``*X`` for the first number)."""
    text = TEXT.get(key, key)
    for letter, value in values.items():
        text = text.replace(f"*{letter}", str(value))
    return text


def build_items(save: Node, punishments: Mapping[str, int] | None = None) -> list[dict]:
    """The items this module can reproduce from a ``Save`` root, in the game's order:
    Incident Reports, Prisoner Parole, Staff Exhausted. ``punishments`` may hold
    ``solitary``, ``solitary_queue`` and ``lockdown`` counts."""
    objects = save.get("/Objects")
    punish = dict(punishments or {})
    items = [incident_counts(objects, **punish)]
    parole = parole_due(objects)
    if parole:
        items.append(
            {
                "id": "PrisonersLeaving",
                "title": TEXT.get("objective_prisonerparole", "Prisoner Parole"),
                "visible": True,
                "parole": len(parole),
                "names": [prisoner_name(p) for p in parole],
                "lines": [_fmt("objective_parole_count", X=len(parole))],
            }
        )
    items.append(staff_exhausted_item(objects, save.get("/Rooms")))
    return [i for i in items if i.get("visible")]
