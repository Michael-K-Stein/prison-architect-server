"""Tests for src/bot/todo_items.py; the values are copied from a live save (`ctl state Save`)."""

from __future__ import annotations

from src.bot import todo_items as t


def prisoner(
    forname, sentence, served, parole, damage=None, category="Normal", needs=()
):
    obj = {
        "Type": "Prisoner",
        "Category": category,
        "/Bio": {
            "Forname": forname,
            "Surname": "X",
            "SentenceF": sentence,
            "Served": served,
            "NextParole": parole,
        },
        "/Needs": {
            "/Needs": {
                f"/[i {i}]": {"Type": n, "ActionPoint": ap, "Charge": c}
                for i, (n, ap, c) in enumerate(needs, 1)
            }
        },
    }
    if damage is not None:
        obj["Damage"] = damage
    return obj


def objects(*items):
    out = {"Size": len(items)}
    for i, item in enumerate(items):
        out[f"/[i {i}]"] = item
    return out


def staff(kind, rest=None, **extra):
    obj = {"Type": kind, "Energy": 50.0, **extra}
    if rest is not None:
        obj["RestState"] = rest
    return obj


# The five prisoners the user saw ("1 prisoners up for parole").
LIVE = objects(
    prisoner("Gareth", 6.0, 3.06, "Half"),
    prisoner("Mark", 16.0, 2.83, "Half"),
    prisoner("Mark", 18.0, 7.81, "Half"),
    prisoner("Matt", 15.0, 12.38, "Failed"),
    prisoner("Ben", 25.0, 11.45, "Failed"),
)

NEEDY = objects(
    prisoner(
        "Matt",
        15.0,
        13.0,
        "Failed",
        needs=[("Food", 55.0, 100.0), ("Hygiene", 50.0, 100.0)],
    ),
    prisoner("Chris", 3.0, 1.0, "Half", needs=[("Food", 62.0, 72.0)]),
    prisoner(
        "Dan",
        7.0,
        5.0,
        "ThreeQuarters",
        needs=[("Food", 63.0, 100.0), ("Hygiene", 57.0, 100.0)],
    ),
)


def test_parole_matches_the_game_screen():
    due = t.parole_due(LIVE)
    assert [t.prisoner_name(p) for p in due] == ["Gareth X"]


def test_parole_rules():
    items = objects(
        prisoner("Dead", 6.0, 3.6, "Half", damage=1.0),
        prisoner("Mad", 6.0, 3.6, "Half", category="Insane"),
        prisoner("Short", 1.0, 1.0, "Half"),
        prisoner("Quarter", 7.0, 5.3, "ThreeQuarters"),
        prisoner("NotYet", 7.0, 5.2, "ThreeQuarters"),
        prisoner("Flip", 2.0, 2.0, "ThreeQuarters"),
        prisoner("Done", 6.0, 6.0, "Succeeded"),
        prisoner("Never", 6.0, 6.0, "None"),
    )
    assert [p["/Bio"]["Forname"] for p in t.parole_due(items)] == ["Quarter"]


def test_medical_and_dead():
    items = objects(
        prisoner("Matt", 15.0, 13.0, "Failed", damage=0.7194612622261047),
        prisoner("Gareth", 6.0, 3.7, "Half", damage=1.0),
        prisoner("Mark", 16.0, 3.4, "Half", damage=0.26669418811798096),
        prisoner("Mark", 18.0, 8.4, "Half", damage=0.007407527882605791),
        {"Type": "Guard", "Damage": 0.25},
        {"Type": "Bed", "Damage": 0.9},
    )
    assert t.medical_attention(items) == 2  # Matt and the Mark at 0.2667 (> 0.25)
    assert t.dead_bodies(items) == 1
    item = t.incident_counts(items)
    assert item["visible"]
    assert item["lines"] == ["2 require medical attention", "1 dead bodies"]


def test_incident_item_hidden_with_only_bodies():
    items = objects(prisoner("Gareth", 6.0, 3.7, "Half", damage=1.0))
    item = t.incident_counts(items)
    assert not item["visible"] and item["lines"] == []
    shown = t.incident_counts(items, solitary=2, solitary_queue=1, lockdown=3)
    assert shown["lines"][0] == "2 in Solitary (1 awaiting)"
    assert "3 in Lockdown" in shown["lines"]


def test_exhausted_staff_and_resting():
    items = objects(
        prisoner("A", 5.0, 1.0, "Half"),
        staff("Workman", "RestStateRequired"),
        staff("Workman", "RestStateResting"),
        staff("Guard", "RestStateExhausted"),
        staff("Cook"),
        staff("Doctor", Damage=1.0, RestState="RestStateRequired"),
    )
    got = t.exhausted_staff(items)
    assert got == {"exhausted": 3, "resting": 1, "staff": 4}
    assert t.exhausted_percent(items) == 75


def test_exhausted_staff_needs_prisoners_and_live_ints():
    items = objects(staff("Workman", "RestStateRequired"))
    assert t.exhausted_staff(items)["exhausted"] == 0
    live = objects(
        prisoner("A", 5.0, 1.0, "Half"), {"name": "Workman", "rs": 1, "el": 0.0}
    )
    assert t.exhausted_staff(live)["exhausted"] == 1


def test_staff_exhausted_item_lines():
    people = objects(
        prisoner("A", 5.0, 1.0, "Half"),
        staff("Workman", "RestStateRequired"),
        staff("Workman", "RestStateRequired"),
    )
    no_room = t.staff_exhausted_item(people, objects({"RoomType": "Cell"}))
    assert no_room["lines"] == [
        "2 staff members are exhausted.",
        "Build a Staff Room so they can rest.",
    ]
    room = t.staff_exhausted_item(people, objects({"RoomType": "Staffroom"}))
    assert room["lines"] == ["2 staff members are exhausted.", "(0 are resting)"]
    assert not t.staff_exhausted_item(objects(staff("Cook")), None)["visible"]


def test_category_counts_and_intake():
    counts = t.category_counts(
        objects(
            prisoner("A", 5.0, 1.0, "Half", category="MinSec"),
            prisoner("B", 5.0, 1.0, "Half"),
            prisoner("C", 5.0, 1.0, "Half", damage=1.0),
        )
    )
    assert counts["MinSec"] == 1 and counts["Normal"] == 1 and counts["DeathRow"] == 0
    assert t.intake_closed({"IntakeType": 0}) and not t.intake_closed({"IntakeType": 1})
    assert t.intake_arrival_time({"DailyScheduledTime": 8}) == "08:00"


def test_need_bucket_shapes():
    assert t.need_bucket(100.0, 55.0, True)["critical"] == 1.0
    assert t.need_bucket(100.0, 55.0, False)["high"] == 1.0  # not a RaisesTemp need
    assert t.need_bucket(37.0, 38.0, True)["low"] > 0
    assert t.need_bucket(60.0, 55.0, True)["mid"] == 1.0
    assert t.need_bucket(10.0, 55.0, True)["low"] == 1.0
    assert t.need_bucket(95.0, 55.0, False)["high"] == 1.0  # >= 55 + 0.8 * 45 = 91


def test_needs_percent():
    # Food: two critical (100 on a RaisesTemp need) and one mid (72 >= 62): 2/3
    assert t.needs_percent(NEEDY, "Food") == 66
    assert t.needs_percent(NEEDY, "Hygiene") == 100
    assert t.needs_percent(NEEDY, "Luxuries") is None
    assert t.needs_percent(NEEDY, "Food", "high") == 66


def test_prisoners_per_guard():
    items = objects(
        *[prisoner("P", 5.0, 1.0, "Half") for _ in range(17)],
        staff("Guard"),
        staff("ArmedGuard"),
    )
    assert t.prisoners_per_guard(items) == 8
    assert t.prisoners_per_guard(NEEDY) is None


def test_alerts():
    save = {
        "TimeIndex": 30000.0,
        "Balance": 100.0,
        "/Objects": NEEDY
        | {"/[i 50]": staff("Psychologist"), "/[i 51]": staff("Chief")},
        "/Rooms": objects({"RoomType": "Cell"}),
    }
    assert t.evaluate_alert("NEEDS04", save) is True  # Food 66% >= 30
    assert t.evaluate_alert("NEEDS08", save) is True  # Hygiene 100% >= 30
    assert t.evaluate_alert("NEEDS01", save) is None  # no Bladder data
    assert t.evaluate_alert("MONEY01", save) is True  # cash below 5000 after 14 days
    assert t.evaluate_alert("OBJECTS04", save) is True  # no Servo
    assert t.evaluate_alert("DOCTOR01", save) is False  # no MedicalWard room yet
    assert t.evaluate_alert("NOPE", save) is None
    save["Balance"] = 90000.0
    save["/Objects"]["/[i 52]"] = {"Type": "Servo"}
    assert t.evaluate_alert("MONEY01", save) is False
    assert t.evaluate_alert("OBJECTS04", save) is False
    result = t.active_alerts(save)
    assert "NEEDS04" in result["raised"]
    assert "OBJECTS04" in result["clear"]
    assert "MONEY01" in result["clear"]


def test_alert_needs_adviser_and_early_game():
    save = {"TimeIndex": 100.0, "Balance": 0.0, "/Objects": NEEDY, "/Rooms": {}}
    assert t.evaluate_alert("MONEY01", save) is False  # first 14 days are exempt
    assert "NEEDS04" in t.active_alerts(save)["no_adviser"]


def test_build_items_text():
    save = {"/Objects": LIVE, "/Rooms": {}}
    items = t.build_items(save)
    assert [i["id"] for i in items] == ["PrisonersLeaving"]
    assert items[0]["lines"] == ["1 prisoners up for parole"]
    assert items[0]["names"] == ["Gareth X"]
