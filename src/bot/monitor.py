"""Real-time monitoring of live games across Photon regions."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from pyphotonrealtime.realtime.lobby import TypedLobby
from pyphotonrealtime.realtime.room import RoomInfo
from rich.console import Console
from rich.live import Live
from rich.table import Table

from src.bot.flow import connect
from src.bot.formatting import room_players
from src.bot.session import Options, Session, fetch_regions
from src.capture import Recorder

log = logging.getLogger(__name__)

DEFAULT_INTERVAL = 3.0
LOBBY_WAIT_TIMEOUT = 10.0


def build_games_table(
    regional_rooms: dict[str, list[RoomInfo]],
    *,
    statuses: dict[str, str] | None = None,
    interval: float = DEFAULT_INTERVAL,
    updated_at: str | None = None,
) -> Table:
    """A Rich :class:`Table` displaying live games grouped by region."""
    updated = updated_at or datetime.now().strftime("%H:%M:%S")

    total_games = sum(len(rooms) for rooms in regional_rooms.values())
    total_players = sum(
        sum(r.player_count for r in rooms) for rooms in regional_rooms.values()
    )
    region_count = len(regional_rooms)

    title = (
        f"[bold cyan]Prison Architect Live Games[/bold cyan] "
        f"({total_games} game{'s' if total_games != 1 else ''}, "
        f"{total_players} player{'s' if total_players != 1 else ''} "
        f"in {region_count} region{'s' if region_count != 1 else ''})"
    )
    caption = f"Updated: {updated} | Refresh: every {interval:.1f}s | Ctrl-C to stop"

    table = Table(title=title, caption=caption, expand=False)
    table.add_column("Region", style="cyan", justify="center")
    table.add_column("Game Name", style="bold")
    table.add_column("Players", justify="center")
    table.add_column("State", justify="center")
    table.add_column("Players in Game")

    if not total_games:
        status_info = ""
        if statuses:
            parts = [f"{reg}: {st}" for reg, st in sorted(statuses.items())]
            status_info = f" ({', '.join(parts)})"
        table.add_row(
            "-",
            f"[dim]No live games currently active{status_info}[/dim]",
            "-",
            "-",
            "-",
        )
        return table

    for region in sorted(regional_rooms):
        rooms = regional_rooms[region]
        for room in sorted(rooms, key=lambda r: r.name.lower()):
            max_p = str(room.max_players) if room.max_players else "?"
            p_count = room.player_count
            if room.max_players and p_count >= room.max_players:
                players_styled = f"[yellow]{p_count} / {max_p}[/yellow]"
            elif p_count > 0:
                players_styled = f"[green]{p_count} / {max_p}[/green]"
            else:
                players_styled = f"[dim]{p_count} / {max_p}[/dim]"

            state_styled = (
                "[green]open[/green]" if room.is_open else "[red]closed[/red]"
            )

            players = room_players(room)
            mas = room.custom_properties.get("MAS") or room.custom_properties.get(
                "GameMaster"
            )
            if mas and isinstance(mas, str):
                mas = mas.strip()

            formatted_players: list[str] = []
            for p in players:
                if p == mas:
                    formatted_players.append(f"{p} [dim](host)[/dim]")
                else:
                    formatted_players.append(p)

            if formatted_players:
                players_col = ", ".join(formatted_players)
            elif p_count > 0:
                players_col = f"[dim]{p_count} player(s)[/dim]"
            else:
                players_col = "[dim]none[/dim]"

            table.add_row(
                region,
                room.name,
                players_styled,
                state_styled,
                players_col,
            )

    return table


class GameMonitor:
    """Manages lobby sessions across regions to monitor live games."""

    def __init__(
        self,
        opts: Options,
        regions: list[str],
        recorder: Recorder | None = None,
        session_factory: (
            Callable[[Options, str, Recorder | None], Session] | None
        ) = None,
    ) -> None:
        self.opts = opts
        self.regions = regions
        self.recorder = recorder
        self._factory = session_factory or connect
        self._sessions: dict[str, Session] = {}
        self._statuses: dict[str, str] = {r: "starting" for r in regions}
        self._lock = threading.Lock()

    def start(self) -> None:
        """Connect to each region and join its default lobby."""
        log.info("starting game monitor for regions: %s", ", ".join(self.regions))
        if len(self.regions) == 1:
            self._connect_region(self.regions[0])
            return

        with ThreadPoolExecutor(max_workers=min(len(self.regions), 8)) as pool:
            futures = [
                pool.submit(self._connect_region, region) for region in self.regions
            ]
            for f in futures:
                try:
                    f.result()
                except Exception:
                    log.exception("region connect error")

    def _connect_region(self, region: str) -> None:
        try:
            self._statuses[region] = "connecting"
            session = self._factory(self.opts, region, self.recorder)
            with session.lock:
                session.client.op_join_lobby(TypedLobby())
            session.wait_for(lambda: session.lobby_joined, timeout=LOBBY_WAIT_TIMEOUT)
            with self._lock:
                self._sessions[region] = session
                self._statuses[region] = "connected"
            log.info("connected to lobby in region %s", region)
        except Exception as exc:
            log.warning("failed to connect to region %s: %s", region, exc)
            with self._lock:
                self._statuses[region] = f"error: {exc}"

    def snapshot(self) -> dict[str, list[RoomInfo]]:
        """A copy of all currently active rooms per region."""
        result: dict[str, list[RoomInfo]] = {}
        with self._lock:
            for region, session in list(self._sessions.items()):
                if session.disconnected is not None:
                    self._statuses[region] = f"disconnected: {session.disconnected}"
                with session.lock:
                    rooms = [
                        r
                        for r in session.client.room_list.values()
                        if not r.removed_from_list
                    ]
                result[region] = rooms
        return result

    @property
    def statuses(self) -> dict[str, str]:
        """Current status per region."""
        with self._lock:
            return dict(self._statuses)

    def stop(self) -> None:
        """Disconnect all region sessions."""
        log.info("stopping game monitor")
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            try:
                session.stop()
            except Exception:
                log.exception("error stopping session")

    def __enter__(self) -> GameMonitor:
        self.start()
        return self

    def __exit__(self, *args: object) -> None:
        self.stop()


def run_monitor(
    opts: Options,
    *,
    region: str | None = None,
    interval: float = DEFAULT_INTERVAL,
    once: bool = False,
    recorder: Recorder | None = None,
    console: Console | None = None,
    monitor_factory: Callable[..., GameMonitor] | None = None,
) -> None:
    """Run the live monitoring loop."""
    c = console or Console()
    target_region = region or opts.region

    if target_region:
        regions = [target_region]
    else:
        c.print("[cyan]Querying available regions...[/cyan]")
        available = fetch_regions(opts, recorder)
        regions = list(available.keys())
        if not regions:
            c.print("[red]No regions available.[/red]")
            return

    c.print(
        f"[green]Monitoring games in {len(regions)} region(s):[/green] "
        f"{', '.join(regions)}"
    )

    create_monitor = monitor_factory or GameMonitor
    with create_monitor(opts, regions, recorder) as monitor:
        # Give initial room lists a moment to arrive
        time.sleep(1.0)
        snapshot = monitor.snapshot()
        table = build_games_table(
            snapshot,
            statuses=monitor.statuses,
            interval=interval,
        )

        if once:
            c.print(table)
            return

        with Live(table, console=c, refresh_per_second=2) as live:
            while True:
                time.sleep(interval)
                snapshot = monitor.snapshot()
                live.update(
                    build_games_table(
                        snapshot,
                        statuses=monitor.statuses,
                        interval=interval,
                    )
                )
