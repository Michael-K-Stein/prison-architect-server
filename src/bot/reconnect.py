"""Keep a headless bot in the game: resync after land, rejoin after a stall or drop.

The host stops sending snapshots to a client that has gone stale. Seen live (journal2,
"Land expansion"): after a ``LandPurchased`` the real client shows a "reconnecting"
window while it reloads the save, and bots that did not reload went silent (game time
frozen in ``ctl state``, ``host_stalled`` true) until they rejoined. So:

1. on ``LandPurchased`` (RPC 10) the session asks for a fresh save (``Session``);
2. :class:`ReconnectPolicy` decides, from the connection and how long ``World``
   snapshots have been missing, to ``resync`` (ask for the save again), to ``rejoin``
   (leave and join the room again, with a growing delay while the room is full) or wait;
3. :class:`Reconnector` runs that in a thread next to the control server and swaps the new
   session into it, so the control port and the bot's names survive.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.bot.control import ControlServer
    from src.bot.session import Session

log = logging.getLogger(__name__)

LAND_PURCHASED = 10
"""RPC ``LandPurchased``: the host grew the map; every client reloads the save."""
STALL_LIMIT = 15.0
"""Seconds without a ``World`` snapshot before the bot asks for the save again."""
RESYNC_WAIT = 20.0
"""Seconds after that request before the bot gives up on it and rejoins."""
BACKOFF = (2.0, 4.0, 8.0, 15.0, 30.0)
"""Delays between rejoin attempts (the last one repeats)."""
MAX_ATTEMPTS = 10


@dataclass
class ReconnectPolicy:
    """What to do given the connection state (pure, so it can be tested)."""

    stall_limit: float = STALL_LIMIT
    resync_wait: float = RESYNC_WAIT
    _resync_at: float | None = field(default=None, repr=False)

    def reset(self) -> None:
        """Forget an earlier resync (the bot is healthy again, or was just rebuilt)."""
        self._resync_at = None

    def decide(self, disconnected: bool, silent_for: float, now: float) -> str:
        """``ok``, ``resync``, ``wait`` or ``rejoin``."""
        if disconnected:
            return "rejoin"
        if silent_for < self.stall_limit:
            self._resync_at = None
            return "ok"
        if self._resync_at is None:
            self._resync_at = now
            return "resync"
        if now - self._resync_at >= self.resync_wait:
            return "rejoin"
        return "wait"


def backoff(attempt: int) -> float:
    """Seconds to wait before rejoin attempt number ``attempt`` (0 based)."""
    return BACKOFF[min(attempt, len(BACKOFF) - 1)]


class Reconnector(threading.Thread):
    """Watches the control server's session and replaces it when it goes bad."""

    def __init__(
        self,
        server: ControlServer,
        rejoin: Callable[[], Session],
        password: str,
        policy: ReconnectPolicy | None = None,
        poll: float = 2.0,
    ) -> None:
        super().__init__(daemon=True, name="reconnector")
        self.server = server
        self.rejoin = rejoin
        self.password = password
        self.policy = policy or ReconnectPolicy()
        self.poll = poll
        self.rejoins = 0
        self.gave_up = False

    def run(self) -> None:
        while not self.server.stopped.wait(self.poll):
            session = self.server.session
            seen = session.state.world_seen
            silent = time.time() - seen if seen else 0.0
            action = self.policy.decide(
                session.disconnected is not None, silent, time.monotonic()
            )
            if action == "resync":
                log.warning("no World snapshot for %.0f s: asking for the save", silent)
                session.request_save(self.password)
            elif action == "rejoin":
                if not self._rejoin(session):
                    self.gave_up = True
                    log.error("could not rejoin: stopping")
                    self.server.stop()
                    return

    def _rejoin(self, old: Session) -> bool:
        """Leave, join again (retrying while the room is full) and swap the session."""
        log.warning("rejoining the game")
        try:
            old.stop()
        except Exception:  # noqa: BLE001 -- a dead connection may fail to close
            log.exception("closing the old session failed")
        for attempt in range(MAX_ATTEMPTS):
            if self.server.stopped.wait(backoff(attempt)):
                return True
            try:
                new = self.rejoin()
                new.request_save(self.password)
            except Exception as exc:  # noqa: BLE001 -- full room, network, host busy
                log.warning("rejoin attempt %d failed: %s", attempt + 1, exc)
                continue
            self.server.session = new
            self.policy.reset()
            self.rejoins += 1
            log.warning("rejoined as actor %s", new.client.local_player.actor_number)
            return True
        return False
