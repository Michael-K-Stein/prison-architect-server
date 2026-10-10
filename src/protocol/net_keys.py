"""Long names for the short keys of the host's live snapshots.

The host's game classes register each synced field twice: under its long save
name (``SubType``) and under a short network key (``st``), both bound to the
same member offset in the object. Pairing them by offset in the binary
(journal2 "Short snapshot keys") gives the names below. ``ObjectData`` mixes
several classes, so a few keys mean one thing per class (``ct``, ``op``, ``s``,
``ts``); those list all readings. ``?`` marks a field the binary registers
without a save name, so only its type and the capture values are known.
"""

from __future__ import annotations

KEYS: dict[str, dict[str, str]] = {
    "ObjectData": {
        # WorldObject (every object), fn 0x1407D1E10
        "uId": "Id: the object's unique id",
        "t": "Type: object type id",
        "st": "SubType",
        "c": "Carried: index of the object it carries",
        "l": "Loaded: sits on a carrier",
        "cr": "carrier: the object carrying it (? no save name)",
        "wa": "Walls: wall sides around it",
        "da": "Damage",
        "h": "Hidden",
        "g": "Garbage",
        "a": "? bool (member +114, no save name)",
        "ttt": "? bool (member +411, no save name)",
        "dry": "Dryness",
        "inst": "? bool, default true (installed?)",
        "sl": "Slot: carried object slot 0-19 (sl0 ... sl19)",
        "d": "Dest: where it is walking to (d.x, d.y)",
        # Person (prisoners, staff), fn 0x14052F7B0
        "eq": "Equipment",
        "cae": "ActionEquipment",
        "ji": "JobId",
        "sta": "Station",
        "ba": "BodyArmour",
        "sh": "Shackled",
        "ci": "Carrying: the object a person carries",
        "el": "Energy",
        "rs": "RestState",
        "rt": "ReloadTimer",
        "ait": "AiSetTarget",
        "nidto": "NavigatingInsideDueToOrder",
        "fa": "FirstAidBackpack",
        "ieu": "IsEmergencyUnit",
        "ud": "UnlockingDoor",
        "gjt": "GritJobTimer",
        "eit": "ExtendedInfirmaryTime",
        "la": "? vector (member +784)",
        "esr": "? (member +952)",
        # Needs, fn 0x14061EFA0
        "nedt": "Timer (needs)",
        "ca": "Action (needs)",
        "cp": "Complaining",
        "late": "LastAte",
        # container, door, search, vehicle
        "ct": "Contents (container) | Target (needs)",
        "op": "Opened (container) | Open (door)",
        "rp": "RequiresPlayerToOpen",
        "po": "PlayerOpened (door)",
        "dm": "Mode (door)",
        "rba": "KeycardDoorAccess (door)",
        "s": "State (vehicle) | Shakedown (search)",
        "ss": "SoundState (vehicle)",
        "ts": "TargetSector (person) | TunnelSearch (search)",
        "db": "DrugBust (search)",
        "sm": "SearchJobsMax (search)",
        "sc": "? (search, member +100)",
        "sj": "? (search, member +104)",
        "si": "? (search, member +108)",
        "tun": "? (search, member +248)",
    },
    "StaffAlert": {
        "tts": "summary text key (language file)",
        "ts": "? detail text key (guess)",
        "aa": "staff object type the alert is about",
    },
    "MisconductSystem": {
        "twi": "float, game seconds, advances with game speed (journal2 `twi`)",
        "tdc": "? (member +108)",
        "pil": "?",
        "pis": "?",
        "prs": "?",
    },
    "EffectsSystem": {
        "p": "position (p.x, p.y)",
        "o": "direction (o.x, o.y; unit vector in captures)",
        "v": "velocity (v.x, v.y)",
        "l": "? 60.0 in captures (lifetime?)",
    },
}
"""System -> short key -> long name and note."""


def long_name(system: str, key: str) -> str | None:
    """The long name of ``key`` (``sl3.i`` -> ``Slot3.i``) in ``system``, or None."""
    names = KEYS.get(system)
    if not names:
        return None
    base, dot, suffix = key.partition(".")
    if base in names:
        note = names[base]
        name = note.split(":")[0] if ":" in note else note
    elif base.startswith("sl") and base[2:].isdigit():
        name = f"Slot{base[2:]}"
    else:
        return None
    return name + dot + suffix
