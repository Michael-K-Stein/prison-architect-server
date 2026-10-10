"""Connection to Photon: a ``RealtimeClient`` pumped by a background thread.

Threading: ``RealtimeClient`` is single-threaded and needs ``service()`` calls,
but prompts block. So :class:`Session` runs ``service()`` in a daemon thread and
every client call, from either thread, takes one ``RLock``. Callbacks fire inside
``service()`` (lock held) and only append to plain containers.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from pyphotonrealtime import AppSettings, RealtimeClient
from pyphotonrealtime.protocol.param.parameter_key import ParameterKey
from pyphotonrealtime.realtime import (
    ConnectionCallbacks,
    LobbyCallbacks,
    MatchmakingCallbacks,
    OnEventCallback,
    RaiseEventArgs,
)

from src.bot import build
from src.bot.build import Job
from src.bot.formatting import format_event_lines
from src.bot.names import ObjectNames
from src.bot.zones import Zones
from src.bot.recording import record_traffic
from src.bot.savegame import SaveTransfer
from src.bot.state import GameState
from src.capture import Recorder
from src.protocol import rpc
from src.server.upstream import resolve_upstream

log = logging.getLogger(__name__)

PING_INTERVAL = 4.0  # seconds between the game client's P (ping) updates
FIRST_PING_DELAY = 1.3  # ... the first one comes this long after joining
CLAUDE_ORANGE = "d97757"  # RRGGBB; sent as the game does: "0xRRGGBBAA"
HOST_ACTOR = 1  # the game's "is host" test is "local actor number is 1" (IDA)
APP_VERSION = "the_slammer_1.0"  # AppVersion in the game's Authenticate (captures)


class ConnectError(RuntimeError):
    """The bot could not connect or join; the message is meant for the user."""


@dataclass
class Options:
    """Command line settings shared by the commands."""

    app_id: str
    app_version: str = APP_VERSION
    name_server: str = ""
    region: str | None = None
    speed_index: bool = False
    full_events: bool = False
    name: str = "Claude"
    colour: str = CLAUDE_ORANGE
    record: Path | None = None
    """Capture file for the bot's own traffic (``--record``); None = not recorded."""
    password: str = ""
    """The game's password, sent in ``AuthoriseConnection`` after joining."""


class Session(
    ConnectionCallbacks,
    MatchmakingCallbacks,
    LobbyCallbacks,
    OnEventCallback,
):
    """A ``RealtimeClient`` pumped by a background thread, plus what it saw."""

    def __init__(
        self, client: RealtimeClient | None = None, recorder: Recorder | None = None
    ) -> None:
        """Wrap ``client`` (a new one by default) and register for callbacks.

        With ``recorder``, every packet this client sends or receives is recorded.
        """
        self.client = client or RealtimeClient()
        self.lock = threading.RLock()
        self.regions: dict[str, str] = {}
        self.events: deque[tuple[int, int, Any]] = deque(maxlen=5000)
        self.master = self.joined = self.lobby_joined = False
        self.state = GameState(names=ObjectNames(), zones=Zones())
        """What the host's events say about the game (merged snapshots)."""
        self.password = ""
        """The game password last sent (reused to refresh the save)."""
        self.save = SaveTransfer(self.raise_event)
        """The join handshake: the host's save game, once requested."""
        self.disconnected: object | None = None
        self.join_error = ""
        self._stop = threading.Event()
        self._next_ping: float | None = None
        if (peer := getattr(self.client, "peer", None)) is not None:
            # Photon only measures its round trip from keep-alive pings, which
            # are sent when idle; ping often so the game's "P" is a real value.
            peer.keep_alive_interval = 1.0
            if recorder is not None:
                record_traffic(peer, recorder)
        self._thread = threading.Thread(target=self._pump, daemon=True)
        self.client.add_callback_target(self)

    # callbacks (called from the service thread)
    def on_region_list_received(self, regions: dict[str, str]) -> None:
        """Keep the regions; a set ``cloud_region`` stops the library auto-pinging."""
        log.info("Name Server sent %d regions: %s", len(regions), ", ".join(regions))
        self.regions = regions
        if self.client.cloud_region is None:
            self.client.cloud_region = "-"

    def on_connected_to_master(self) -> None:
        """Mark the Master Server as reached."""
        log.info("connected to the Master Server")
        self.master = True

    def on_joined_lobby(self) -> None:
        """Mark the lobby as joined."""
        log.info("joined the lobby")
        self.lobby_joined = True

    def on_joined_room(self) -> None:
        """Mark the room as joined."""
        log.info("joined the room as actor #%d", self.client.local_player.actor_number)
        self.joined = True

    def on_join_room_failed(self, return_code: int, message: str) -> None:
        """Remember why joining failed."""
        self.join_error = f"{message} (code {return_code})"
        log.warning("join room failed: %s", self.join_error)

    def on_disconnected(self, cause: object) -> None:
        """Remember the disconnect cause."""
        self.disconnected = cause
        log.warning("disconnected: %s", cause)

    def on_event(self, event: Any) -> None:
        """Queue custom (game) events: code 1-199, ``Data`` as raw bytes."""
        if not 0 < event.code < 200:
            return
        data = event.parameters.get(ParameterKey.Data)
        value = data.value if data is not None else None
        if log.isEnabledFor(logging.DEBUG):
            for line in format_event_lines(event.sender, event.code, value):
                log.debug("event %s", line)
        self.events.append((event.sender, event.code, value))
        self.state.apply(event.code, value)
        try:
            line = self.save.on_event(event.code, value)
        except (ValueError, rpc.RpcShapeError) as exc:
            line = f"handshake event {event.code} unreadable: {exc}"
        if line:
            self.state.note(f"handshake: {line}")
            if self.save.tree is not None and self.state.save is None:
                self.state.load_save(self.save.tree)

    def build(self, jobs: list[Job]) -> bool:
        """Send build jobs to the host (``DirectoryData("Construction")``)."""
        actor = self.client.local_player.actor_number
        return self.raise_event(
            build.DIRECTORY_DATA, build.construction_data(jobs, actor)
        )

    def request_save(self, password: str = "") -> None:
        """Ask the host for the full game (``AuthoriseConnection``).

        Can be repeated: the host sends a fresh save each time (``refresh``).
        """
        self.password = password
        self.state.save = None  # the next save loaded replaces it
        self.save.request(password)

    @property
    def objectives(self) -> dict[str, str]:
        """Current objectives: ``Name`` -> ``Type``, from :attr:`state`."""
        with self.state.lock:
            return {k: v.get("Type", "") for k, v in self.state.objectives.items()}

    # thread and helpers
    def report_ping(self, now: float) -> bool:
        """Like the game: set our actor's ``P`` to the round trip time (ms).

        First ~1.3 s after joining, then every 4 s; nothing until Photon has
        measured a round trip (a ``P`` of 0 would show as no latency). Returns
        whether a ``SetProperties`` was queued.
        """
        peer = getattr(self.client, "peer", None)
        actor = self.client.local_player.actor_number
        if not self.joined or peer is None or actor <= 0:
            return False
        if self._next_ping is None:
            self._next_ping = now + FIRST_PING_DELAY
        if now < self._next_ping or peer.last_round_trip_time is None:
            return False
        self._next_ping = now + PING_INTERVAL
        rtt = int(peer.round_trip_time)
        sent = self.client.op_set_properties_of_actor(actor, {"P": rtt})
        log.debug("ping P=%d ms (queued: %s)", rtt, sent)
        return sent

    def _pump(self) -> None:
        while not self._stop.is_set():
            with self.lock:
                self.client.service()
                self.report_ping(time.monotonic())
            time.sleep(1 / 30)

    def start(self, settings: AppSettings) -> None:
        """Connect and start the service thread."""
        log.info(
            "connecting to %s (region %s)",
            settings.name_server or "the default Name Server",
            settings.fixed_region or "picked by the library",
        )
        with self.lock:
            self.client.connect_using_settings(settings)
        if not self._thread.is_alive():
            self._thread.start()

    def wait_for(self, done: Callable[[], bool], timeout: float = 20) -> bool:
        """Poll ``done`` until true; False on timeout or disconnect."""
        end = time.monotonic() + timeout
        while time.monotonic() < end and self.disconnected is None:
            if done():
                return True
            time.sleep(0.05)
        return done()

    def raise_event(self, code: int, data: bytes, *, broadcast: bool = False) -> bool:
        """Send a game RPC to the host, as a client does (actor 1 only).

        ``bytes`` go out as an Int8Slice under key Data (245).
        """
        with self.lock:
            args = (
                RaiseEventArgs()  # every other player
                if broadcast
                else RaiseEventArgs(target_actors=[HOST_ACTOR])
            )
            sent = self.client.op_raise_event(code, data, args)
            actor = self.client.local_player.actor_number
        log.info(
            "sent RPC %d %s (%d B): %s",
            code,
            rpc.rpc_name(code),
            len(data),
            "queued" if sent else "NOT queued",
        )
        for line in format_event_lines(actor, code, data):
            log.debug("  %s", line)
        return sent

    def stop(self) -> None:
        """Disconnect cleanly and stop the thread (safe to call twice)."""
        log.info("disconnecting")
        with self.lock:
            self.client.disconnect()
        time.sleep(0.2)  # let the thread flush the disconnect
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=2)


def split_address(spec: str) -> tuple[str, int]:
    """``host`` or ``host:port`` -> (host, port); port 0 = protocol default."""
    host, _, port = spec.partition(":")
    return host, int(port) if port else 0


def make_settings(opts: Options, region: str | None = None) -> AppSettings:
    """``AppSettings`` for ``opts``; the name server may be ``auto`` or host[:port]."""
    settings = AppSettings(
        app_id_realtime=opts.app_id,
        app_version=opts.app_version,
        fixed_region=region,
        enable_lobby_statistics=True,
    )
    if opts.name_server == "auto":
        host, port = resolve_upstream("auto")
        log.info("resolved ns.exitgames.com over DNS-over-HTTPS to %s:%d", host, port)
        return replace(settings, name_server=host, name_server_port=port)
    if opts.name_server:
        host, port = split_address(opts.name_server)
        log.info("using Name Server %s:%d from the options", host, port)
        return replace(settings, name_server=host, name_server_port=port)
    return settings


def fetch_regions(opts: Options, recorder: Recorder | None = None) -> dict[str, str]:
    """Ask the Name Server for its regions (read-only), then disconnect."""
    session = Session(recorder=recorder)
    try:
        session.start(make_settings(opts))
        if not session.wait_for(lambda: bool(session.regions)):
            raise ConnectError(
                f"no region list received from the Name Server"
                f" (disconnected: {session.disconnected}). Is the Photon Name Server"
                " reachable? If your hosts file redirects it to 127.0.0.1, set"
                " PHOTON_NAME_SERVER (or --name-server) to its real address."
            )
        return dict(session.regions)
    finally:
        session.stop()
