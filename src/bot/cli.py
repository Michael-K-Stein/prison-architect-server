"""Interactive Prison Architect bot: pick a region, a game, then send RPCs.

``python main.py bot`` connects to Photon, lists regions, lobbies and games, joins the
chosen game and opens a live HUD: game state, and every known action.

Debugging: ``--log-file PATH`` writes the bot's steps (and, at ``-v debug``, every
event and ping) to a file; the console stays the TUI. ``-o PATH`` (``--record``)
saves every packet the bot sends and receives, decrypted, into a capture file that
``python main.py capture tail PATH`` reads.
"""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from enum import Enum
from os import environ
from pathlib import Path
from typing import Annotated
from urllib.parse import quote

import typer
from rich.console import Console

from src.bot.broadcast import SPEAKERS, speaker_index
from src.bot.control import DEFAULT_PORT, ControlServer, call
from src.bot.flow import join_flow, join_room, pick
from src.bot.formatting import format_region
from src.bot.hud import run_hud
from src.bot.reconnect import Reconnector
from src.bot.room_cli import building_app, door_app, room_app
from src.bot.session import (
    APP_VERSION,
    CLAUDE_ORANGE,
    ConnectError,
    Options,
    Session,
    fetch_regions,
)
from src.capture import Recorder
from src.env import ENV_PATH, load_env
from src.logs import LOG_LEVELS, default_log_level, setup_logging

LogLevel = Enum("LogLevel", {n: n for n in LOG_LEVELS}, type=str)
console = Console()
log = logging.getLogger(__name__)

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
    full_events: Annotated[
        bool, typer.Option(help="Show full DirectoryData events.")
    ] = False,
    name: Annotated[str, typer.Option(help="Actor name shown in the game.")] = "Claude",
    colour: Annotated[
        str, typer.Option(help="Actor colour, RRGGBB hex.")
    ] = CLAUDE_ORANGE,
    log_file: Annotated[
        Path | None,
        typer.Option(
            help="Append the bot's log to this file (nothing is logged to the "
            "console). Without it, logging is not configured."
        ),
    ] = None,
    log_level: Annotated[
        LogLevel | None,
        typer.Option(
            "-v",
            "--verbose",
            case_sensitive=False,
            help="Log level for --log-file. debug adds every event and ping.",
            show_default="$LOG_LEVEL or info",
        ),
    ] = None,
    record: Annotated[
        Path | None,
        typer.Option(
            "-o",
            "--record",
            help="Record every packet the bot sends and receives (decrypted) into "
            "this capture file, for `capture tail` and `capture sessions`.",
        ),
    ] = None,
    password: Annotated[
        str,
        typer.Option(
            help="The game's password; sent after joining to ask the host for the "
            "full save (env: PA_PASSWORD).",
        ),
    ] = "",
) -> None:
    """Prison Architect bot (no subcommand: interactive)."""
    load_env(ENV_PATH)
    if log_file is not None:
        setup_logging(
            log_level.value if log_level else default_log_level(),
            log_file=log_file,
            console=False,
        )
    app_id = app_id or environ.get("PHOTON_APP_ID", "")
    opts = Options(
        app_id=app_id,
        app_version=app_version,
        name_server=name_server or environ.get("PHOTON_NAME_SERVER", ""),
        region=region,
        speed_index=speed_index,
        full_events=full_events,
        name=name,
        colour=colour,
        record=record,
        password=password or environ.get("PA_PASSWORD", ""),
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
            "(the game's id is src.server.server.PRISON_ARCHITECT_APP_ID)."
        )


@contextmanager
def recording(opts: Options) -> Iterator[Recorder | None]:
    """A :class:`Recorder` for ``opts.record`` (closed on exit), or None."""
    if opts.record is None:
        yield None
        return
    opts.record.parent.mkdir(parents=True, exist_ok=True)
    with Recorder(opts.record) as recorder:
        log.info("recording the bot's traffic to %s", opts.record)
        yield recorder


@app.command()
def regions(ctx: typer.Context) -> None:
    """List the Photon regions (read-only)."""
    require_app_id(ctx.obj)
    with recording(ctx.obj) as recorder:
        for code, address in fetch_regions(ctx.obj, recorder).items():
            console.print(format_region(code, address), markup=False)


def run(opts: Options) -> None:
    """The interactive flow: region, lobby, game, menu."""
    session: Session | None = None
    with recording(opts) as recorder:
        try:
            region = opts.region
            if region is None:
                found = fetch_regions(opts, recorder)
                region = pick(
                    "Region", [(format_region(c, a), c) for c, a in found.items()]
                )
            log.info("region: %s", region)
            session = join_flow(opts, region, recorder)
            session.request_save(opts.password)
            run_hud(session, opts)
        except KeyboardInterrupt:
            log.info("interrupted by the user")
            console.print("\nInterrupted, disconnecting.")
        except ConnectError as exc:
            log.error("bot stopped: %s", exc)
            console.print(f"[red]Error:[/red] {exc}", markup=True, highlight=False)
            raise typer.Exit(1) from None
        except Exception:
            log.exception("bot stopped with an error")
            raise
        finally:
            if session is not None:
                session.stop()


@app.command()
def serve(
    ctx: typer.Context,
    room: Annotated[
        str | None, typer.Option(help="Game (room) name; default: the first open one.")
    ] = None,
    port: Annotated[int, typer.Option(help="Control server port.")] = DEFAULT_PORT,
    reconnect: Annotated[
        bool,
        typer.Option(
            help="Resync after land purchases and rejoin when the host goes silent "
            "or the connection drops."
        ),
    ] = True,
) -> None:
    """Join a game headless and serve the JSON control API (see `bot ctl`)."""
    opts: Options = ctx.obj
    require_app_id(opts)
    if opts.region is None:
        raise typer.BadParameter(
            "serve needs a region: pass --region before `serve` "
            "(`bot regions` lists them)."
        )
    session: Session | None = None
    server: ControlServer | None = None
    with recording(opts) as recorder:
        try:
            session = join_room(opts, opts.region, room, recorder)
            session.request_save(opts.password)
            server = ControlServer(session, port)
            server.start()
            console.print(f"control server: {server.url}", markup=False)
            if reconnect:
                server.auto_reconnect = True
                Reconnector(
                    server,
                    lambda: join_room(opts, opts.region, room, recorder),
                    opts.password,
                ).start()
            reason = server.wait()
            log.info("serve stopped: %s", reason)
            if reason == "disconnected":
                console.print(
                    f"Disconnected: {server.session.disconnected}", markup=False
                )
        except KeyboardInterrupt:
            log.info("interrupted by the user")
            console.print("\nInterrupted, disconnecting.")
        except ConnectError as exc:
            log.error("bot stopped: %s", exc)
            console.print(f"[red]Error:[/red] {exc}", markup=True, highlight=False)
            raise typer.Exit(1) from None
        finally:
            if server is not None:
                server.stop()
                session = server.session  # a reconnect may have replaced it
            if session is not None:
                session.stop()


ctl = typer.Typer(help="Talk to a running `bot serve` (prints JSON).")
app.add_typer(ctl, name="ctl")


@ctl.callback()
def ctl_main(
    ctx: typer.Context,
    port: Annotated[int, typer.Option(help="Control server port.")] = DEFAULT_PORT,
) -> None:
    """Client for the control server on 127.0.0.1."""
    ctx.obj = port


def _show(ctx: typer.Context, method: str, path: str, body: dict | None = None) -> None:
    try:
        status, data = call(method, path, body, port=ctx.obj)
    except OSError as exc:
        typer.echo(json.dumps({"error": f"no control server: {exc}"}, indent=1))
        raise typer.Exit(1) from None
    typer.echo(json.dumps(data, indent=1))
    if status >= 400:
        raise typer.Exit(1)


def _fail(message: str) -> None:
    typer.echo(json.dumps({"error": message}, indent=1))
    raise typer.Exit(1)


def _rect(
    x: int | None, y: int | None, width: int, height: int, zone: str | None
) -> dict:
    """A job's area: the named zone (resolved by the server) or X Y W H."""
    if zone:
        return {"zone": zone}
    if x is None or y is None:
        _fail("give X Y or --zone NAME")
    return {"x": x, "y": y, "width": width, "height": height}


@ctl.command("state")
def ctl_state(
    ctx: typer.Context,
    system: Annotated[str | None, typer.Argument(help="System, e.g. World.")] = None,
    path: Annotated[str | None, typer.Argument(help="Child path, a/b.")] = None,
    depth: Annotated[int, typer.Option(help="Child levels (-1: all).")] = -1,
    raw: Annotated[
        bool, typer.Option(help="Show the short network keys without long names.")
    ] = False,
) -> None:
    """The game state summary, or one system/node (short keys get long names)."""
    if system is None:
        _show(ctx, "GET", "/state")
        return
    node = "/".join(x.strip("/") for x in (system, path or "") if x.strip("/"))
    _show(ctx, "GET", f"/state/{quote(node)}?depth={depth}{'&raw=1' if raw else ''}")


@ctl.command("keys")
def ctl_keys(
    system: Annotated[str | None, typer.Argument(help="e.g. ObjectData.")] = None,
) -> None:
    """What the short snapshot keys (`st`, `ci`, `ts`...) stand for."""
    from src.protocol.net_keys import KEYS

    typer.echo(json.dumps(KEYS.get(system, KEYS) if system else KEYS, indent=1))


@ctl.command("rules")
def ctl_rules(
    room: Annotated[
        str | None, typer.Argument(help="e.g. Kitchen; all if omitted.")
    ] = None,
) -> None:
    """What a room needs to count (size, objects), from the game's data."""
    from src.protocol.room_rules import ROOM_RULES, describe

    names = [room] if room else sorted(ROOM_RULES)
    typer.echo(
        json.dumps([describe(n) or f"unknown room {n!r}" for n in names], indent=1)
    )


@ctl.command("research")
def ctl_research(
    name: Annotated[
        str | None, typer.Argument(help="e.g. Cctv; all if omitted.")
    ] = None,
) -> None:
    """What each research needs (staff to hire, prerequisite, cost), from the game data."""
    from src.protocol.research_rules import RESEARCH_RULES, describe

    names = [name] if name else list(RESEARCH_RULES)
    typer.echo(json.dumps([describe(n) or f"unknown {n!r}" for n in names], indent=1))


@ctl.command("actions")
def ctl_actions(
    ctx: typer.Context,
    kind: Annotated[
        str | None, typer.Option(help="player, host or handshake (default: all).")
    ] = None,
    show_all: Annotated[
        bool, typer.Option("--all", help="Include blocked actions.")
    ] = False,
) -> None:
    """The RPC actions and their arguments."""
    query = f"?all={int(show_all)}" + (f"&kind={quote(kind)}" if kind else "")
    _show(ctx, "GET", "/actions" + query)


@ctl.command("action")
def ctl_action(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Action name or RPC code.")],
) -> None:
    """One action's arguments with their choices from the live state."""
    _show(ctx, "GET", f"/actions/{quote(name)}")


@ctl.command("send")
def ctl_send(
    ctx: typer.Context,
    action: Annotated[str, typer.Argument(help="Action name or RPC code.")],
    args: Annotated[list[str] | None, typer.Argument(help="Arguments as text.")] = None,
    broadcast: Annotated[
        bool,
        typer.Option(help="Send to every other player, not only the host."),
    ] = False,
) -> None:
    """Send one RPC (to the host; --broadcast: to everyone else)."""
    body = {"action": action, "args": args or [], "broadcast": broadcast}
    _show(ctx, "POST", "/send", body)


@ctl.command("broadcast")
def ctl_broadcast(
    ctx: typer.Context,
    message: Annotated[str, typer.Argument(help="What the adviser says.")],
    speaker: Annotated[
        str | None,
        typer.Option(
            "--from",
            help=f"Who speaks: {', '.join(SPEAKERS)}. Asks from a list if omitted.",
        ),
    ] = None,
    to: Annotated[
        str,
        typer.Option(
            help="Who receives it: everyone (default: every other player) or host "
            "(the host only).",
        ),
    ] = "everyone",
) -> None:
    """Show a message spoken by an adviser, to every player or to the host only."""
    if to not in ("everyone", "host"):
        raise typer.BadParameter("--to must be everyone or host")
    if speaker is None:
        if not sys.stdin.isatty():
            raise typer.BadParameter("--from is required without a terminal")
        speaker = pick(
            "Who speaks?",
            [(f"The {name}", name) for name in SPEAKERS],
        )
    try:
        index = speaker_index(speaker)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from None
    body = {
        "action": "NewSpeechAdded",
        "args": [str(index), message],
        "broadcast": to == "everyone",
    }
    _show(ctx, "POST", "/send", body)


@ctl.command("build")
def ctl_build(
    ctx: typer.Context,
    tool: Annotated[
        str,
        typer.Argument(
            help="foundation, wall, floor, room, place, line (pipes/cables) or demolish."
        ),
    ],
    x: Annotated[int | None, typer.Argument(help="Left cell.")] = None,
    y: Annotated[int | None, typer.Argument(help="Top cell.")] = None,
    width: Annotated[int, typer.Argument(help="Cells wide (not for place).")] = 1,
    height: Annotated[int, typer.Argument(help="Cells high (not for place).")] = 1,
    name: Annotated[
        str | None,
        typer.Option(
            "--name",
            "-n",
            help="Material (foundation/wall/floor), room kind (room, default "
            "Cell) or object (place, e.g. Bed). See `ctl names`.",
        ),
    ] = None,
    facing: Annotated[
        str | None, typer.Option(help="place: down, up, left or right.")
    ] = None,
    zone: Annotated[
        str | None,
        typer.Option(
            "--zone", "-z", help="A named zone (`ctl zone`) instead of X Y W H."
        ),
    ] = None,
) -> None:
    """Build: e.g. `build foundation 10 10 5 5`, `build place 11 11 -n Bed`."""
    spec: dict = {"tool": tool, **_rect(x, y, width, height, zone)}
    key = {"room": "kind", "place": "object", "line": "object"}.get(tool, "material")
    if name:
        spec[key] = name
    if facing:
        spec["facing"] = facing
    _show(ctx, "POST", "/build", {"jobs": [spec]})


name_app = typer.Typer(
    help="Name objects/rooms so commands and output use the name, not an index."
)
ctl.add_typer(name_app, name="name")


@name_app.command("set")
def ctl_name_set(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="e.g. Main_Power_Station.")],
    ref: Annotated[str, typer.Argument(help="Object index (52, #52) or uId,index.")],
    room: Annotated[bool, typer.Option("--room", help="REF is a room index.")] = False,
) -> None:
    """Name an object: `ctl name set Main_Power_Station 52`."""
    _show(ctx, "POST", "/alias", {"set": name, "ref": ref, "room": room})


@name_app.command("rm")
def ctl_name_rm(
    ctx: typer.Context, name: Annotated[str, typer.Argument(help="The name.")]
) -> None:
    """Forget a name."""
    _show(ctx, "POST", "/alias", {"remove": name})


@name_app.command("list")
def ctl_name_list(ctx: typer.Context) -> None:
    """All names of this game and what they point at."""
    _show(ctx, "GET", "/alias")


@ctl.command("network")
def ctl_network(
    ctx: typer.Context,
    utility: Annotated[
        str, typer.Argument(help="Utility to validate.")
    ] = "electricity",
) -> None:
    """Validate a utility's lines: each network, what feeds it, what is wrong.

    Electricity: raw green energy (generators' lines) must reach consumers only
    through a Transformer. Reads the last save: `ctl refresh` first after building.
    """
    _show(ctx, "GET", f"/network?utility={quote(utility)}")


zone_app = typer.Typer(
    help="Name map rectangles (Food_Zone) and use them with --zone in area/build/demolish."
)
ctl.add_typer(zone_app, name="zone")


@zone_app.command("set")
def ctl_zone_set(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="e.g. Food_Zone.")],
    x: Annotated[int, typer.Argument(help="Left cell.")],
    y: Annotated[int, typer.Argument(help="Top cell.")],
    width: Annotated[int, typer.Argument(help="Cells wide.")],
    height: Annotated[int, typer.Argument(help="Cells high.")],
) -> None:
    """Name a rectangle: `ctl zone set Food_Zone 20 66 20 7`."""
    body = {"set": name, "x": x, "y": y, "w": width, "h": height}
    _show(ctx, "POST", "/zone", body)


@zone_app.command("rm")
def ctl_zone_rm(
    ctx: typer.Context, name: Annotated[str, typer.Argument(help="The zone.")]
) -> None:
    """Forget a zone."""
    _show(ctx, "POST", "/zone", {"remove": name})


@zone_app.command("list")
def ctl_zone_list(ctx: typer.Context) -> None:
    """All zones of this game."""
    _show(ctx, "GET", "/zone")


@ctl.command("raw")
def ctl_raw(
    ctx: typer.Context,
    job_type: Annotated[str, typer.Argument(help="Job Type, e.g. DismantleObject.")],
    x: Annotated[int, typer.Argument(help="Cell x.")],
    y: Annotated[int, typer.Argument(help="Cell y.")],
    width: Annotated[int, typer.Argument(help="Cells wide.")] = 1,
    height: Annotated[int, typer.Argument(help="Cells high.")] = 1,
    material: Annotated[int, typer.Option(help="Numeric Material.")] = 0,
) -> None:
    """Send any Construction job type (experiments)."""
    spec = {"tool": "raw", "type": job_type, "x": x, "y": y}
    spec |= {"width": width, "height": height, "material": material}
    _show(ctx, "POST", "/build", {"jobs": [spec]})


@ctl.command("hints")
def ctl_hints(
    ctx: typer.Context,
    topic: Annotated[
        str | None,
        typer.Argument(help="doors, entrance, power, green, people, grants or build."),
    ] = None,
    object_name: Annotated[
        str | None,
        typer.Option(
            "--object", help="Full game hint for one object, e.g. Transformer."
        ),
    ] = None,
) -> None:
    """Game rules to remember (also shown in action details and command replies)."""
    if object_name:
        _show(ctx, "GET", f"/hints?object={quote(object_name)}")
        return
    _show(ctx, "GET", "/hints" + (f"?topic={topic}" if topic else ""))


@ctl.command("staff")
def ctl_staff(ctx: typer.Context) -> None:
    """Energy and rest status of every staff member (exhausted / tired / ok)."""
    _show(ctx, "GET", "/staff")


@ctl.command("wires")
def ctl_wires(
    ctx: typer.Context,
    request: Annotated[
        bool,
        typer.Option("--request", help="Send WireDataRequested (94) first and wait."),
    ] = False,
) -> None:
    """Which objects are wired to which (export meter -> Transformer links)."""
    _show(ctx, "GET", "/wires" + ("?request=1" if request else ""))


ISSUES_FILE = Path("bot-issues.jsonl")
"""Where `ctl issue` appends: one JSON object per line, read by the bot's maintainer."""


ctl.add_typer(room_app, name="room")
ctl.add_typer(building_app, name="building")
ctl.add_typer(door_app, name="door")


@ctl.command("issue")
def ctl_issue(
    text: Annotated[str, typer.Argument(help="What blocks you, and which task.")],
    task: Annotated[
        str, typer.Option("--task", help="The task it blocks (e.g. 'build Library').")
    ] = "",
) -> None:
    """Report a missing or broken bot feature that blocks a task (then do other work)."""
    import time

    entry = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "task": task, "issue": text}
    with ISSUES_FILE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")
    typer.echo(json.dumps({"filed": entry}, indent=1))


LAND_PRICE_PER_CELL = 5.088
"""About what the host charges per cell (journal2: 100x10 cells cost 5088)."""


@ctl.command("land")
def ctl_land(
    ctx: typer.Context,
    where: Annotated[
        str,
        typer.Argument(help="info, south N, east N, or buy X Y W H (new cells)."),
    ] = "info",
    numbers: Annotated[
        list[int] | None, typer.Argument(help="N rows/columns, or X Y W H.")
    ] = None,
    speed: Annotated[
        int, typer.Option(help="Game speed to restore (the host resets it to 1).")
    ] = 10,
) -> None:
    """Show or buy land: `land` (size, price), `land south 20`, `land east 10`,
    `land buy X Y W H`. A purchase costs about 5 per cell and resets the game speed."""
    port = ctx.obj
    numbers = numbers or []
    try:
        _, save = call("GET", "/state/Save?depth=0", port=port)
        w, h = int(save["NumCellsX"]), int(save["NumCellsY"])
        balance = float(save["Balance"])
        info = {
            "map": [w, h],
            "origin": [save.get("OriginW"), save.get("OriginH")],
            "balance": balance,
            "price_per_cell": LAND_PRICE_PER_CELL,
        }
        if where == "info":
            typer.echo(json.dumps(info, indent=1))
            return
        if where in ("south", "east") and len(numbers) == 1 and numbers[0] > 0:
            n = numbers[0]
            rect = (0, h, w, n) if where == "south" else (w, 0, n, h)
        elif where == "buy" and len(numbers) == 4 and min(numbers) >= 0:
            rect = tuple(numbers)
        else:
            _fail("usage: land | land south N | land east N | land buy X Y W H")
        cost = rect[2] * rect[3] * LAND_PRICE_PER_CELL
        if cost > balance:
            _fail(f"about {cost:.0f} needed, balance is {balance:.0f}")
        status, data = call(
            "POST",
            "/send",
            {"action": "LandPurchaseRequest", "args": [*rect, False, True]},
            port=port,
        )
        if status >= 400:
            _fail(f"refused: {data}")
        after = save
        for _ in range(5):  # the host applies it within a few seconds
            call("POST", "/refresh", {"seconds": 5}, port=port)
            _, after = call("GET", "/state/Save?depth=0", port=port)
            if [after["NumCellsX"], after["NumCellsY"]] != [w, h]:
                break
        call(
            "POST",
            "/send",
            {"action": "GameSpeedChange", "args": [speed]},
            port=port,
        )
    except OSError as exc:
        _fail(f"no control server: {exc}")
    grown = [int(after["NumCellsX"]), int(after["NumCellsY"])]
    typer.echo(
        json.dumps(
            {
                "requested": list(rect),
                "map": grown,
                "grew": grown != [w, h],
                "spent": round(balance - float(after["Balance"])),
                "speed_restored": speed,
            },
            indent=1,
        )
    )


@ctl.command("connect")
def ctl_connect(
    ctx: typer.Context,
    kind: Annotated[str, typer.Argument(help="power or water.")],
    apply: Annotated[
        bool, typer.Option("--apply", help="Send the planned cables / pipes.")
    ] = False,
) -> None:
    """Plan (and with --apply lay) the cables or pipes that connect every unserved
    object (no power / no water) to the nearest fed network by the shortest route.

    Cables never touch the raw green network; pipes end ON each appliance's cell.
    Refresh first (`ctl refresh`), and again after the workmen finished.
    """
    port = ctx.obj
    try:
        status, plan = call("GET", f"/connect?kind={quote(kind)}", port=port)
    except OSError as exc:
        _fail(f"no control server: {exc}")
    if status >= 400 or "error" in plan:
        _fail(str(plan.get("error", plan)))
    sent = 0
    if apply and plan["jobs"]:
        for i in range(0, len(plan["jobs"]), 40):
            batch = plan["jobs"][i : i + 40]
            status, data = call("POST", "/build", {"jobs": batch}, port=port)
            if status >= 400:
                _fail(f"refused: {data}")
            sent += len(batch)
    typer.echo(
        json.dumps(
            {
                "targets": plan["targets"],
                "runs": len(plan["jobs"]),
                "sent": sent,
                "skipped": plan["skipped"],
                "jobs": [] if apply else plan["jobs"],
                "next": "wait for the workmen, `ctl refresh`, check `problems`",
            },
            indent=1,
        )
    )


@ctl.command("todo")
def ctl_todo(ctx: typer.Context) -> None:
    """The in-game Todo list: objectives, staff alerts now showing (with the game's advice)
    and the intake state: what the game wants done next."""
    _show(ctx, "GET", "/todo")


@ctl.command("alerts")
def ctl_alerts(
    ctx: typer.Context,
    since: Annotated[int, typer.Option(help="Only alerts after this number.")] = 0,
    new: Annotated[bool, typer.Option(help="Only the ones not yet delivered.")] = False,
) -> None:
    """Staff alerts and advisor speech with the game's advice (what to do next).

    Unseen alerts also ride on the next reply of any command as `alerts_new`.
    """
    _show(ctx, "GET", f"/alerts?since={since}" + ("&new=1" if new else ""))


@ctl.command("hire")
def ctl_hire(
    ctx: typer.Context,
    role: Annotated[str, typer.Argument(help="Guard, Cook, Doctor, Warden, Workman.")],
    count: Annotated[int, typer.Argument(help="How many to hire.")] = 1,
) -> None:
    """Hire staff (a `Staff` construction job per person), e.g. `hire Guard 2`."""
    _show(ctx, "POST", "/build", {"jobs": [{"tool": "hire", "role": role}] * count})


@ctl.command("demolish")
def ctl_demolish(
    ctx: typer.Context,
    x: Annotated[int | None, typer.Argument(help="Left cell.")] = None,
    y: Annotated[int | None, typer.Argument(help="Top cell.")] = None,
    width: Annotated[int, typer.Argument(help="Cells wide.")] = 1,
    height: Annotated[int, typer.Argument(help="Cells high.")] = 1,
    name: Annotated[
        str,
        typer.Option(
            "--name",
            "-n",
            help="Demolish (bulldoze), DemolishWalls, ClearIndoorArea or RemoveTunnels.",
        ),
    ] = "Demolish",
    zone: Annotated[
        str | None,
        typer.Option(
            "--zone", "-z", help="A named zone (`ctl zone`) instead of X Y W H."
        ),
    ] = None,
) -> None:
    """Bulldoze an area; then DemolishWalls, then ClearIndoorArea to clear a building."""
    spec = {"tool": "demolish", **_rect(x, y, width, height, zone)}
    _show(ctx, "POST", "/build", {"jobs": [{**spec, "material": name}]})


@ctl.command("priority")
def ctl_priority(
    ctx: typer.Context,
    x: Annotated[int | None, typer.Argument(help="Left cell.")] = None,
    y: Annotated[int | None, typer.Argument(help="Top cell.")] = None,
    width: Annotated[int, typer.Argument(help="Cells wide.")] = 1,
    height: Annotated[int, typer.Argument(help="Cells high.")] = 1,
    zone: Annotated[
        str | None,
        typer.Option(
            "--zone", "-z", help="A named zone (`ctl zone`) instead of X Y W H."
        ),
    ] = None,
) -> None:
    """Make the queued work jobs in an area HIGH PRIORITY (the client's priority tool)."""
    spec = {"tool": "priority", **_rect(x, y, width, height, zone)}
    _show(ctx, "POST", "/build", {"jobs": [spec]})


@ctl.command("dismantle")
def ctl_dismantle(
    ctx: typer.Context,
    x: Annotated[int | None, typer.Argument(help="Left cell.")] = None,
    y: Annotated[int | None, typer.Argument(help="Top cell.")] = None,
    width: Annotated[int, typer.Argument(help="Cells wide.")] = 1,
    height: Annotated[int, typer.Argument(help="Cells high.")] = 1,
    objects: Annotated[
        bool,
        typer.Option(
            "--objects", help="Dismantle objects (DismantleObject), not cables/pipes."
        ),
    ] = False,
    zone: Annotated[
        str | None,
        typer.Option(
            "--zone", "-z", help="A named zone (`ctl zone`) instead of X Y W H."
        ),
    ] = None,
) -> None:
    """Remove cables and pipes (DismantleUtility) in an area; `--objects` for objects."""
    spec = {"tool": "dismantle", **_rect(x, y, width, height, zone)}
    kind = "DismantleObject" if objects else "DismantleUtility"
    _show(ctx, "POST", "/build", {"jobs": [{**spec, "kind": kind}]})


@ctl.command("wire")
def ctl_wire(
    ctx: typer.Context,
    x1: Annotated[
        int, typer.Argument(help="Start cell x (e.g. beside the power source).")
    ],
    y1: Annotated[int, typer.Argument(help="Start cell y.")],
    x2: Annotated[int, typer.Argument(help="End cell x: a cell touching the device.")],
    y2: Annotated[int, typer.Argument(help="End cell y.")],
    name: Annotated[
        str, typer.Option("--name", "-n", help="ElectricalCable.")
    ] = "ElectricalCable",
) -> None:
    """Lay cable from one cell to another: along x, then along y (both ends included)."""
    jobs = [
        {
            "tool": "line",
            "object": name,
            "x": min(x1, x2),
            "y": y1,
            "width": abs(x2 - x1) + 1,
            "height": 1,
        },
        {
            "tool": "line",
            "object": name,
            "x": x2,
            "y": min(y1, y2),
            "width": 1,
            "height": abs(y2 - y1) + 1,
        },
    ]
    _show(ctx, "POST", "/build", {"jobs": jobs})


@ctl.command("area")
def ctl_area(
    ctx: typer.Context,
    x: Annotated[int | None, typer.Argument(help="Left cell.")] = None,
    y: Annotated[int | None, typer.Argument(help="Top cell.")] = None,
    width: Annotated[int, typer.Argument(help="Cells wide.")] = 10,
    height: Annotated[int, typer.Argument(help="Cells high.")] = 10,
    zone: Annotated[
        str | None,
        typer.Option(
            "--zone", "-z", help="A named zone (`ctl zone`) instead of X Y W H."
        ),
    ] = None,
) -> None:
    """What the map cells in an area are made of (walls, floor, frame, nothing)."""
    if zone:
        _show(ctx, "GET", f"/area?zone={quote(zone)}")
        return
    if x is None or y is None:
        _fail("give X Y or --zone NAME")
    _show(ctx, "GET", f"/area?x={x}&y={y}&w={width}&h={height}")


@ctl.command("refresh")
def ctl_refresh(ctx: typer.Context) -> None:
    """Re-fetch the full save (rooms, occupants, problems), then print the state."""
    _show(ctx, "POST", "/refresh", {"seconds": 5})


@ctl.command("names")
def ctl_names(
    ctx: typer.Context,
    table: Annotated[
        str, typer.Argument(help="objects, materials, rooms, vehicles or intake.")
    ],
    query: Annotated[str, typer.Argument(help="Part of the name.")] = "",
) -> None:
    """The game's ids by name, e.g. `names objects bed`."""
    _show(ctx, "GET", f"/names/{quote(table)}?q={quote(query)}")


@ctl.command("events")
def ctl_events(
    ctx: typer.Context,
    since: Annotated[int, typer.Option(help="Only events after this seq.")] = 0,
    limit: Annotated[int, typer.Option(help="At most this many.")] = 100,
) -> None:
    """Numbered notable game events."""
    _show(ctx, "GET", f"/events?since={since}&limit={limit}")


@ctl.command("wait")
def ctl_wait(
    ctx: typer.Context,
    seconds: Annotated[float, typer.Argument(help="Seconds (max 30).")],
) -> None:
    """Let game time pass, then print the state."""
    _show(ctx, "POST", "/wait", {"seconds": seconds})


@ctl.command("quit")
def ctl_quit(ctx: typer.Context) -> None:
    """Disconnect the bot and stop the server."""
    _show(ctx, "POST", "/quit", {})
