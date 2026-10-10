"""Proxy console commands that act on an attached game: ``games``, ``attach``,
``detach`` and the ones that inject events (``say``, ``cash``, ``balance``, ``inject``).

Every injected packet goes to the attached client only, is shown in the pane and
is recorded with ``injected=1``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pyphotonrealtime.server import Direction

from src.bot.broadcast import speaker_index
from src.bot.catalog import ArgError, find, parse_args
from src.cli.attach import Game, GameTracker, deliver, event_from_data, inject
from src.cli.balance import BalanceOverride, snapshot_data
from src.cli.console import Command
from src.protocol.rpc import RpcShapeError

NEW_SPEECH = 117
TRANSACTION_ADDED = 118
DIRECTORY_DATA = 9
CASH_KEY = "finance_cost_cashflow"
"""Ledger key of the +35 cash-flow item in the captures (journal2)."""


def inject_commands(
    tracker: GameTracker,
    balance: BalanceOverride,
    record: Callable[..., int | None],
    show: Callable[..., Any],
) -> dict[str, Command]:
    """The commands, bound to the proxy's tracker, recorder and pane."""

    def attached() -> Game:
        game = tracker.current()
        if game is None:
            raise ValueError("not attached to a game (games, then attach)")
        return game

    def send(game: Game, code: int, *args: object, sender: int | None = None) -> None:
        try:
            packet, packet_id = inject(game, code, *args, sender=sender, record=record)
        except RpcShapeError as exc:
            raise ValueError(str(exc)) from None
        show(packet_id, Direction.ToClient, packet, injected=True)

    def games(args: list[str]) -> str:
        live = tracker.games()
        if not live:
            return "no games yet: join one in the client"
        return "\n".join(
            f"{'*' if g is tracker.current() else ' '} {g.label()}" for g in live
        )

    def attach(args: list[str]) -> str:
        if len(args) > 1:
            raise ValueError("expected a game number or name")
        return f"attached to {tracker.attach(args[0] if args else None).label()}"

    def detach(args: list[str]) -> str:
        tracker.detach()
        return "detached"

    def say(args: list[str]) -> str:
        game = attached()
        if len(args) < 2:
            raise ValueError("expected a speaker and a message")
        send(game, NEW_SPEECH, speaker_index(args[0]), " ".join(args[1:]))
        return ""

    def cash(args: list[str]) -> str:
        """A one-off cash-flow item: the client's balance moves by AMOUNT."""
        game = attached()
        if not 1 <= len(args) <= 2:
            raise ValueError("expected an amount and optionally a ledger key")
        send(
            game,
            TRANSACTION_ADDED,
            int(args[0]),
            args[1] if args[1:] else CASH_KEY,
            0,
            0,
        )
        return ""

    def push_balance(game: Game) -> None:
        """Send the client the balance it should show right now."""
        shown = balance.shown(game.session)
        if shown is None or game.host_actor is None:
            raise ValueError(
                "the host hasn't sent a snapshot yet; try again in a moment"
            )
        for name in ("Finance", "World"):
            packet = event_from_data(
                game, DIRECTORY_DATA, snapshot_data(name, shown), game.host_actor
            )
            show(
                deliver(game, packet, record), Direction.ToClient, packet, injected=True
            )

    def bank(args: list[str]) -> str:
        game = attached()
        if not args:
            return balance.status(game.session)
        if args == ["off"]:
            balance.release()
            push_balance(game)
            return "override off; the client shows the real balance again"
        if len(args) != 1:
            raise ValueError("expected an amount or off")
        offset = balance.pin(game.session, int(args[0]))
        push_balance(game)
        return f"client now shows {args[0]} (offset {offset:+d}); the host is unchanged"

    def raw(args: list[str]) -> str:
        game = attached()
        if not args:
            raise ValueError("expected an RPC name or number, then its arguments")
        try:
            action = find(args[0])
        except KeyError:
            raise ValueError(f"unknown RPC {args[0]!r}") from None
        if action.blocked:
            raise ValueError(f"{action.name}: {action.blocked}")
        try:
            values = parse_args(action, args[1:])
        except ArgError as exc:
            raise ValueError(str(exc)) from None
        send(game, action.code, *values)
        return ""

    return {
        "games": Command("games", "list the games being proxied", games),
        "attach": Command("attach [N|NAME]", "attach to a game to inject into", attach),
        "detach": Command("detach", "leave the attached game", detach),
        "say": Command("say SPEAKER TEXT", "an adviser speaks in the game", say),
        "cash": Command(
            "cash AMOUNT [KEY]", "add a cash-flow item to the balance", cash
        ),
        "balance": Command(
            "balance [AMOUNT|off]",
            "show the client a bank balance of your choice",
            bank,
        ),
        "inject": Command(
            "inject RPC [ARGS...]", "send the client any event (see ctl actions)", raw
        ),
    }
