"""Build ``src/protocol/game_text.py`` from the game's language files.

Run as ``python -m src.protocol.textgen "<language dir>"`` (the folder with
``base-language.txt``, ``fullgame.txt`` and ``d11.txt``). Kept: every key that contains
``staffalert`` or ``warning`` or starts with ``help_``, ``objective_``, ``need_name_``,
``needs_help_``, ``room_``, ``adviser_``, ``roomerror_`` or ``quickbuild_`` (later files override earlier ones).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

LANGUAGE_FILES = ("base-language.txt", "fullgame.txt", "d11.txt")
OUT_PATH = Path(__file__).with_name("game_text.py")
PREFIXES = (
    "help_",
    "objective_",
    "need_name_",
    "needs_help_",
    "room_",
    "adviser_",
    "quickbuild_",
    "roomerror_",
)
HEADER = '''"""English text of the game's alert, help, objective, need and room messages. Generated.

From the game's ``data/language/{base-language,fullgame,d11}.txt`` by ``python -m
src.protocol.textgen``: keys containing ``staffalert`` or ``warning``, or starting with
``help_``, ``objective_``, ``need_name_``, ``needs_help_``, ``room_``, ``adviser_`` or
``quickbuild_``. Used to show ``StaffAlert`` / ``NewSpeechAdded`` keys and the Todo list as text.
"""

TEXT: dict[str, str] = {
'''
_LINE = re.compile(r"^(\S+)\s+(.*)$")


def wanted(key: str) -> bool:
    low = key.lower()
    return "staffalert" in low or "warning" in low or low.startswith(PREFIXES)


def read(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        match = _LINE.match(line.strip("\r"))
        if match and wanted(match[1]):
            out[match[1]] = match[2].strip().replace("\n", "\n")
    return out


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    texts: dict[str, str] = {}
    for name in LANGUAGE_FILES:
        path = Path(argv[1]) / name
        if path.exists():
            texts.update(read(path))
    body = "".join(
        f"    {k!r}: {v!r},\n".replace("'", '"', 0) for k, v in sorted(texts.items())
    )
    OUT_PATH.write_text(HEADER + body + "}\n", encoding="utf-8")
    print(f"{len(texts)} texts -> {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
