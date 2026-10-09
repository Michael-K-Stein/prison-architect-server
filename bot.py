"""Interactive Prison Architect bot: pick a region, a game, then send RPCs.

``python bot.py`` connects to Photon, lists regions, lobbies and games, joins the
chosen game and opens a menu (game speed, incoming events, ...).

Threading: ``RealtimeClient`` is single-threaded and needs ``service()`` calls,
but prompts block. So :class:`Session` runs ``service()`` in a daemon thread and
every client call, from either thread, takes one ``RLock``. Callbacks fire inside
``service()`` (lock held) and only append to plain containers.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from os import environ
from pathlib import Path
from typing import Annotated, Any

import typer
from InquirerPy import inquirer
from prompt_toolkit import Application
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
from prompt_toolkit.layout import Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from pyphotonrealtime import AppSettings, RealtimeClient
from pyphotonrealtime.protocol.param.parameter_key import ParameterKey
from pyphotonrealtime.realtime import (
    ConnectionCallbacks,
    EnterRoomParams,
    LobbyCallbacks,
    MatchmakingCallbacks,
    OnEventCallback,
)
from pyphotonrealtime.realtime.lobby import LobbyType, TypedLobby
from pyphotonrealtime.realtime.room import RoomInfo
from rich.console import Console

import pa_events
import pa_rpc

PING_INTERVAL = 4.0  # seconds between the game client's P (ping) updates
FIRST_PING_DELAY = 1.3  # ... the first one comes this long after joining
CLAUDE_ORANGE = "d97757"  # RRGGBB; sent as the game does: "0xRRGGBBAA"
APP_VERSION = "the_slammer_1.0"  # AppVersion in the game's Authenticate (captures)
GAME_SPEED_CHANGE = 96  # RPC id; one int argument
HANDSHAKE_CODES = range(9)  # RPCs 0..8: save-game transfer / authorisation
DIRECTORY_DATA = 9
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
console = Console()


# -- pure helpers -------------------------------------------------------------


def colour_property(rrggbb: str) -> str:
    """The game's colour property (``C``): ``0xRRGGBBAA`` with full alpha."""
    return "0x" + rrggbb.lstrip("#").lower() + "ff"


def speed_wire_value(index: int, *, speed_index: bool = False) -> int:
    """The int for ``GameSpeedChange``: the multiplier, or the stop's index."""
    return index if speed_index else SPEED_STOPS[index][1]


def render_slider(stops: Sequence[str], index: int) -> FormattedText:
    """Draw the slider: a bar filled up to ``index``, the labels under it."""
    count = len(stops)
    width = max(len(label) for label in stops) + 2
    half = width // 2
    on, off = "fg:ansicyan", "fg:ansibrightblack"
    bar: list[tuple[str, str]] = []
    names: list[tuple[str, str]] = []
    for i, label in enumerate(stops):
        bar.append((on if i <= index else off, ("━" if i else " ") * half))
        dot = "◉" if i == index else "●" if i < index else "○"
        bar.append(
            ("bold fg:ansibrightcyan" if i == index else on if i < index else off, dot)
        )
        bar.append(
            (
                on if i < index else off,
                ("━" if i < count - 1 else " ") * (width - half - 1),
            )
        )
        style = "bold reverse fg:ansibrightcyan" if i == index else off
        names.append((style, label.center(width)))
    title = ("bold", "Game speed\n\n")
    return FormattedText([title, *bar, ("", "\n"), *names])


def plain(text: FormattedText) -> str:
    """The text of formatted text without styles."""
    return "".join(part[1] for part in text)


def handle_key(index: int, key: str, count: int) -> tuple[int, str | None]:
    """Apply a key: returns the new index and ``"submit"`` / ``"cancel"`` / None."""
    if key in ("left", "h"):
        return max(index - 1, 0), None
    if key in ("right", "l"):
        return min(index + 1, count - 1), None
    if key == "home":
        return 0, None
    if key == "end":
        return count - 1, None
    if key == "enter":
        return index, "submit"
    if key in ("escape", "q", "c-c"):
        return index, "cancel"
    return index, None


def format_region(code: str, address: str) -> str:
    """One region menu line."""
    return f"{code:<8} {address}"


def format_room(room: RoomInfo) -> str:
    """One game menu line: name, players and whether it can be joined."""
    state = "open" if room.is_open else "closed"
    return f"{room.name}  ({room.player_count}/{room.max_players or '?'})  {state}"


def format_lobby(lobby: TypedLobby) -> str:
    """One lobby menu line."""
    return f"{lobby.name or '(default)'}  [{lobby.type.name}]"


def format_event_lines(
    sender: int, code: int, data: Any, *, verbose: bool = False
) -> list[str]:
    """Readable lines for one incoming game event (RPC ``code``)."""
    head = f"#{sender} "
    if not isinstance(data, (bytes, bytearray)):
        return [f"{head}event {code}: non-byte payload {data!r}"]
    data = bytes(data)
    tag = " [handshake]" if code in HANDSHAKE_CODES or code == DIRECTORY_DATA else ""
    if code == DIRECTORY_DATA and not verbose:
        try:
            name, blob = pa_events.decode_args(data)[:2]
            text = bytes(name).decode("utf-8", "replace")
            return [f"{head}{pa_rpc.rpc_name(code)}{tag}: {text!r}, {len(blob)} B"]
        except (ValueError, TypeError):
            return [f"{head}{pa_rpc.rpc_name(code)}{tag}: {len(data)} B"]
    try:
        lines = pa_rpc.format_rpc(pa_rpc.parse(code, data))
    except pa_rpc.RpcShapeError:
        try:
            lines = pa_events.format_event(code, data)
        except ValueError:
            lines = [f"event {code}: {data.hex(' ')}"]
    return [f"{head}{lines[0]}{tag}", *lines[1:]]


def split_address(spec: str) -> tuple[str, int]:
    """``host`` or ``host:port`` -> (host, port); port 0 = protocol default."""
    host, _, port = spec.partition(":")
    return host, int(port) if port else 0


def _load_dotenv(path: Path) -> None:
    """Put ``KEY=value`` lines of ``path`` into the environment (not overriding)."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            if key.strip():
                environ.setdefault(key.strip(), value.strip().strip("\"'"))


# -- slider UI ------------------------------------------------------------------


def pick_speed(index: int = 1, *, input: Any = None, output: Any = None) -> int | None:
    """Run the slider; the chosen stop's index, or None when cancelled."""
    state = {"index": index}
    keys = KeyBindings()
    names = ("left", "right", "enter", "escape", "home", "end", "c-c", "h", "l", "q")

    def make(name: str) -> Callable[[KeyPressEvent], None]:
        def handler(event: KeyPressEvent) -> None:
            state["index"], action = handle_key(state["index"], name, len(SPEED_STOPS))
            if action == "submit":
                event.app.exit(result=state["index"])
            elif action == "cancel":
                event.app.exit(result=None)

        return handler

    for name in names:
        keys.add(name, eager=True)(make(name))
    control = FormattedTextControl(
        lambda: FormattedText(
            [
                *render_slider([n for n, _ in SPEED_STOPS], state["index"]),
                ("", "\n\n"),
                ("fg:ansibrightblack", SPEED_HELP),
            ]
        )
    )
    app: Application[int | None] = Application(
        layout=Layout(Window(control, wrap_lines=True)),
        key_bindings=keys,
        input=input,
        output=output,
        erase_when_done=True,
    )
    return app.run()


# -- connection -----------------------------------------------------------------


@dataclass
class Options:
    """Command line settings shared by the commands."""

    app_id: str
    app_version: str = APP_VERSION
    name_server: str = ""
    region: str | None = None
    speed_index: bool = False
    verbose: bool = False
    name: str = "Claude"
    colour: str = CLAUDE_ORANGE


class Session(
    ConnectionCallbacks,
    MatchmakingCallbacks,
    LobbyCallbacks,
    OnEventCallback,
):
    """A ``RealtimeClient`` pumped by a background thread, plus what it saw."""

    def __init__(self, client: RealtimeClient | None = None) -> None:
        """Wrap ``client`` (a new one by default) and register for callbacks."""
        self.client = client or RealtimeClient()
        self.lock = threading.RLock()
        self.regions: dict[str, str] = {}
        self.events: deque[tuple[int, int, Any]] = deque(maxlen=5000)
        self.master = self.joined = self.lobby_joined = False
        self.disconnected: object | None = None
        self.join_error = ""
        self._stop = threading.Event()
        self._next_ping: float | None = None
        if (peer := getattr(self.client, "peer", None)) is not None:
            # Photon only measures its round trip from keep-alive pings, which
            # are sent when idle; ping often so the game's "P" is a real value.
            peer.keep_alive_interval = 1.0
        self._thread = threading.Thread(target=self._pump, daemon=True)
        self.client.add_callback_target(self)

    # callbacks (called from the service thread)
    def on_region_list_received(self, regions: dict[str, str]) -> None:
        """Keep the regions; a set ``cloud_region`` stops the library auto-pinging."""
        self.regions = regions
        if self.client.cloud_region is None:
            self.client.cloud_region = "-"

    def on_connected_to_master(self) -> None:
        """Mark the Master Server as reached."""
        self.master = True

    def on_joined_lobby(self) -> None:
        """Mark the lobby as joined."""
        self.lobby_joined = True

    def on_joined_room(self) -> None:
        """Mark the room as joined."""
        self.joined = True

    def on_join_room_failed(self, return_code: int, message: str) -> None:
        """Remember why joining failed."""
        self.join_error = f"{message} (code {return_code})"

    def on_disconnected(self, cause: object) -> None:
        """Remember the disconnect cause."""
        self.disconnected = cause

    def on_event(self, event: Any) -> None:
        """Queue custom (game) events: code 1-199, ``Data`` as raw bytes."""
        if not 0 < event.code < 200:
            return
        data = event.parameters.get(ParameterKey.Data)
        value = data.value if data is not None else None
        self.events.append((event.sender, event.code, value))

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
        return self.client.op_set_properties_of_actor(
            actor, {"P": int(peer.round_trip_time)}
        )

    def _pump(self) -> None:
        while not self._stop.is_set():
            with self.lock:
                self.client.service()
                self.report_ping(time.monotonic())
            time.sleep(1 / 30)

    def start(self, settings: AppSettings) -> None:
        """Connect and start the service thread."""
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

    def raise_event(self, code: int, data: bytes) -> bool:
        """Send a game RPC. ``bytes`` go out as an Int8Slice under key Data (245)."""
        with self.lock:
            return self.client.op_raise_event(code, data)

    def stop(self) -> None:
        """Disconnect cleanly and stop the thread (safe to call twice)."""
        with self.lock:
            self.client.disconnect()
        time.sleep(0.2)  # let the thread flush the disconnect
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=2)


def make_settings(opts: Options, region: str | None = None) -> AppSettings:
    """``AppSettings`` for ``opts``; the name server may be ``auto`` or host[:port]."""
    settings = AppSettings(
        app_id_realtime=opts.app_id,
        app_version=opts.app_version,
        fixed_region=region,
        enable_lobby_statistics=True,
    )
    if opts.name_server == "auto":
        from prison_architect import resolve_upstream

        host, port = resolve_upstream("auto")
        return replace(settings, name_server=host, name_server_port=port)
    if opts.name_server:
        host, port = split_address(opts.name_server)
        return replace(settings, name_server=host, name_server_port=port)
    return settings


def fetch_regions(opts: Options) -> dict[str, str]:
    """Ask the Name Server for its regions (read-only), then disconnect."""
    session = Session()
    try:
        session.start(make_settings(opts))
        if not session.wait_for(lambda: bool(session.regions)):
            raise typer.BadParameter("no region list received from the Name Server")
        return dict(session.regions)
    finally:
        session.stop()


def pick(message: str, choices: list[tuple[str, Any]]) -> Any:
    """An InquirerPy select over ``(label, value)`` pairs."""
    return inquirer.select(
        message=message,
        choices=[{"name": name, "value": value} for name, value in choices],
        raise_keyboard_interrupt=True,
    ).execute()


def join_flow(opts: Options, region: str) -> Session:
    """Connect to ``region``'s Master, pick a lobby and a game, join it."""
    session = Session()
    # Sent as the actor name (Photon player property 255), which the game shows.
    session.client.local_player.nick_name = opts.name
    try:
        session.start(make_settings(opts, region))
        if not session.wait_for(lambda: session.master):
            raise typer.BadParameter(f"could not reach region {region!r}")
        lobbies = [TypedLobby()]
        with session.lock:
            lobbies += [
                s.lobby
                for s in session.client.lobby_statistics
                if not s.lobby.is_default
            ]
        lobby = lobbies[0]
        if len(lobbies) > 1:
            lobby = pick("Lobby", [(format_lobby(x), x) for x in lobbies])
        with session.lock:
            session.client.op_join_lobby(lobby)
        session.wait_for(lambda: session.lobby_joined)
        if lobby.type == LobbyType.SqlLobby:
            with session.lock:
                session.client.op_get_game_list(lobby, "")
        time.sleep(1.5)  # the full room list arrives as an event right after
        with session.lock:
            rooms = list(session.client.room_list.values())
        if not rooms:
            raise typer.BadParameter("no games in this lobby")
        name = pick("Game", [(format_room(r), r.name) for r in rooms if r.is_open])
        with session.lock:
            session.client.op_join_room(
                EnterRoomParams(
                    room_name=name,
                    player_properties={"C": colour_property(opts.colour)},
                )
            )
        if not session.wait_for(lambda: session.joined or bool(session.join_error)):
            raise typer.BadParameter("joining timed out")
        if session.join_error:
            raise typer.BadParameter(f"join failed: {session.join_error}")
    except BaseException:
        session.stop()
        raise
    return session


# -- actions ----------------------------------------------------------------------


@dataclass
class Context:
    """What an action handler gets."""

    session: Session
    opts: Options
    log: list[str] = field(default_factory=list)


def action_speed(ctx: Context) -> None:
    """Pick a speed on the slider and send ``GameSpeedChange``."""
    index = pick_speed()
    if index is None:
        return
    value = speed_wire_value(index, speed_index=ctx.opts.speed_index)
    data = pa_rpc.build(GAME_SPEED_CHANGE, value)
    ok = ctx.session.raise_event(GAME_SPEED_CHANGE, data)
    mode = "index" if ctx.opts.speed_index else "multiplier"
    console.print(
        f"{'sent' if ok else 'NOT sent'} GameSpeedChange({value}) [{mode}] "
        f"event {GAME_SPEED_CHANGE}, Data={data.hex(' ')}  (unverified)",
        markup=False,
    )
    ctx.log.append(f"speed {SPEED_STOPS[index][0]} -> {value}")


def action_events(ctx: Context) -> None:
    """Stream incoming game events until Ctrl-C."""
    console.print("[dim]Streaming events, Ctrl-C to stop.[/dim]")
    try:
        while True:
            while ctx.session.events:
                sender, code, data = ctx.session.events.popleft()
                for line in format_event_lines(
                    sender, code, data, verbose=ctx.opts.verbose
                ):
                    console.print(line, markup=False, highlight=False)
            if ctx.session.disconnected is not None:
                console.print("[red]Disconnected.[/red]")
                return
            time.sleep(0.1)
    except KeyboardInterrupt:
        console.print()


# Add new RPC actions here: (menu label, handler taking a Context).
ACTIONS: list[tuple[str, Callable[[Context], None]]] = [
    ("Change game speed", action_speed),
    ("Show incoming events", action_events),
]


def menu(ctx: Context) -> None:
    """The in-game main menu; returns when the user leaves."""
    while ctx.session.disconnected is None:
        choice = pick(
            "Prison Architect bot",
            [*[(label, fn) for label, fn in ACTIONS], ("Leave / quit", None)],
        )
        if choice is None:
            return
        choice(ctx)


# -- typer ------------------------------------------------------------------------

app = typer.Typer(help=__doc__, invoke_without_command=True, no_args_is_help=False)


@app.callback()
def main(
    ctx: typer.Context,
    region: Annotated[
        str | None, typer.Option(help="Region code; skips the picker.")
    ] = None,
    app_id: Annotated[
        str | None,
        typer.Option(help="Photon App ID (env or .env: PHOTON_APP_ID)."),
    ] = None,
    app_version: Annotated[str, typer.Option(help="Photon AppVersion.")] = APP_VERSION,
    name_server: Annotated[
        str | None,
        typer.Option(
            help="Name Server host[:port], or 'auto' (resolve ns.exitgames.com over "
            "DNS-over-HTTPS) (env: PHOTON_NAME_SERVER). Needed when the hosts file "
            "points the name at 127.0.0.1 (the local proxy)."
        ),
    ] = None,
    speed_index: Annotated[
        bool,
        typer.Option(help="Send the stop index (0-4) instead of the multiplier."),
    ] = False,
    verbose: Annotated[
        bool, typer.Option(help="Show full DirectoryData events.")
    ] = False,
    name: Annotated[str, typer.Option(help="Actor name shown in the game.")] = "Claude",
    colour: Annotated[
        str, typer.Option(help="Actor colour, RRGGBB hex.")
    ] = CLAUDE_ORANGE,
) -> None:
    """Prison Architect bot (no subcommand: interactive)."""
    _load_dotenv(Path(__file__).with_name(".env"))
    app_id = app_id or environ.get("PHOTON_APP_ID", "")
    opts = Options(
        app_id,
        app_version,
        name_server or environ.get("PHOTON_NAME_SERVER", ""),
        region,
        speed_index,
        verbose,
        name,
        colour,
    )
    ctx.obj = opts
    if ctx.invoked_subcommand is None:
        require_app_id(opts)
        run(opts)


def require_app_id(opts: Options) -> None:
    """Fail with a clear message when no Photon App ID is configured."""
    if not opts.app_id:
        raise typer.BadParameter(
            "PHOTON_APP_ID is not set; use --app-id or put it in .env "
            "(the game's id is prison_architect.PRISON_ARCHITECT_APP_ID)."
        )


@app.command()
def regions(ctx: typer.Context) -> None:
    """List the Photon regions (read-only)."""
    require_app_id(ctx.obj)
    for code, address in fetch_regions(ctx.obj).items():
        console.print(format_region(code, address), markup=False)


def run(opts: Options) -> None:
    """The interactive flow: region, lobby, game, menu."""
    session: Session | None = None
    try:
        region = opts.region
        if region is None:
            found = fetch_regions(opts)
            region = pick(
                "Region", [(format_region(c, a), c) for c, a in found.items()]
            )
        session = join_flow(opts, region)
        menu(Context(session, opts))
    except KeyboardInterrupt:
        console.print("\nInterrupted, disconnecting.")
    finally:
        if session is not None:
            session.stop()


if __name__ == "__main__":
    app()
