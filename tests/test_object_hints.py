"""Object hints: the generator, the committed JSON, the tracker, and /build replies."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from src.bot import hintgen, objecthints
from src.bot.cli import app
from src.bot.control import ControlServer, call
from src.bot.state import GameState

FAKE_BASE = (
    "buildtoolbar_popup_uts_transformer\tBase text [[*X]] here\n"
    "object_transformer\tTransformer\n"
    "buildtoolbar_popup_uts_Battery\tStores\\nenergy.\n"
    "buildtoolbar_popup_uts_NotAnObject\tIgnored\n"
    "room_cell\tCell\n"
    "roomgrading_Cell_BadWalls\t[*E] Surrounded by depressing walls\n"
    "d11_staffalert_hint_OBJECTS01\t\t\tA Transformer will help [*A] units.\n"
)
FAKE_D11 = "buildtoolbar_popup_uts_transformer\tOverride text\n"


def test_generator_on_fake_language_files(tmp_path: Path) -> None:
    (tmp_path / "base-language.txt").write_text(FAKE_BASE, encoding="utf-8")
    (tmp_path / "d11.txt").write_text(FAKE_D11, encoding="utf-8")
    doc = hintgen.build(tmp_path)
    assert doc["generated_from"] == ["base-language.txt", "d11.txt"]
    transformer = doc["objects"]["Transformer"]
    assert transformer["hint"] == "Override text"  # d11 overrides base
    assert transformer["name"] == "Transformer"
    assert transformer["extra"] == ["A Transformer will help units."]
    assert doc["objects"]["Battery"]["hint"] == "Stores\nenergy."
    assert doc["objects"]["Battery"]["name"] == "Battery"  # no object_ key: table name
    assert "NotAnObject" not in doc["objects"]
    assert doc["rooms"]["Cell"]["name"] == "Cell"
    assert doc["rooms"]["Cell"]["extra"] == ["Surrounded by depressing walls"]


def test_main_writes_the_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "base-language.txt").write_text(FAKE_BASE, encoding="utf-8")
    out = tmp_path / "out" / "object_hints.json"
    monkeypatch.setattr(hintgen, "OUT_PATH", out)
    assert hintgen.main([str(tmp_path)]) == 0
    assert "Transformer" in json.loads(out.read_text(encoding="utf-8"))["objects"]


def test_committed_json_has_transformer_and_battery() -> None:
    doc = json.loads(objecthints.DATA_PATH.read_text(encoding="utf-8"))
    for name in ("Transformer", "Battery"):
        entry = doc["objects"][name]
        assert entry["name"] and entry["hint"], name
    assert (
        objecthints.lookup("transformer")["hint"]
        == doc["objects"]["Transformer"]["hint"]
    )
    assert objecthints.lookup("battery")["name"] == "Battery"
    assert objecthints.lookup("NoSuchObject") is None


def test_first_use_only_once() -> None:
    tracker = objecthints.ObjectHintTracker()
    hint = objecthints.lookup("Transformer")["hint"]
    assert tracker.take(["Transformer"], now=0) == [hint]
    assert tracker.take(["Transformer"], now=1) == []


def test_repeat_after_calls() -> None:
    tracker = objecthints.ObjectHintTracker(
        repeat_after_calls=3, repeat_after_seconds=1e9
    )
    hint = objecthints.lookup("Battery")["hint"]
    assert tracker.take(["Battery"], now=0) == [hint]  # call 1
    assert tracker.take(["Battery"], now=0) == []  # call 2
    assert tracker.take(["Battery"], now=0) == []  # call 3
    assert tracker.take(["Battery"], now=0) == [hint]  # call 4: 3 calls later


def test_repeat_after_seconds() -> None:
    tracker = objecthints.ObjectHintTracker(
        repeat_after_calls=999, repeat_after_seconds=100
    )
    hint = objecthints.lookup("Battery")["hint"]
    assert tracker.take(["Battery"], now=0) == [hint]
    assert tracker.take(["Battery"], now=99) == []
    assert tracker.take(["Battery"], now=100) == [hint]


def test_at_most_three_oldest_unseen_first() -> None:
    tracker = objecthints.ObjectHintTracker()
    names = ["Transformer", "Battery", "PowerStation", "SolarPanels"]
    first = tracker.take(names, now=0)
    assert len(first) == 3
    assert tracker.take(names, now=1) == [objecthints.lookup("SolarPanels")["hint"]]


def test_unknown_and_duplicate_names() -> None:
    tracker = objecthints.ObjectHintTracker()
    assert tracker.take(["Nope", "", "Transformer", "transformer"], now=0) == [
        objecthints.lookup("Transformer")["hint"]
    ]


def test_first_only_false_repeats_every_call() -> None:
    tracker = objecthints.ObjectHintTracker(first_only=False)
    assert len(tracker.take(["Battery"], now=0)) == 1
    assert len(tracker.take(["Battery"], now=1)) == 1


class _Session:
    """Only what the control server touches."""

    def __init__(self) -> None:
        self.state = GameState()
        self.lock = threading.RLock()
        self.disconnected = None
        self.client = SimpleNamespace(
            current_room=SimpleNamespace(name="Jail", players={})
        )

    def build(self, jobs: list) -> bool:
        return True

    def raise_event(self, code: int, data: bytes, *, broadcast: bool = False) -> bool:
        return True


@pytest.fixture
def server() -> Iterator[ControlServer]:
    control = ControlServer(_Session(), port=0)
    control.start()
    yield control
    control.stop()


def test_build_reply_carries_object_hints_once(server: ControlServer) -> None:
    spec = {"tool": "place", "object": "Transformer", "x": 1, "y": 1}
    status, body = call("POST", "/build", {"jobs": [spec]}, port=server.port)
    assert status == 200
    assert body["object_hints"] == [objecthints.lookup("Transformer")["hint"]]
    status, body = call("POST", "/build", {"jobs": [spec]}, port=server.port)
    assert status == 200 and "object_hints" not in body


def test_hints_object_endpoint_and_cli(server: ControlServer) -> None:
    status, body = call("GET", "/hints?object=Battery", port=server.port)
    assert status == 200 and body["name"] == "Battery"
    assert call("GET", "/hints?object=Nope", port=server.port)[0] == 404
    result = CliRunner().invoke(
        app, ["ctl", "--port", str(server.port), "hints", "--object", "Battery"]
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["name"] == "Battery"
