"""Research rules from the game's ``data/research.txt`` (and ``research_dlc.txt``).

Generated. ``admin`` is the staff member who must be employed (and in his
office) before the research can progress; ``requires`` the research that must
be finished first; ``cost`` is charged up front on ``BeginResearch`` (the file
stores it negative); ``time`` is the research time (units of the file).
Entries with no cost (Warden) are starting items.
"""

from __future__ import annotations

RESEARCH_RULES: dict[str, dict[str, str | int | None]] = {
    "Warden": {
        "type": "Entity",
        "requires": None,
        "admin": None,
        "cost": None,
        "time": None,
    },
    "Maintainance": {
        "type": "Entity",
        "requires": "Warden",
        "admin": "Warden",
        "cost": 500,
        "time": 360,
    },
    "Security": {
        "type": "Entity",
        "requires": "Warden",
        "admin": "Warden",
        "cost": 500,
        "time": 360,
    },
    "Legal": {
        "type": "Entity",
        "requires": "Warden",
        "admin": "Warden",
        "cost": 5000,
        "time": 720,
    },
    "MentalHealth": {
        "type": "Entity",
        "requires": "Warden",
        "admin": "Warden",
        "cost": 500,
        "time": 360,
    },
    "Finance": {
        "type": "Entity",
        "requires": "Warden",
        "admin": "Warden",
        "cost": 500,
        "time": 360,
    },
    "Cctv": {
        "type": "Ability",
        "requires": "Security",
        "admin": "Security",
        "cost": 2000,
        "time": 360,
    },
    "RemoteAccess": {
        "type": "Ability",
        "requires": "Security",
        "admin": "Security",
        "cost": 2000,
        "time": 360,
    },
    "Health": {
        "type": "Entity",
        "requires": "Warden",
        "admin": "Warden",
        "cost": 500,
        "time": 360,
    },
    "Cleaning": {
        "type": "Entity",
        "requires": "Maintainance",
        "admin": "Maintainance",
        "cost": 2000,
        "time": 360,
    },
    "GroundsKeeping": {
        "type": "Entity",
        "requires": "Maintainance",
        "admin": "Maintainance",
        "cost": 2000,
        "time": 360,
    },
    "Deployment": {
        "type": "Ability",
        "requires": "Security",
        "admin": "Security",
        "cost": 1000,
        "time": 360,
    },
    "Patrols": {
        "type": "Ability",
        "requires": "Security",
        "admin": "Security",
        "cost": 1000,
        "time": 360,
    },
    "Dogs": {
        "type": "Entity",
        "requires": "Patrols",
        "admin": "Security",
        "cost": 1000,
        "time": 360,
    },
    "PrisonLabour": {
        "type": "Ability",
        "requires": "Maintainance",
        "admin": "Maintainance",
        "cost": 1000,
        "time": 360,
    },
    "Education": {
        "type": "Ability",
        "requires": "Warden",
        "admin": "Warden",
        "cost": 2000,
        "time": 720,
    },
    "LandExpansion": {
        "type": "Ability",
        "requires": "Finance",
        "admin": "Finance",
        "cost": 1000,
        "time": 720,
    },
    "Contraband": {
        "type": "Ability",
        "requires": "Security",
        "admin": "Security",
        "cost": 1000,
        "time": 360,
    },
    "Policy": {
        "type": "Ability",
        "requires": "Warden",
        "admin": "Warden",
        "cost": 1000,
        "time": 360,
    },
    "Armoury": {
        "type": "Entity",
        "requires": "Security",
        "admin": "Security",
        "cost": 2000,
        "time": 720,
    },
    "BodyArmour": {
        "type": "Ability",
        "requires": "Armoury",
        "admin": "Security",
        "cost": 1000,
        "time": 360,
    },
    "Tazers": {
        "type": "Ability",
        "requires": "Armoury",
        "admin": "Security",
        "cost": 1000,
        "time": 360,
    },
    "TazersForEveryone": {
        "type": "Ability",
        "requires": "Tazers",
        "admin": "Security",
        "cost": 5000,
        "time": 720,
    },
    "BankLoans": {
        "type": "Ability",
        "requires": "Finance",
        "admin": "Finance",
        "cost": 500,
        "time": 720,
    },
    "LowerTaxes1": {
        "type": "Ability",
        "requires": "Finance",
        "admin": "Finance",
        "cost": 10000,
        "time": 2880,
    },
    "LowerTaxes2": {
        "type": "Ability",
        "requires": "LowerTaxes1",
        "admin": "Finance",
        "cost": 50000,
        "time": 2880,
    },
    "ExtraGrant": {
        "type": "Ability",
        "requires": "Finance",
        "admin": "Finance",
        "cost": 500,
        "time": 360,
    },
    "AdvancedManagement": {
        "type": "Ability",
        "requires": "Warden",
        "admin": "Warden",
        "cost": 1000,
        "time": 360,
    },
    "Deathrow": {
        "type": "Ability",
        "requires": "Legal",
        "admin": "Legal",
        "cost": 10000,
        "time": 1440,
    },
    "PermanentPunishment": {
        "type": "Ability",
        "requires": "Legal",
        "admin": "Legal",
        "cost": 5000,
        "time": 1440,
    },
    "RemoveMinCellSize": {
        "type": "Ability",
        "requires": "Legal",
        "admin": "Legal",
        "cost": 10000,
        "time": 1440,
    },
    "ReduceExecutionLiability": {
        "type": "Ability",
        "requires": "Deathrow",
        "admin": "Legal",
        "cost": 10000,
        "time": 4320,
    },
    "LegalPrep": {
        "type": "Ability",
        "requires": "Legal",
        "admin": "Legal",
        "cost": 50000,
        "time": 4320,
    },
    "LegalDefense": {
        "type": "Ability",
        "requires": "LegalPrep",
        "admin": "Legal",
        "cost": 50000,
        "time": 180,
    },
    "GuardTowers": {
        "type": "Entity",
        "requires": "Armoury",
        "admin": "Security",
        "cost": 5000,
        "time": 1080,
    },
    "NonLethalSniper": {
        "type": "Entity",
        "requires": "GuardTowers",
        "admin": "Security",
        "cost": 5000,
        "time": 360,
    },
    "Orderly": {
        "type": "Entity",
        "requires": "Health",
        "admin": "Warden",
        "cost": 1000,
        "time": 720,
    },
    "ForestryLabour": {
        "type": "Ability",
        "requires": "PrisonLabour",
        "admin": "Maintainance",
        "cost": 1500,
        "time": 360,
    },
    "Farming": {
        "type": "Entity",
        "requires": "Maintainance",
        "admin": "Maintainance",
        "cost": 2000,
        "time": 480,
    },
    "RecyclingIncentive": {
        "type": "Entity",
        "requires": "LowerTaxes1",
        "admin": "Finance",
        "cost": 2500,
        "time": 720,
    },
    "StaffVetting": {
        "type": "Ability",
        "requires": "Security",
        "admin": "Security",
        "cost": 1000,
        "time": 360,
    },
    "CCTVImprovement": {
        "type": "Ability",
        "requires": "Cctv",
        "admin": "Security",
        "cost": 1000,
        "time": 180,
    },
}


ADMIN_STAFF = {
    "Warden": "Warden",
    "Maintainance": "Foreman",
    "Security": "Chief",
    "Legal": "Lawyer",
    "MentalHealth": "Psychologist",
    "Finance": "Accountant",
}
"""``admin`` research -> the staff object (``Sprite`` of that Entity research) who
must be hired and sit in his office for the research to progress: Foreman,
Chief, Lawyer, Psychologist, Accountant (object ids 134, 133, 138, 135, 137)."""


def describe(name: str) -> str | None:
    """One line: what a research needs, or None if unknown."""
    r = RESEARCH_RULES.get(name)
    if r is None:
        return None
    parts = []
    if r["admin"]:
        parts.append(
            f"needs the {ADMIN_STAFF.get(str(r['admin']), r['admin'])} hired"
            " and in his office"
        )
    if r["requires"]:
        parts.append(f"after {r['requires']}")
    if r["cost"] is not None:
        parts.append(f"costs {r['cost']} up front")
    return f"{name}: " + ", ".join(parts or ["no requirements"])
