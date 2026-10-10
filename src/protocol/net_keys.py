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
        # electrical (fn 0x14052C720, 0x140694BE0), crates (0x140727510), mail
        "sw": "Switch",
        "pow": "Powered",
        "on": "On",
        "ep": "ExternalPower",
        "mo": "Moved",
        "dem": "Demand: power drawn",
        "cap": "Capacity: power a PowerStation / Capacitor supplies",
        "pt": "Powertype",
        "qua": "Quantity",
        "mt": "MailType",
        "con": "Contents",
        "dri": "? ObjectId (member +588, crate-like objects)",
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
    "SectorSystem": {
        # Sectors/<sector id>/<list>: each a list of ids (Size + [i N]); the same
        # lists, in the same order, as the save's Sectors/<n> children. Values
        # checked equal for sectors 46 and 66 (journal2 "SectorSystem keys").
        "s": "Stations",
        "ds": "DogStations",
        "as": "ArmedGuardStations",
        "os": "OrderlyStations",
        "cs": "CookStations",
        "docs": "DoctorStations",
        "js": "JanitorStations",
        "gs": "GardenerStations",
        "fs": "FarmerStations",
        "j": "Jobs",
        "cr": "ContainedRooms: room indices inside the sector",
        "l": "Targets: object indices to look at (guard targets)",
    },
    "Thermometer": {
        "t": "Temperature",
        "roc": "RateOfChange (temperature)",
        "sm": "StaffMorale",
        "sroc": "StaffMoraleRateOfChange",
        "ru": "RiotUnderway",
    },
    "VictorySystem": {
        "fc": "FailureCondition",
        "rdt": "RecentDeathTimer",
        "ret": "RecentEscapeTimer",
        "sp": "StaffPayBeforeDemand",
        "npg": "? (member +1112)",
        "rdp": "? (member +1176)",
        "rep": "? (member +1184)",
        "ft": "? (member +1200)",
    },
    "PlayerData": {
        # PlayerData/<actor number>: that player's current tool use, mirrored by
        # the host (observed with a real client in MKS2; no save long names).
        "jp": "JobPosition: the cell under the tool (jp.x, jp.y)",
        "js": "JobStart: cell where a drag began (-1 when not dragging)",
        "p": "Pointer: cursor position in world coordinates (p.x, p.y)",
    },
    "EventLog": {
        # LoggedEvents/i, fn 0x14057E610. No save long names exist: these
        # are descriptive names for what the fields hold.
        "t": "EventType: a code from EVENT_LOG_TYPES",
        "tIdx": "TimeIndex: game minute the event happened",
        "gID": "GroupId: gang id for gang events (? guess), else -1",
        "gID2": "GroupId2: the other gang (? guess), else -1",
        "loc": "Location (loc.x, loc.y; 0 when not tied to a place)",
        "en1": "Entity1: first object involved (en1.i index, en1.u uId)",
        "en2": "Entity2: second object involved, -1 if none",
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


EVENT_LOG_TYPES: dict[str, str] = {
    "pr.d": "prisoner died (guess)",
    "stf.d": "staff died (guess; seen with a location)",
    "pr.ed": "prisoner event 'ed' with gang id (guess; by far the most frequent)",
    "stf.ed": "staff event 'ed' (guess)",
    "pr.gf": "prisoner gang fight (guess)",
    "g.tc": "gang territory change (guess)",
    "g.nl": "gang new leader (guess)",
    "g.ld": "gang leader died (guess)",
    "pr.jg": "prisoner joined gang (guess)",
    "pr.lg": "prisoner left gang (guess)",
    "pr.m": "prisoner gang member/mugged (guess; seen with gID and gID2)",
    "stf.pp": "staff 'pp' event (guess: punched/pepper-sprayed)",
    "pr.pp": "prisoner 'pp' event (guess)",
    "pr.r": "prisoner released (guess)",
    "pr.re": "prisoner released early / re-arrested (guess; fires with pr.r)",
    "pr.reo": "prisoner reoffended (guess)",
    "pr.e": "prisoner escaped (guess)",
    "pr.z": "prisoner zombified (guess)",
    "stf.z": "staff zombified (guess)",
    "infc": "infection (guess)",
    "grvz": "graveyard zombie (guess)",
    "dbug": "debug",
}
"""``EventLog`` ``t`` codes, from the 22 strings the game registers at
``0x140DDC250`` (``sub_1400652C0``). The meanings are guesses from the names and
the captures (counts: pr.ed 37885, pr.r 12009, pr.re 10655, pr.m 2850, stf.d 252,
pr.pp 191)."""

RAW = False
"""When true, keys are shown as the game sends them (``--raw-keys``)."""


def set_raw(raw: bool) -> None:
    """Show original short keys everywhere (the ``--raw-keys`` flag)."""
    global RAW
    RAW = raw


def label(system: str | None, key: str) -> str:
    """``Long name (key)`` for a known short key, else ``key`` (always ``key`` in raw mode)."""
    long = None if RAW or not system else long_name(system, key)
    return f"{long} ({key})" if long and long != key else key


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
