"""The game-speed RPC: the slider's stops and the int each one sends."""

GAME_SPEED_CHANGE = 96  # RPC id; one int argument
# (label, wire value) per slider stop. UNVERIFIED against a live game: the int
# of GameSpeedChange may be the multiplier (default) or a button index.
SPEED_STOPS: tuple[tuple[str, int], ...] = (
    ("Paused", 0),
    ("1x", 1),
    ("2x", 2),
    ("5x", 5),
    ("10x", 10),
)
SPEED_HELP = (
    "left/right or h/l: change   Enter: send   Esc/q: back\n"
    "Unverified: the int sent may not be what the live game expects."
)


def speed_wire_value(index: int, *, speed_index: bool = False) -> int:
    """The int for ``GameSpeedChange``: the multiplier, or the stop's index."""
    return index if speed_index else SPEED_STOPS[index][1]
