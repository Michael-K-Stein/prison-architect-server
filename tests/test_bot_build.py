"""Client build jobs: the Construction tree and the job specs."""

from __future__ import annotations

import pytest

from src.bot import build
from src.protocol import rpc
from src.protocol.snapshot import decode_args, decompress, format_tree


def test_construction_payload_round_trips() -> None:
    jobs = [build.foundation(10, 10, 5, 5), build.place("Bed", 11, 11)]
    data = build.construction_data(jobs, actor=8)
    name, blob = (v for _, v in rpc.parse(9, data).args)
    assert name == b"Construction"
    lines = format_tree(decompress(blob).tree)
    assert lines[:2] == ["Construction {pn=8}", "  Jobs {Size=2}"]
    assert lines[2].startswith(
        "    [i 0] {Type='Foundations', Material=59, PosX=10, PosY=10, SizeX=5, SizeY=5"
    )
    assert "Type='Objects', Material=5," in lines[3]
    assert decode_args(data)[0] == b"Construction"


def test_job_specs() -> None:
    assert build.job_from(
        {"tool": "room", "x": 1, "y": 2, "width": 3, "height": 3}
    ) == (build.Job("Designation", 1, 1, 2, 3, 3))
    door = build.job_from(
        {"tool": "place", "object": "JailDoor", "x": 12, "y": 14, "facing": "up"}
    )
    assert (door.material, door.facing) == (26, "up")
    wall = build.job_from({"tool": "wall", "x": 0, "y": 0, "width": 4, "height": 1})
    assert (wall.type, wall.material) == ("flooring", 46)
    with pytest.raises(build.BuildError, match="unknown tool"):
        build.job_from({"tool": "dig"})
    with pytest.raises(build.BuildError, match="unknown object 'Unicorn'"):
        build.job_from({"tool": "place", "object": "Unicorn", "x": 1, "y": 1})
    with pytest.raises(build.BuildError, match="whole numbers"):
        build.job_from({"tool": "foundation", "x": 1})
