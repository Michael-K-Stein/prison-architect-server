"""Readable names and values for the fields of a prisoner in the save (``Inmates`` panel)."""

from __future__ import annotations

import re
from typing import Any

NAMES: dict[str, str] = {
    "Forname": "First name",
    "Surname": "Surname",
    "Age": "Age",
    "AgeCategory": "Age group",
    "AgeToDieOldAge": "Dies of old age at",
    "BodyType": "Body model",
    "BodyScale": "Height scale",
    "HeadType": "Face",
    "WrinkleType": "Wrinkles",
    "SkinColour": "Skin colour",
    "ClothingColour": "Clothing colour",
    "CivilianClothes": "Wearing civilian clothes",
    "Traits": "Trait",
    "ReputationRevealed": "Reputation revealed",
    "Crime": "Crime",
    "SentenceF": "Sentence",
    "Served": "Served",
    "NextParole": "Next parole hearing",
    "Nitg": "Number in gang",
    "DrugAddiction": "Drug addiction",
    "ClemencyChance": "Clemency chance",
    "OriginalCategory": "Arrived as",
    "Category": "Security group",
    "StintNumber": "Times imprisoned",
    "WorkCredential": "Work qualification",
    "WorkingCredential": "Work qualification",
    "Carried": "Carrying",
    "Loaded": "Sitting on a carrier",
    "Carrier": "Carried by",
    "CarrierId": "Carried by",
    "Type": "Kind",
    "Damage": "Health damage",
    "Convictions": "Convictions",
    "Experience": "Experience",
    "Plea": "Pleaded",
    "Guilty": "Found guilty",
    "Id": "Object id",
    "Pos": "Position",
    "Bio": "Biography",
}
"""Raw field name -> what the game's UI would call it."""

_GREEN, _RED, _YELLOW, _CYAN, _DIM = (
    "fg:ansigreen",
    "fg:ansired",
    "fg:ansiyellow",
    "fg:ansicyan",
    "fg:ansibrightblack",
)
CATEGORY_STYLE = {
    "MinSec": _GREEN,
    "Normal": "",
    "MaxSec": _YELLOW,
    "Protected": _CYAN,
    "SuperMax": _RED,
    "DeathRow": "bold " + _RED,
    "Insane": "fg:ansimagenta",
}
"""Colour of each security group's name."""
PAROLE = {
    "None": "no hearing scheduled",
    "Half": "at half of the sentence",
    "ThreeQuarters": "at three quarters of the sentence",
    "Failed": "failed",
    "Succeeded": "granted",
}
CATEGORIES = {
    "MinSec": "Minimum",
    "Normal": "Medium",
    "MaxSec": "Maximum",
    "Protected": "Protective Custody",
    "SuperMax": "SuperMax",
}
"""Security groups the game words differently from the save."""
_NO_ID = 0xFFFFFFFF


def order(key: str) -> tuple[int, str]:
    """Sort key: known fields in the order of ``NAMES`` (name, age, sentence ...), then the rest."""
    names = list(NAMES)
    base = key.partition(".")[0]
    return (names.index(base) if base in names else len(names), key)


def _words(key: str) -> str:
    """``SomeFieldName`` -> ``Some field name``."""
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", key).strip()
    return text[:1].upper() + text[1:].lower() if text else key


def title(key: str) -> str:
    """The readable name of a field (``CarrierId.i`` -> ``Carried by (index)``)."""
    base, dot, part = key.partition(".")
    name = NAMES.get(base) or _words(base)
    if not dot:
        return name
    suffix = {"i": "index", "u": "unique id", "x": "x", "y": "y"}.get(part, part)
    return f"{name} ({suffix})"


def _is_no_id(value: Any) -> bool:
    return isinstance(value, int) and value in (-1, _NO_ID)


def value_of(
    key: str, value: Any, fields: dict[str, Any] | None = None
) -> tuple[str, str]:
    """Readable text and a prompt_toolkit style for a field's value."""
    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    base = key.partition(".")[0]
    if isinstance(value, list):
        return ", ".join(value_of(key, v, fields)[0] for v in value), _CYAN
    if base in ("CarrierId", "Carrier") and key != base and _is_no_id(value):
        return "nobody", _DIM
    if base == "Carried" and isinstance(value, int):
        # an object index (net key "c"); -1 and 0 both mean nothing in the captures
        return (
            ("nothing", _DIM)
            if value in (0, -1, _NO_ID)
            else (f"object #{value}", _CYAN)
        )
    if isinstance(value, bool) or key in (
        "Loaded",
        "ReputationRevealed",
        "CivilianClothes",
    ):
        return ("yes", _GREEN) if value else ("no", _DIM)
    if base in ("Category", "OriginalCategory"):
        text = str(value)
        return CATEGORIES.get(text, _words(text)), CATEGORY_STYLE.get(text, "")
    if base == "NextParole":
        text = str(value)
        style = {"Failed": _RED, "Succeeded": _GREEN, "None": _DIM}.get(text, _YELLOW)
        return PAROLE.get(text, _words(text)), style
    if base == "SentenceF" and isinstance(value, (int, float)):
        return f"{value:.1f} years", _YELLOW  # the game prints "%.1f"; YearsServed
    if base == "Served" and isinstance(value, (int, float)):
        total = (fields or {}).get("SentenceF")
        if isinstance(total, (int, float)) and total > 0:
            return f"{value:.1f} of {total:.1f} years ({value / total:.0%})", _GREEN
        return f"{value:.1f} years", _GREEN
    if base == "Age" and isinstance(value, (int, float)):
        return f"{value:.0f} years", ""
    if base == "BodyScale" and isinstance(value, float):
        size = "shorter" if value < 0.95 else "taller" if value > 1.05 else "average"
        return f"{value:.0%} of normal ({size})", ""
    if base == "BodyType" and isinstance(value, int):
        return f"body sprite #{value + 1}", ""
    if base == "HeadType":
        text = str(value)
        number = re.sub(r"\D", "", text)
        sex = "female" if text.startswith("Female") else "male"
        return f"{sex} face #{number}" if number else text, ""
    if base in ("SkinColour", "ClothingColour") and isinstance(value, str):
        return _colour(value), ""
    if base == "ClemencyChance" and isinstance(value, float):
        return f"{value:.0%}", ""
    if base == "Damage" and isinstance(value, (int, float)):
        style = _RED if value >= 1.0 else _YELLOW if value > 0.25 else ""
        return ("dead" if value >= 1.0 else f"{value:.0%}"), style
    if base == "DrugAddiction" and isinstance(value, int):
        return ("none", _DIM) if _is_no_id(value) else (f"drug {value}", _RED)
    if base == "Crime":
        return _words(str(value)), _RED
    if base == "WorkCredential" or base == "WorkingCredential":
        return _words(str(value)), _CYAN
    if base == "AgeCategory":
        return _words(str(value)), ""
    if base == "AgeToDieOldAge" and isinstance(value, float):
        return ("never", _DIM) if value < 0 else f"{value:.0f} years", ""
    if base == "StintNumber":
        return str(value), ""
    if isinstance(value, float):
        return f"{value:.2f}", ""
    return str(value), ""


def _colour(text: str) -> str:
    """``0x84512cff`` (RGBA) -> ``#84512c``; fully transparent is ``none``."""
    digits = text[2:] if text.startswith("0x") else text
    if len(digits) == 8 and re.fullmatch(r"[0-9a-fA-F]{8}", digits):
        return "none" if digits.endswith("00") else f"#{digits[:6]}"
    return text
