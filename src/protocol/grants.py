"""Every grant the game can offer, for ``AcceptGrant`` (a string argument).

Generated from the game's ``data/grants.lua`` (inside ``main.dat``) plus the DLC grant
names found in the binary. The argument is the grant's **objective name with its
``Grant_`` prefix** (``AcceptGrant("Grant_GreenMachine")`` completed that grant at once
in MKS2; the bare ``GreenMachine`` / ``bootstraps`` do nothing, journal2 "Grants by
name"). ``start``/``completion`` are the payments in dollars (``Objective.CreateGrant``
args), ``requires`` the prerequisite grants/unlocks, ``tasks`` the sub-objectives
(``Grant_<name>_<task>``) with the script condition when ``grants.lua`` has it.
"""

from __future__ import annotations

from typing import Any

GRANTS: dict[str, dict[str, Any]] = {
    "Grant_bootstraps": {
        "title": "Basic Detention Centre",
        "start": 20000,
        "completion": 10000,
        "requires": [],
        "tasks": [
            (
                "Grant_bootstraps_holdingcell",
                'RequireEitherRoom("PaddedHoldingCell", "HoldingCell", true)',
            ),
            ("Grant_bootstraps_shower", 'RequireRoom("Shower", true)'),
            ("Grant_bootstraps_yard", 'RequireRoom("Yard", true)'),
            ("Grant_bootstraps_kitchen", 'RequireRoom("Kitchen", true)'),
            ("Grant_bootstraps_canteen", 'RequireRoom("Canteen", true)'),
            ("Grant_bootstraps_guard", 'RequireObjects("Guard", 2)'),
            ("Grant_bootstraps_chef", 'RequireObjects("Cook", 2)'),
        ],
    },
    "Grant_Administration": {
        "title": "Administration Centre",
        "start": 5000,
        "completion": 5000,
        "requires": [],
        "tasks": [
            ("Grant_Administration_offices", 'RequireRoomsAvailable("Office", 2)'),
            ("Grant_Administration_Warden", 'RequireObjects("Warden", 1)'),
            (
                "Grant_Administration_Accountant_Research",
                'RequireResearched("Finance")',
            ),
            ("Grant_Administration_Accountant", 'RequireObjects("Accountant", 1)'),
        ],
    },
    "Grant_FirstCellBlock": {
        "title": "Cell Block A",
        "start": 20000,
        "completion": 20000,
        "requires": [("Completed", "Grant_bootstraps", 0), ("Unlocked", "Finance", 0)],
        "tasks": [("Grant_FirstCellBlock_Cells", "RequirePrisonerCapacity(15)")],
    },
    "Grant_Health": {
        "title": "Inmate Health and Well Being",
        "start": 10000,
        "completion": 10000,
        "requires": [],
        "tasks": [
            ("Grant_Health_Ward", 'RequireRoom("MedicalWard", true)'),
            ("Grant_Health_Doctors", 'RequireObjects("Doctor", 2)'),
            ("Grant_Health_Psychologist", 'RequireObjects("Psychologist", 1)'),
        ],
    },
    "Grant_Bailout": {
        "title": "Government Bailout",
        "start": 50000,
        "completion": 50000,
        "requires": [
            ("Cash", "AtMost", 500),
            ("Cashflow", "AtMost", 0),
            ("Debt", "AtLeast", 10000),
            ("Prisoners", "AtLeast", 30),
        ],
        "tasks": [
            ("Grant_Bailout_Cashflow", 'Requires("Cashflow", "AtLeast", 100)'),
            ("Grant_Bailout_Debt", 'Requires("Debt", "AtMost", 0)'),
        ],
    },
    "Grant_Maintenance": {
        "title": "Prison Maintenance",
        "start": 10000,
        "completion": 5000,
        "requires": [("Completed", "Grant_bootstraps", 0)],
        "tasks": [
            ("Grant_Maintenance_Research_Root", 'RequireResearched("Maintainance")'),
            ("Grant_Maintenance_Research_Cleaning", 'RequireResearched("Cleaning")'),
            (
                "Grant_Maintenance_Research_GroundsKeeping",
                'RequireResearched("GroundsKeeping")',
            ),
            ("Grant_Maintenance_Foreman", 'RequireObjects("Foreman", 1)'),
            ("Grant_Maintenance_Janitor", 'RequireObjects("Janitor", 2)'),
            ("Grant_Maintenance_Gardener", 'RequireObjects("Gardener", 1)'),
        ],
    },
    "Grant_Visitation": {
        "title": "Visitation Rights",
        "start": 5000,
        "completion": 5000,
        "requires": [("Completed", "Grant_bootstraps", 0)],
        "tasks": [
            ("Grant_Visitation_Room", 'RequireRoom("Visitation", true)'),
            (
                "Grant_Visitation_Tables",
                'RequireObjectsWithAlt("VisitorTable", 3, "VisitorTableSecure")',
            ),
            ("Grant_Visitation_CommonRoom", 'RequireRoom("CommonRoom", true)'),
            ("Grant_Visitation_PoolTable", 'RequireObjects("PoolTable", 1)'),
            ("Grant_Visitation_TV", 'RequireObjectsWithAlt("Tv", 2, "LargeTv")'),
            ("Grant_Visitation_Phones", 'RequireObjects("PhoneBooth", 5)'),
        ],
    },
    "Grant_BasicSecurity": {
        "title": "Security Procedure Certification",
        "start": 10000,
        "completion": 10000,
        "requires": [("Completed", "Grant_bootstraps", 1)],
        "tasks": [
            ("Grant_BasicSecurity_Chief", 'RequireObjects("Chief", 1)'),
            ("Grant_BasicSecurity_Guards", 'RequireObjects("Guard", 10)'),
            ("Grant_BasicSecurity_Research", 'RequireResearched("Patrols")'),
            ("Grant_BasicSecurity_Patrols", 'Requires("PatrolGuards", "AtLeast", 3)'),
        ],
    },
    "Grant_EnhancedSecurity": {
        "title": "Governmental Security Ratings",
        "start": 15000,
        "completion": 15000,
        "requires": [("Completed", "Grant_BasicSecurity", 1)],
        "tasks": [
            (
                "Grant_EnhancedSecurity_PatrolDogs",
                'Requires("PatrolDogs", "AtLeast", 2)',
            ),
            (
                "Grant_EnhancedSecurity_PatrolArmed",
                'Requires("PatrolArmed", "AtLeast", 2)',
            ),
        ],
    },
    "Grant_AdvancedSecurity": {
        "title": "Max-Sec Infrastructure Implementation",
        "start": 20000,
        "completion": 20000,
        "requires": [("Completed", "Grant_EnhancedSecurity", 1)],
        "tasks": [
            ("Grant_AdvancedSecurity_Guards", 'RequireObjects("Guard", 20)'),
            (
                "Grant_AdvancedSecurity_ResearchBodyArmour",
                'RequireResearched("BodyArmour")',
            ),
            ("Grant_AdvancedSecurity_ResearchTazers", 'RequireResearched("Tazers")'),
            ("Grant_AdvancedSecurity_CCTVMonitor", 'RequireObjects("CctvMonitor", 1)'),
            (
                "Grant_AdvancedSecurity_CCTVCameras",
                'RequireObjectsWithAlt("Cctv", 6, "CctvCamo", "AdvancedSearchLight")',
            ),
        ],
    },
    "Grant_PrisonerWorkforce": {
        "title": "Prisoner Acclimatization and Engagement",
        "start": 10000,
        "completion": 10000,
        "requires": [("Completed", "Grant_Maintenance", 1)],
        "tasks": [
            (
                "Grant_PrisonerWorkforce_LaundryAssigned",
                'Requires("PrisonerJobs", "Laundry", 3)',
            ),
            (
                "Grant_PrisonerWorkforce_KitchenAssigned",
                'Requires("PrisonerJobs", "Kitchen", 3)',
            ),
            (
                "Grant_PrisonerWorkforce_CleaningAssigned",
                'Requires("PrisonerJobs", "CleaningCupboard", 3)',
            ),
        ],
    },
    "Grant_EducationReformProgram": {
        "title": "The Reform through Education Initiative",
        "start": 15000,
        "completion": 40000,
        "requires": [("Completed", "Grant_Administration", 1)],
        "tasks": [
            ("Grant_EducationReformProgram_Research", 'RequireResearched("Education")'),
            (
                "Grant_EducationReformProgram_Classroom",
                'RequireRoom("Classroom", true)',
            ),
            ("Grant_EducationReformProgram_Desks", 'RequireObjects("SchoolDesk", 20)'),
            (
                "Grant_EducationReformProgram_FoundationEd",
                'Requires("ReformPassed", "FoundationEducation", 10)',
            ),
            (
                "Grant_EducationReformProgram_GeneralEd",
                'Requires("ReformPassed", "GeneralEducation", 1)',
            ),
        ],
    },
    "Grant_PrisonLabour": {
        "title": "Prison Manufacturing Facility",
        "start": 20000,
        "completion": 10000,
        "requires": [("Completed", "Grant_PrisonerWorkforce", 1)],
        "tasks": [
            ("Grant_PrisonLabour_Plates", 'RequireManufactured("LicensePlate", 30)')
        ],
    },
    "Grant_FurnitureManufacturing": {
        "title": "Carpentry Apprenticeship Program",
        "start": 10000,
        "completion": 10000,
        "requires": [("Completed", "Grant_PrisonLabour", 1)],
        "tasks": [
            (
                "Grant_FurnitureManufacturing_Bed",
                'RequireManufactured("SuperiorBed", 10)',
            )
        ],
    },
    "Grant_ReduceStaffStress": {
        "title": "Staff Well-being Initiative",
        "start": 0,
        "completion": 10000,
        "requires": [],
        "tasks": [
            ("Grant_ReduceStaffStress_Staffroom", 'RequireRoom("Staffroom", true)'),
            (
                "Grant_ReduceStaffStress_FreeGuards",
                'Requires("AvailableGuards", "AtLeast", 5)',
            ),
            (
                "Grant_ReduceStaffStress_RestedStaff",
                'Requires("ExhaustedStaffPercent", "AtMost", 5)',
            ),
        ],
    },
    "Grant_ShortTermInvestment": {
        "title": "Short-term Investment",
        "start": -5000,
        "completion": 16000,
        "requires": [("Unlocked", "Finance", 0)],
        "tasks": [("Grant_ShortTermInvestment_Wait", "RequireTimePassed(4320)")],
    },
    "Grant_LongTermInvestment": {
        "title": "Long-term Investment",
        "start": -5000,
        "completion": 16000,
        "requires": [("Unlocked", "Finance", 0)],
        "tasks": [("Grant_LongTermInvestment_Wait", "RequireTimePassed(10080)")],
    },
    "Grant_NutritionResearch": {
        "title": "Inmate Nutrition Research",
        "start": 0,
        "completion": 15000,
        "requires": [
            ("Unlocked", "Health", 0),
            ("Unlocked", "MentalHealth", 0),
            ("Prisoners", "AtLeast", 20),
        ],
        "tasks": [
            ("Grant_NutritionResearch_Poor", "RequireSetMeals(1)"),
            ("Grant_NutritionResearch_Good", "RequireSetMeals(3)"),
        ],
    },
    "Grant_DrugSearch": {
        "title": "Crackdown on Drugs",
        "start": 0,
        "completion": 15000,
        "requires": [("Prisoners", "AtLeast", 30)],
        "tasks": [
            ("Grant_DrugSearch_Find", 'Requires("ContrabandFound", "Narcotics", 10)')
        ],
    },
    "Grant_ContrabandSupply": {
        "title": "Tool Cleanup",
        "start": 0,
        "completion": 20000,
        "requires": [("Prisoners", "AtLeast", 40)],
        "tasks": [
            (
                "Grant_ContrabandSupply_Tools",
                'Requires("ContrabandSupply", "Tools", 0)',
            ),
            (
                "Grant_ContrabandSupply_Weapons",
                'Requires("ContrabandSupply", "Weapons", 0)',
            ),
        ],
    },
    "Grant_CellBlock50": {
        "title": "Cell Block B",
        "start": 10000,
        "completion": 20000,
        "requires": [("Completed", "Grant_FirstCellBlock", 1)],
        "tasks": [("Grant_CellBlock50_Cells", "RequirePrisonerCapacity(50)")],
    },
    "Grant_CellBlock100": {
        "title": "Cell Block C",
        "start": 10000,
        "completion": 20000,
        "requires": [("Completed", "Grant_CellBlock50", 1)],
        "tasks": [("Grant_CellBlock100_Cells", "RequirePrisonerCapacity(100)")],
    },
    "Grant_CellBlock200": {
        "title": "Cell Block D",
        "start": 10000,
        "completion": 20000,
        "requires": [("Completed", "Grant_CellBlock100", 1)],
        "tasks": [("Grant_CellBlock200_Cells", "RequirePrisonerCapacity(200)")],
    },
    "Grant_CellBlock500": {
        "title": "Cell Block E",
        "start": 10000,
        "completion": 20000,
        "requires": [("Completed", "Grant_CellBlock200", 1)],
        "tasks": [("Grant_CellBlock500_Cells", "RequirePrisonerCapacity(500)")],
    },
    "Grant_EcoFriendly": {
        "title": "Eco Friendly",
        "start": None,
        "completion": None,
        "requires": [],
        "tasks": [("Grant_EcoFriendly_Days", None)],
    },
    "Grant_FirstInsaneCellBlock": {
        "title": "Criminally Insane Wing",
        "start": None,
        "completion": None,
        "requires": [],
        "tasks": [
            ("Grant_FirstInsaneCellBlock_Cells", None),
            ("Grant_FirstInsaneCellBlock_Psychiatrist", None),
            ("Grant_FirstInsaneCellBlock_prisoners", None),
        ],
    },
    "Grant_GivingSomethingBack": {
        "title": "Giving Something Back",
        "start": None,
        "completion": None,
        "requires": [],
        "tasks": [("Grant_GivingSomethingBack_Sell", None)],
    },
    "Grant_GreenMachine": {
        "title": "Green Machine",
        "start": None,
        "completion": None,
        "requires": [],
        "tasks": [
            ("Grant_GreenMachine_Hybrid", None),
            ("Grant_GreenMachine_Solar", None),
            ("Grant_GreenMachine_Wind", None),
        ],
    },
    "Grant_TrackerPilot": {
        "title": None,
        "start": None,
        "completion": None,
        "requires": [],
        "tasks": [],
    },
}
"""Grant objective name -> title, payments, prerequisites and tasks."""

_BY_LOWER = {name.lower(): name for name in GRANTS}


def canonical(text: str) -> str:
    """The grant's full objective name for what a user typed.

    ``greenmachine``, ``GreenMachine`` and ``Grant_GreenMachine`` all give
    ``Grant_GreenMachine``; anything unknown is returned with ``Grant_`` added, so the
    host decides (live ``target_*`` goals keep their own prefix).
    """
    raw = text.strip()
    if raw.startswith("target_"):
        return raw
    bare = raw.removeprefix("Grant_").removeprefix("grant_")
    found = _BY_LOWER.get(f"grant_{bare}".lower())
    return found or f"Grant_{bare}"
