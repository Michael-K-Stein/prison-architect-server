"""Room Quality criteria and their evaluation."""

from __future__ import annotations

from src.bot import qualitygen, quality


def test_the_data_files_give_cells_a_grading_list() -> None:
    cell = quality.GRADINGS["Cell"]
    assert [c["Size"] for c in cell if c["Type"] == "RoomSize"] == [6, 9, 16]
    mattress = next(c for c in cell if c.get("Id") == "Mattress")
    assert mattress["GradeEffect"] == -1


def test_size_steps_and_items_add_up() -> None:
    result = quality.evaluate(
        "Cell", 10, ["Bed", "ComfyBed", "Toilet", "Radio", "Mattress"]
    )
    met = {c["text"]: c["met"] for c in result["criteria"] if c["type"] == "RoomSize"}
    assert list(met.values()) == [True, True, False]  # 6 and 9 squares, not 16
    assert (
        result["computed"] == 2 + 1 + 1 - 1
    )  # size 6, 9; ComfyBed; Radio; Mattress -1


def test_invisible_criteria_are_marked_unknown() -> None:
    window = next(
        c
        for c in quality.evaluate("Cell", 1, [])["criteria"]
        if c["type"] == "OutsideWindow"
    )
    assert window["met"] is None and window["effect"] == 2


def test_parse_reads_inline_grading_lines() -> None:
    text = "\nBEGIN Room\n Name Cell\n BEGIN Grading Type Item Id Tv Alt LargeTv Multi true END\nEND\n"
    assert qualitygen.parse(text) == {
        "Cell": [{"Type": "Item", "Id": "Tv", "Alt": ["LargeTv"], "Multi": True}]
    }


def _by_type(result: dict, kind: str) -> list[dict]:
    return [c for c in result["criteria"] if c["type"] == kind]


def test_outdoor_windows_and_no_window_penalty() -> None:
    no_window = quality.evaluate("Cell", 12, [], {"windows": [], "walls": {"total": 0}})
    assert [c["met"] for c in _by_type(no_window, "HasWindow")] == [True]  # -1 applies
    large = quality.evaluate(
        "Cell",
        12,
        [],
        {"windows": [{"large": True, "outdoor": True}], "walls": {"total": 0}},
    )
    assert [c["met"] for c in _by_type(large, "OutsideWindow")] == [True, True]
    assert [c["met"] for c in _by_type(large, "HasWindow")] == [False]


def test_indoor_window_does_not_count_as_outside() -> None:
    result = quality.evaluate(
        "Cell",
        12,
        [],
        {"windows": [{"large": True, "outdoor": False}], "walls": {"total": 0}},
    )
    assert [c["met"] for c in _by_type(result, "OutsideWindow")] == [False, False]


def test_wall_and_pa_criteria_use_the_edge() -> None:
    result = quality.evaluate(
        "Cell",
        12,
        [],
        {
            "windows": [],
            "walls": {"total": 10, "GlassWall": 6},
            "pa": True,
        },
    )
    assert [c["met"] for c in _by_type(result, "HasGlassWalls")] == [True]  # 60% >= 50%
    assert [c["met"] for c in _by_type(result, "HasPASystem")] == [True]


def test_concrete_walls_are_not_depressing() -> None:
    result = quality.evaluate(
        "Cell", 12, [], {"windows": [], "walls": {"total": 10, "ConcreteWall": 10}}
    )
    assert [c["met"] for c in _by_type(result, "BadWalls")] == [None]
