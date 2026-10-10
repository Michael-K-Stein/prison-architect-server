"""Finance ledger entries: ``TransactionAdded`` (118) and ``TransactionAppended`` (119).

Both carry ``[amount, key, int, text]`` (``rpc_table``). ``amount`` is a signed
change to the bank balance in dollars (negative = spent). ``key`` names the
ledger category: ``finance_cost_*`` for running costs, grants, fines and intake,
``object_<Type>`` for the price of one placed object, ``research_<Name>`` for a
research project. The int and text slots were 0 in every captured entry, so an
empty text arrives as int 0 and is read here as ``""``. See journal2
``TransactionAdded`` (118).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.protocol.snapshot import decode_args

if TYPE_CHECKING:
    from collections.abc import Iterable

TRANSACTION_ADDED = 118
TRANSACTION_APPENDED = 119
LEDGER_CODES = frozenset({TRANSACTION_ADDED, TRANSACTION_APPENDED})

CASHFLOW = "cashflow"
CONSTRUCTION = "construction"
RESEARCH = "research"
GRANT = "grant"
PRISONERS = "prisoners"
STAFF = "staff"
SALES = "sales"
OTHER = "other"
UNKNOWN = "unknown"
CATEGORY_ORDER = (
    CASHFLOW,
    CONSTRUCTION,
    RESEARCH,
    GRANT,
    PRISONERS,
    STAFF,
    SALES,
    OTHER,
    UNKNOWN,
)
"""Display order of :func:`group_by_category`."""


@dataclass(frozen=True)
class Entry:
    """One ledger entry as the game sends it."""

    code: int
    """118 (``TransactionAdded``) or 119 (``TransactionAppended``)."""
    amount: int
    """Signed dollars: negative is money out, positive is money in."""
    key: str
    """Ledger key, e.g. ``object_Light``."""
    flag: int
    """Third argument; always 0 in the captures (meaning unknown)."""
    text: str
    """Fourth argument as text; ``""`` when the game sends int 0."""

    @property
    def category(self) -> str:
        """The :data:`CATEGORY_ORDER` entry this key belongs to."""
        return classify(self.key)[0]

    @property
    def description(self) -> str:
        """Short readable meaning of the key (see :func:`classify`)."""
        return classify(self.key)[1]


_EXACT: dict[str, tuple[str, str]] = {
    "finance_cost_cashflow": (
        CASHFLOW,
        (
            "running cash flow; about one per minute in the todos capture, -62 each;"
            " +35 once at game start"
        ),
    ),
    "finance_cost_foundations": (
        CONSTRUCTION,
        "concrete foundations placed, charged when the blueprint is built",
    ),
    "finance_cost_equipbodyarmour": (STAFF, "body armour issued to staff (name only)"),
    "finance_cost_prisonerintake": (
        PRISONERS,
        "fee paid when a prisoner arrives (300 to 3600 seen)",
    ),
    "finance_cost_grantadvance": (GRANT, "advance paid when a grant is accepted"),
    "finance_cost_grantcompletion": (GRANT, "payment when a grant is completed"),
    "finance_cost_grantfine": (GRANT, "grant fine (name only, not seen)"),
    "finance_cost_grantcancellation": (GRANT, "grant cancelled (name only, not seen)"),
    "finance_cost_grantrefund": (GRANT, "grant refund (name only, not seen)"),
    "finance_cost_prisonsale": (SALES, "prison sale (name only, not seen)"),
    "parole_fine": (PRISONERS, "parole fine, -5000 each"),
    "reform_reward": (PRISONERS, "reward for a reformed prisoner, +1000 each"),
    "d11_powerexportmeter_sell_desc": (
        SALES,
        "power export meter sale: a sell line, +500 to +3000",
    ),
    "interface_action_snackbought": (OTHER, "snack bought in the interface, +2"),
}
"""Exact keys -> (category, description). Amounts are from the captures."""

_PREFIXES: tuple[tuple[str, str, str], ...] = (
    ("object_", CONSTRUCTION, "price of one placed object (negative)"),
    ("research_", RESEARCH, "research project cost (negative)"),
    ("finance_cost_", OTHER, "finance cost category (not in the table)"),
)
"""Prefix -> (category, description suffix), checked after :data:`_EXACT`."""

_TEST_KEYS = frozenset({"MONEY", "4", '"Money"'})
"""Keys seen only in our own injected test packets, not in game traffic."""


def classify(key: str) -> tuple[str, str]:
    """``(category, description)`` for a ledger key, never raises."""
    if key in _EXACT:
        return _EXACT[key]
    if key in _TEST_KEYS:
        return (UNKNOWN, "not a game key: our own injected test entry")
    for prefix, category, text in _PREFIXES:
        if key.startswith(prefix):
            name = key[len(prefix) :]
            return (category, f"{name}: {text}")
    return (UNKNOWN, "key not seen in the captures")


def _text(value: object) -> str:
    """The fourth argument as text: int 0 (the game's empty string) is ``""``."""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    if value == 0:
        return ""
    raise ValueError(f"ledger text argument is not text: {value!r}")


def parse_entry(code: int, data: bytes) -> Entry:
    """Parse the ``Data`` of a 118 or 119 event.

    Raises ValueError if ``code`` is not 118 or 119 or there are not four
    arguments; TypeError if an argument has the wrong type.
    """
    if code not in LEDGER_CODES:
        raise ValueError(f"event {code} is not a ledger entry")
    args = decode_args(data)
    if len(args) != 4:
        raise ValueError(f"ledger entry has {len(args)} arguments, expected 4")
    amount, key, flag, text = args
    if not isinstance(amount, int) or not isinstance(flag, int):
        raise TypeError(f"ledger amount or flag is not an int: {args!r}")
    if not isinstance(key, bytes):
        raise TypeError(f"ledger key is not a string: {key!r}")
    return Entry(
        code=code,
        amount=amount,
        key=key.decode("utf-8", "replace"),
        flag=flag,
        text=_text(text),
    )


def group_by_category(entries: Iterable[Entry]) -> dict[str, list[Entry]]:
    """Entries grouped by category, in :data:`CATEGORY_ORDER`, keeping order."""
    groups: dict[str, list[Entry]] = defaultdict(list)
    for entry in entries:
        groups[entry.category].append(entry)
    return {name: groups[name] for name in CATEGORY_ORDER if name in groups}
