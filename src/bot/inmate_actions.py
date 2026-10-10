"""Things the player can do to one inmate (the inmate panel in the game).

Each is one RPC on the inmate's ObjectId, taken from ``captures/inmate-actions.sqlite``
(journal2 "Inmate actions"):

* security group: ``ApplyPrisonerCategory(inmate, group)`` (the game sends it twice)
* search the inmate / cell / cell block: ``PerformAction(inmate, 7 | 8 | 9)``
* lockdown / solitary: ``ApplyPunishment(inmate, 1 | 2, duration)``;
  ``ClearAllPunishments(inmate)`` ends them
* escort to a spot (the infirmary ...): ``PlayerSetsTarget(index, x, y, False, inmate)``
* move to a cell / swap two inmates' cells: ``QuickCellChange(inmate, cell room)``,
  once per inmate (the room is an ObjectId ``uId,index``)
* assign / unassign a guard: ``AssignGuardToPrisoner(inmate)`` /
  ``UnassignGuardFromPrisoner(inmate)`` (the host picks the guard)
"""

from __future__ import annotations

from typing import Any

SECURITY_CODES = {
    "MinSec": 1,
    "Normal": 2,
    "MaxSec": 3,
    "Protected": 4,
    "SuperMax": 5,
}
"""Security group -> the ``ApplyPrisonerCategory`` argument. Captured: Normal = 2 and
SuperMax = 5; the others follow the game's order (``None`` = 0, as in the uniform
colours), unconfirmed."""
SECURITY_NAMES = {
    "MinSec": "Minimum",
    "Normal": "Medium",
    "MaxSec": "Maximum",
    "Protected": "Protective Custody",
    "SuperMax": "SuperMax",
}
"""How the game words each group."""

PERFORM = {"search": 7, "search-cell": 8, "search-block": 9}
"""Command -> the ``PerformAction`` argument (captured: search an inmate = 7, search an
inmate's cell = 8, an inmate's cell block = 9)."""
GUARD = {
    "assign-guard": "AssignGuardToPrisoner",
    "unassign-guard": "UnassignGuardFromPrisoner",
    "clear-punishments": "ClearAllPunishments",
}
"""Command -> the RPC that takes only the inmate."""


PUNISHMENTS = {"lockdown": (1, 60), "solitary": (2, 60)}
"""Command -> (``ApplyPunishment`` type, duration minutes per hour). Captured: lockdown
for 6 hours = ``1, 360`` and solitary for 6 hours = ``2, 360``."""
LOCKDOWN = PUNISHMENTS["lockdown"][0]
PERMANENT = 500000
"""Solitary duration of "permanent" (captured: 2, 500000)."""


def punishment_args(command: str, hours: str | None) -> list[str]:
    """The ``ApplyPunishment`` arguments after the inmate; ``ValueError`` if ``hours``
    is not a positive number."""
    kind, per_hour = PUNISHMENTS[command]
    if str(hours).lower() in ("permanent", "forever"):
        return [str(kind), str(PERMANENT)]
    try:
        duration = round(float(hours) * per_hour)
    except (TypeError, ValueError):
        duration = 0
    if duration <= 0:
        raise ValueError(f"{command} needs a number of hours, not {hours!r}")
    return [str(kind), str(duration)]


COMMANDS = (
    "security",
    *PERFORM,
    *GUARD,
    *PUNISHMENTS,
    "cell",
    "swap-cells",
    "escort",
)
"""Every inmate command."""


def security_group(text: str) -> str:
    """A group by save name or the game's wording (case-insensitive); ``ValueError`` if
    unknown."""
    wanted = text.strip().lower()
    for key, label in SECURITY_NAMES.items():
        if wanted in (key.lower(), label.lower()):
            return key
    raise ValueError(
        f"unknown security group {text!r}; one of {', '.join(SECURITY_CODES)}"
    )


def request(command: str, argument: str | None = None) -> tuple[str, list[str]]:
    """``(RPC name, arguments after the inmate)`` for the command (``security
    <group>``, ``lockdown <hours>``, ``search`` ...); ``ValueError`` when malformed."""
    if command == "security":
        if argument is None:
            raise ValueError("security needs a group: " + ", ".join(SECURITY_CODES))
        return "ApplyPrisonerCategory", [str(SECURITY_CODES[security_group(argument)])]
    if command in GUARD:
        return GUARD[command], []
    if command in PERFORM:
        return "PerformAction", [str(PERFORM[command])]
    if command in PUNISHMENTS:
        return "ApplyPunishment", punishment_args(command, argument)
    raise ValueError(
        f"unknown inmate command {command!r}; one of {', '.join(COMMANDS)}"
    )


def _name(node: Any) -> str:
    bio = node.children.get("Bio")
    fields = bio.fields if bio is not None else {}
    parts = (fields.get("Forname", ""), fields.get("Surname", ""))
    return " ".join(
        p.decode("utf-8", "replace") if isinstance(p, bytes) else str(p) for p in parts
    ).strip()


def inmates(state: Any) -> list[tuple[int, str]]:
    """``(object index, full name)`` of every prisoner in the last save."""
    with state.lock:
        objects = state.save.children.get("Objects") if state.save else None
        out = []
        for key, node in objects.children.items() if objects else ():
            kind = node.fields.get("Type", "")
            kind = kind.decode() if isinstance(kind, bytes) else str(kind)
            if kind == "Prisoner" and key.startswith("[i "):
                out.append((int(key[3:-1]), _name(node)))
    return sorted(out, key=lambda t: t[1].lower())


def find_inmate(state: Any, who: str) -> tuple[int, str]:
    """The inmate named ``who`` (a name part, case-insensitive) or ``#index``;
    ``ValueError`` when none or several match."""
    known = inmates(state)
    text = who.strip().lstrip("#")
    if text.isdigit():
        for index, name in known:
            if index == int(text):
                return index, name
        raise ValueError(f"no inmate #{text} in the save (`ctl refresh`?)")
    words = text.lower().split()
    hits = [(i, n) for i, n in known if all(w in n.lower() for w in words)]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise ValueError(
            f"no inmate matches {who!r} (`ctl refresh` after new arrivals)"
        )
    exact = [h for h in hits if h[1].lower() == text.lower()]
    if len(exact) == 1:
        return exact[0]
    raise ValueError(
        f"{who!r} matches several: " + ", ".join(f"{n} (#{i})" for i, n in hits[:8])
    )


def cell_of(state: Any, inmate: int) -> tuple[int, int] | None:
    """``(uId, index)`` of the room whose assigned prisoner (``Entity.i``) is ``inmate``."""
    for room in state.room_list():
        index = room["index"]
        if room["occupant"] == inmate and index is not None:
            uid = state.room_uid(index)
            return (uid, index) if uid is not None else None
    return None


def room_id(state: Any, index: int) -> tuple[int, int]:
    """``(uId, index)`` of room ``index``; ``ValueError`` if the save has no such room."""
    uid = state.room_uid(index)
    if uid is None:
        raise ValueError(f"no room #{index} in the save (`ctl refresh`?)")
    return uid, index
