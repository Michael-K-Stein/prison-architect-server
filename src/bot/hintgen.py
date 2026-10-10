"""Build ``src/bot/data/object_hints.json`` from the game's language files.

Run as ``python -m src.bot.hintgen "<language dir>"`` (the folder holding
``base-language.txt``, ``d11.txt``, ``fullgame.txt``). Only these key families are
read; each is a ``key<tab>text`` line, ``\\n`` in the text is a newline:

- ``buildtoolbar_popup_uts_<Object>``: the object's tooltip, the ``hint`` (only
  names in the game's OBJECTS table are kept; later files override earlier ones).
- ``object_<object>``: the display name (``name``).
- ``room_<Room>``: the display name of a room; ``roomgrading_<Room>_info`` is its
  hint and ``roomgrading_<Room>_*`` its grading lines (both into ``rooms``).
- ``d11_staffalert_{summary,hint}_<ID>``: staff alerts. An alert is attached as an
  ``extra`` line to every object or room whose display name it mentions as a whole
  word (at most 3 per entry); alerts are not otherwise shown.

Placeholders such as ``[[*X]]`` and ``[*E]`` are dropped; text is trimmed.
Keys from ``d11_staffalert_details_*`` and ``*tooltip*`` are not used.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from src.protocol.game_tables import OBJECTS, ROOMS

LANGUAGE_FILES = ("base-language.txt", "d11.txt", "fullgame.txt")
OUT_PATH = Path(__file__).parent / "data" / "object_hints.json"
MAX_EXTRA = 3

_LINE = re.compile(r"^(\S+)\s+(.*)$")
_PLACEHOLDER = re.compile(
    r"\[\[[^\]]*\]\]|\[\*[A-Z]+\](?:\*[A-Z]+)?|\*[A-Z](?![A-Za-z])"
)
_ALERT = re.compile(r"^d11_staffalert_(summary|hint)_([A-Za-z0-9]+)$")


def read_keys(path: Path) -> dict[str, str]:
    """``key -> text`` for one language file (keys lower-cased, text cleaned)."""
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        m = _LINE.match(raw.strip())
        if not m:
            continue
        key, text = m.group(1), m.group(2)
        out[key.lower()] = clean(text)
    return out


def clean(text: str) -> str:
    """Strip placeholders, turn ``\\n`` into newlines, trim."""
    text = _PLACEHOLDER.sub("", text.replace("\\n", "\n"))
    lines = [" ".join(line.split()) for line in text.split("\n")]
    return "\n".join(line for line in lines if line).strip()


def _canonical(table: dict[int, str]) -> dict[str, str]:
    return {name.lower(): name for name in table.values() if name != "None"}


def build(language_dir: Path) -> dict:
    """The JSON document for the language files found in ``language_dir``."""
    keys: dict[str, str] = {}
    used: list[str] = []
    for fname in LANGUAGE_FILES:
        path = language_dir / fname
        if path.is_file():
            keys.update(read_keys(path))  # later files override earlier ones
            used.append(fname)

    objects = _canonical(OBJECTS)
    rooms = _canonical(ROOMS)
    obj_entries: dict[str, dict] = {}
    room_entries: dict[str, dict] = {}

    for lower, canon in objects.items():
        hint = keys.get(f"buildtoolbar_popup_uts_{lower}", "")
        name = keys.get(f"object_{lower}", "")
        if hint or name:
            obj_entries[canon] = {"name": name or canon, "hint": hint, "extra": []}
    for lower, canon in rooms.items():
        name = keys.get(f"room_{lower}", "")
        hint = keys.get(f"roomgrading_{lower}_info", "")
        grading = [
            text
            for key, text in keys.items()
            if key.startswith(f"roomgrading_{lower}_")
            and key != f"roomgrading_{lower}_info"
        ]
        if name or hint or grading:
            room_entries[canon] = {
                "name": name or canon,
                "hint": hint,
                "extra": sorted(t for t in grading if t),
            }

    alerts = _alert_lines(keys)
    _attach(obj_entries, alerts)
    _attach(room_entries, alerts)

    return {
        "objects": dict(sorted(obj_entries.items())),
        "rooms": dict(sorted(room_entries.items())),
        "generated_from": used,
    }


def _alert_lines(keys: dict[str, str]) -> list[str]:
    out = []
    for key, text in sorted(keys.items()):
        if _ALERT.match(key) and text:
            out.append(text)
    return out


def _attach(entries: dict[str, dict], alerts: list[str]) -> None:
    """Add up to MAX_EXTRA alert lines that name each entry's display name."""
    for canon, entry in entries.items():
        needle = re.compile(r"\b" + re.escape(entry["name"]) + r"\b", re.IGNORECASE)
        for text in alerts:
            if len(entry["extra"]) >= MAX_EXTRA:
                break
            if needle.search(text) and text not in entry["extra"]:
                entry["extra"].append(text)


def main(argv: list[str]) -> int:
    """Write the JSON for the language dir given as the first argument."""
    if len(argv) != 1:
        print('usage: python -m src.bot.hintgen "<language dir>"', file=sys.stderr)
        return 2
    doc = build(Path(argv[0]))
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"wrote {OUT_PATH}: {len(doc['objects'])} objects, {len(doc['rooms'])} rooms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
