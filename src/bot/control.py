"""A local JSON-over-HTTP control server for a live bot :class:`Session`.

Lets a non-interactive agent (a script, an AI using a shell) read the game state
and send RPCs. Listens on 127.0.0.1 only. Endpoints::

    GET  /state                      summary, room, players, connection
    GET  /state/<System>[/<path>]    one StateNode (?depth=N)
    GET  /actions                    the RPC catalog (?kind=player&all=0)
    GET  /actions/<name-or-code>     one action, each arg's choices from live state
    POST /send   {"action", "args"}  parse, build and raise an RPC
    POST /build  {"jobs": [spec]}    build jobs (foundation/wall/floor/room/place)
    GET  /names/<table>?q=text       game ids by name (objects, materials, rooms...)
    GET  /hints?object=NAME          the full game hint for one object (any time)
    GET  /area?x=&y=&w=&h=           what the map cells there are made of (a grid);
                                     ?zone=NAME instead of the rectangle
    GET/POST /zone                   named map rectangles (list; set / remove)
    POST /refresh {"seconds"}        re-fetch the full save (rooms, problems), then /state
    GET  /events                     numbered feed lines (?since=N&limit=M)
    POST /wait   {"seconds"}         sleep (max 30 s), then /state
    POST /quit                       disconnect and stop the server

Events are `GameState.log`'s numbered lines (the last 2000).

"""

from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib import error, request
from urllib.parse import parse_qs, unquote, urlsplit

from src.bot import build, catalog, hints, objecthints, wiredata
from src.bot.names import NameError_
from src.bot.zones import Zones, bounds, mask_rows
from src.protocol.grants import GRANTS
from src.protocol import enums, rpc

log = logging.getLogger(__name__)

DEFAULT_PORT = 8765
MAX_WAIT = 30.0
NAME_TABLES = {
    "objects": enums.OBJECTS,
    "materials": enums.MATERIALS,
    "rooms": enums.ROOMS,
    "vehicles": enums.VEHICLES,
    "intake": enums.INTAKE_TYPES,
    "grants": {
        i: f"{n}: {info['title'] or ''} start {info['start']} done {info['completion']}"
        for i, (n, info) in enumerate(GRANTS.items())
    },
}
"""``/names/<table>``: the game's id -> name tables."""
STAFF_STATUS_EVERY = 3
"""Staff-related commands attach ``staff_status`` to every 3rd reply."""
AREA_DEFAULTS = (("x", 0), ("y", 0), ("w", 10), ("h", 10))


MAX_AREA = 200
"""Our own limit on one ``area`` reply (a whole map is 100x80), not a game rule."""


class ControlServer:
    """An HTTP server on 127.0.0.1 that drives ``session``."""

    def __init__(self, session: Any, port: int = DEFAULT_PORT) -> None:
        """Bind to ``port`` (0: any free port); call :meth:`start` to serve."""
        self.session = session
        self.stopped = threading.Event()
        self.auto_reconnect = False
        """True when a :class:`~src.bot.reconnect.Reconnector` replaces dead sessions."""

        handler = type("Handler", (_Handler,), {"control": self})
        self._staff_calls = 0
        self.object_hints = objecthints.ObjectHintTracker()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
        self.httpd.daemon_threads = True
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def port(self) -> int:
        """The bound port."""
        return self.httpd.server_address[1]

    @property
    def url(self) -> str:
        """``http://127.0.0.1:PORT``."""
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> None:
        """Serve in a background thread."""
        self._thread.start()
        log.info("control server listening on %s", self.url)

    def stop(self) -> None:
        """Stop serving (safe to call twice, from any thread)."""
        if self.stopped.is_set():
            return
        self.stopped.set()
        threading.Thread(target=self._shutdown, daemon=True).start()

    def _shutdown(self) -> None:
        if self._thread.is_alive():
            self.httpd.shutdown()
        self.httpd.server_close()

    def wait(self, poll: float = 0.25) -> str:
        """Block until /quit or a disconnect; returns which (Ctrl-C propagates).

        With ``auto_reconnect`` a disconnect is not the end: only /quit or giving up is.
        """
        while not self.stopped.wait(poll):
            if self.session.disconnected is not None and not self.auto_reconnect:
                return "disconnected"
        return "quit"

    # endpoint bodies: (status, json)
    def state(self) -> dict[str, Any]:
        """``/state``: summary plus room, players and connection."""
        session = self.session
        room = getattr(session.client, "current_room", None)
        session.state.names.bind(getattr(room, "name", ""))
        out = session.state.summary()
        players = []
        with session.lock:
            for nr, player in sorted((getattr(room, "players", None) or {}).items()):
                players.append({"actor": nr, "name": getattr(player, "nick_name", "")})
        out["room"] = getattr(room, "name", None)
        out["players"] = players
        out["connected"] = session.disconnected is None
        out["disconnected"] = (
            None if session.disconnected is None else str(session.disconnected)
        )
        return out

    def _add_names(self, system: str, rest: str, tree: dict[str, Any]) -> None:
        """Put the bot's own ``Name`` on ObjectData objects it has named."""
        if system != "ObjectData":
            return
        names = self.session.state.names
        if rest:  # one object: ObjectData/52
            name = names.name_of(int(rest)) if rest.isdigit() else None
            if name:
                tree["Name"] = name
            return
        for key, child in tree.items():
            if key.startswith("/") and key[1:].isdigit() and isinstance(child, dict):
                if name := names.name_of(int(key[1:])):
                    child["Name"] = name

    def _named_details(self) -> dict[str, Any]:
        state = self.session.state
        out = {}
        for name, (uid, index) in state.names.all().items():
            node = state.systems.get("ObjectData")
            obj = node.children.get(str(index)) if node else None
            out[name] = {
                "uId": uid,
                "index": index,
                "type": obj.fields.get("name") if obj else None,
                "current": bool(obj and obj.fields.get("uId") == uid),
            }
        return out

    def alias(self, body: dict[str, Any] | None) -> tuple[int, dict[str, Any]]:
        """``/alias``: list names, or ``{"set": name, "ref": "52"|"uId,index",
        "room": bool}`` / ``{"remove": name}``."""
        state = self.session.state
        room = getattr(getattr(self.session.client, "current_room", None), "name", "")
        state.names.bind(room)
        if body:
            if name := body.get("remove"):
                return 200, {"removed": state.names.remove(str(name))}
            name, ref = body.get("set"), str(body.get("ref", "")).strip()
            if not name or not ref:
                return 400, {"error": 'need {"set": name, "ref": index or uId,index}'}
            try:
                if "," in ref:
                    uid, index = (int(x) for x in ref.split(",", 1))
                else:
                    index = int(ref.lstrip("#"))
                    uid = (
                        state.room_uid(index)
                        if body.get("room")
                        else state.uid_of(index)
                    )
                if uid is None:
                    return 404, {"error": f"#{index} is not in the game state"}
                state.names.set(str(name), uid, index)
            except ValueError as exc:
                return 400, {"error": str(exc)}
        return 200, {"names": self._named_details()}

    def node(
        self, path: str, depth: int, raw: bool = False
    ) -> tuple[int, dict[str, Any]]:
        """``/state/<System>/<path>``: one node's ``to_dict(depth)``."""
        system, _, rest = path.strip("/").partition("/")
        state = self.session.state
        with state.lock:
            root = state.systems.get(system)
            node = root.find(rest) if root else None
            if node is None:
                return 404, {"error": f"no state node {path.strip('/')!r}"}
            tree = node.to_dict(depth, None if raw else system)
            self._add_names(system, rest, tree)
            return 200, tree

    def actions(self, kind: str | None, show_all: bool) -> list[dict[str, Any]]:
        """``/actions``: the catalog, buildable ones only unless ``show_all``."""
        return [
            {
                "code": a.code,
                "name": a.name,
                "kind": a.kind,
                "args": [_arg(x) for x in a.args],
                "blocked": a.blocked,
            }
            for a in catalog.ACTIONS.values()
            if (kind is None or a.kind == kind) and (show_all or not a.blocked)
        ]

    def action(self, key: str) -> tuple[int, dict[str, Any]]:
        """``/actions/<name-or-code>``: one action, args with their live choices."""
        try:
            a = catalog.find(key)
        except KeyError:
            return 404, {"error": f"unknown action {key!r}"}
        state = self.session.state
        with state.lock:
            args = [
                {
                    **_arg(x),
                    "choices": [
                        {"value": _plain(c.value), "label": c.label}
                        for c in catalog.choices(x, state)
                    ],
                }
                for x in a.args
            ]
        return 200, {
            "code": a.code,
            "name": a.name,
            "kind": a.kind,
            "signature": a.signature,
            "args": args,
            "blocked": a.blocked,
            "hints": hints.for_action(a.name),
        }

    def send(self, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        """``/send``: parse, build and raise one RPC."""
        key = body.get("action")
        args = body.get("args") or []
        room = getattr(self.session.client, "current_room", None)
        self.session.state.names.bind(getattr(room, "name", ""))
        if not isinstance(args, list):
            return 400, {"error": "args must be a list"}
        try:
            action = catalog.find(key)
        except (KeyError, TypeError):
            return 400, {"error": f"unknown action {key!r}"}
        try:
            values = catalog.parse_args(action, args, self.session.state)
            data = rpc.build(action.code, *values)
        except (catalog.ArgError, rpc.RpcShapeError) as exc:
            return 400, {"error": str(exc)}
        sent = self.session.raise_event(
            action.code, data, broadcast=bool(body.get("broadcast"))
        )
        log.info("control /send %s %r -> sent=%s", action.name, args, sent)
        return 200, {
            "sent": bool(sent),
            "code": action.code,
            "name": action.name,
            "data_hex": data.hex(),
            "hints": hints.for_action(action.name),
            **self._with_staff(action.name in hints.STAFF_ACTIONS),
        }

    def _zones(self) -> Zones:
        """The session's zones, bound to the joined game."""
        zones = self.session.state.zones
        zones.bind(
            getattr(getattr(self.session.client, "current_room", None), "name", "")
        )
        return zones

    def zone(self, body: dict[str, Any] | None) -> tuple[int, dict[str, Any]]:
        """``/zone``: list zones, or ``{"set": name, "x", "y", "w", "h"}`` /
        ``{"remove": name}``."""
        zones = self._zones()
        try:
            if body and (name := body.get("remove")):
                return 200, {"removed": zones.remove(str(name))}
            if body and (name := body.get("set")):
                x, y, w, h = (int(body[k]) for k in ("x", "y", "w", "h"))
                zones.set(str(name), x, y, w, h)
        except (KeyError, ValueError) as exc:
            return 400, {"error": f"need set, x, y, w, h: {exc}"}
        return 200, {"zones": zones.all(), "groups": zones.groups()}

    def wires(self, ask: bool) -> dict[str, Any]:
        """Object wiring (``wirec`` / ``wirei``); ``ask`` sends WireDataRequested first."""
        state = self.session.state
        found = (
            wiredata.request(self.session, state) if ask else wiredata.wire_data(state)
        )
        return {
            str(i): {
                "connections": [
                    {
                        "index": link.index,
                        "uid": link.uid,
                        "triggered": link.triggered,
                        "time_index": link.time_index,
                        "via": list(link.via),
                    }
                    for link in w.connections
                ],
                "inputs": [list(pair) for pair in w.inputs],
            }
            for i, w in sorted(found.items())
        }

    def area(self, query: dict[str, str]) -> dict[str, Any]:
        """``/area``: the grid of a rectangle or a ``zone``, plus the zones it touches."""
        zones = self._zones()
        if "zone" in query:
            rects = zones.rects(query["zone"])
            if not rects:
                raise NameError_(f"no zone named {query['zone']!r} (`ctl zone list`)")
            x, y, w, h = bounds(rects)
        else:
            rects = []
            x, y, w, h = (int(query.get(k, d)) for k, d in AREA_DEFAULTS)
        reply = self.session.state.area(x, y, min(w, MAX_AREA), min(h, MAX_AREA))
        if len(rects) > 1:  # a group: only its own cells, not its bounding box
            reply["rows"] = mask_rows(reply["rows"], x, y, rects)
            reply.pop("materials")
            reply["bounding_box"] = {"x": x, "y": y, "w": w, "h": h}
        reply["zones"] = zones.overlapping(x, y, w, h)
        return {**reply, "hints": list(hints.COMMAND_HINTS["area"])}

    def build(self, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        """``/build``: ``{"jobs": [spec, ...]}`` (see :func:`build.job_from`).

        A spec may give ``"zone": NAME`` instead of ``x, y, width, height``."""
        specs = body.get("jobs")
        if not isinstance(specs, list) or not specs:
            return 400, {"error": "jobs must be a non-empty list of job specs"}
        try:
            zones = self._zones()
            specs = [one for s in specs for one in zones.resolve(s)]
            jobs = [build.job_from(s) for s in specs]
        except (build.BuildError, NameError_) as exc:
            return 400, {"error": str(exc)}
        sent = self.session.build(jobs)
        log.info("control /build %r -> sent=%s", specs, sent)
        reply: dict[str, Any] = {
            "sent": bool(sent),
            "jobs": [vars(j) for j in jobs],
            "hints": hints.for_jobs(specs),
            **self._with_staff(hints.is_staff_job(specs)),
        }
        if due := self.object_hints.take(_object_names(specs)):
            reply["object_hints"] = due
        return 200, reply

    def object_hint(self, name: str) -> tuple[int, dict[str, Any]]:
        """``/hints?object=NAME``: the full game hint for one object, any time."""
        entry = objecthints.lookup(name)
        if entry is None:
            return 404, {"error": f"no object hint for {name!r}"}
        return 200, entry

    def names(self, table: str, query: str) -> tuple[int, dict[str, Any]]:
        """``/names/<table>``: id -> name for objects/materials/rooms/..."""
        found = NAME_TABLES.get(table)
        if found is None:
            return 404, {"error": f"unknown table; one of {', '.join(NAME_TABLES)}"}
        q = query.lower()
        return 200, {str(i): n for i, n in found.items() if q in n.lower()}

    def _with_staff(self, relevant: bool) -> dict[str, Any]:
        status = self.staff_status() if relevant else None
        return {"staff_status": status} if status else {}

    def staff_status(self, every: int = STAFF_STATUS_EVERY) -> dict[str, Any] | None:
        """A compact staff-needs summary on every ``every``-th staff-related reply."""
        self._staff_calls += 1
        if self._staff_calls % every:
            return None
        needs = self.session.state.staff_needs()
        return {"exhausted": needs["exhausted"], "by_type": needs["summary"]}

    def recent(self, since: int, limit: int) -> dict[str, Any]:
        """``/events``: logged lines with ``seq > since`` (at most ``limit``)."""
        state = self.session.state
        items = state.since(since, limit)
        return {
            "events": [{"seq": s, "at": at, "line": line} for s, at, line in items],
            "last": state.seq,
        }


def _object_names(specs: list[dict]) -> list[str]:
    """Object names a build job refers to (same fields as :func:`hints.for_jobs`)."""
    return [
        str(spec[key])
        for spec in specs
        for key in ("object", "role", "kind")
        if spec.get(key)
    ]


def _arg(arg: catalog.Arg) -> dict[str, Any]:
    return {
        "name": arg.name,
        "type": arg.type,
        "hint": arg.hint,
        "source": catalog.source(arg),
    }


def _plain(value: Any) -> Any:
    """``value`` as JSON: tuples as lists, bytes as hex."""
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, bytes):
        return value.hex()
    return value


class _Handler(BaseHTTPRequestHandler):
    control: ControlServer

    def log_message(self, format: str, *args: Any) -> None:
        log.debug("control: " + format, *args)

    def _reply(self, status: int, body: Any) -> None:
        if isinstance(body, dict) and self.headers.get("X-Interrupts") != "0":
            # staff alerts are interrupts: each unseen one rides on the next reply
            new = self.control.session.state.take_new_alerts()
            if new:
                body = {**body, "alerts_new": [a.as_dict() for a in new]}
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _body(self) -> dict[str, Any]:
        size = int(self.headers.get("Content-Length") or 0)
        if not size:
            return {}
        body = json.loads(self.rfile.read(size))
        if not isinstance(body, dict):
            raise ValueError("body must be a JSON object")
        return body

    def do_GET(self) -> None:
        url = urlsplit(self.path)
        query = {k: v[-1] for k, v in parse_qs(url.query).items()}
        c = self.control
        try:
            if url.path == "/state":
                self._reply(200, c.state())
            elif url.path.startswith("/state/"):
                self._reply(
                    *c.node(url.path[7:], int(query.get("depth", -1)), "raw" in query)
                )
            elif url.path == "/actions":
                show_all = query.get("all", "0").lower() in ("1", "true", "yes")
                self._reply(200, c.actions(query.get("kind") or None, show_all))
            elif url.path.startswith("/actions/"):
                self._reply(*c.action(unquote(url.path[9:])))
            elif url.path == "/area":
                self._reply(200, c.area(query))
            elif url.path == "/zone":
                self._reply(*c.zone(None))
            elif url.path == "/network":
                self._reply(
                    200, c.session.state.networks(query.get("utility", "electricity"))
                )
            elif url.path.startswith("/names/"):
                self._reply(*c.names(url.path[7:], query.get("q", "")))
            elif url.path == "/alias":
                self._reply(*c.alias(None))
            elif url.path == "/staff":
                self._reply(200, c.session.state.staff_needs())
            elif url.path == "/connect":
                self._reply(200, c.session.state.connect_plan(query.get("kind", "")))
            elif url.path == "/quality":
                self._reply(
                    200, {"rooms": c.session.state.room_quality(query.get("room", ""))}
                )
            elif url.path == "/todo":
                state = c.session.state
                if query.get("going_green"):
                    self._reply(200, {"going_green": state.going_green()})
                else:
                    self._reply(200, {"todo": state.todo()})
            elif url.path == "/alerts":
                state = c.session.state
                since = int(query.get("since", 0))
                found = (
                    state.take_new_alerts()
                    if query.get("new")
                    else state.alerts_since(since)
                )
                self._reply(
                    200,
                    {
                        "alerts": [a.as_dict() for a in found],
                        "last": state.alert_log[-1].seq if state.alert_log else 0,
                    },
                )
            elif url.path == "/wires":
                self._reply(200, c.wires("request" in query))
            elif url.path == "/hints" and "object" in query:
                self._reply(*c.object_hint(query["object"]))
            elif url.path == "/hints":
                topic = query.get("topic", "")
                found = hints.TOPICS.get(topic) if topic else None
                if topic and found is None:
                    self._reply(404, {"error": f"topics: {', '.join(hints.TOPICS)}"})
                else:
                    self._reply(
                        200,
                        {
                            k: list(v)
                            for k, v in hints.TOPICS.items()
                            if not topic or k == topic
                        },
                    )
            elif url.path == "/events":
                since = int(query.get("since", 0))
                self._reply(200, c.recent(since, int(query.get("limit", 100))))
            else:
                self._reply(404, {"error": f"unknown endpoint {url.path}"})
        except ValueError as exc:
            self._reply(400, {"error": str(exc)})

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        c = self.control
        try:
            body = self._body()
            if path == "/alias":
                self._reply(*c.alias(body))
            elif path == "/zone":
                self._reply(*c.zone(body))
            elif path == "/send":
                self._reply(*c.send(body))
            elif path == "/build":
                self._reply(*c.build(body))
            elif path == "/refresh":
                c.session.request_save(c.session.password)
                c.stopped.wait(min(float(body.get("seconds", 5)), MAX_WAIT))
                self._reply(200, c.state())
            elif path == "/wait":
                seconds = min(max(float(body.get("seconds", 1)), 0.0), MAX_WAIT)
                c.stopped.wait(seconds)
                self._reply(200, c.state())
            elif path == "/quit":
                c.stop()  # shuts down from another thread, after this reply
                self._reply(200, {"quit": True})
            else:
                self._reply(404, {"error": f"unknown endpoint {path}"})
        except ValueError as exc:
            self._reply(400, {"error": str(exc)})


def call(
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    port: int = DEFAULT_PORT,
    timeout: float = MAX_WAIT + 10,
    interrupts: bool = True,
) -> tuple[int, Any]:
    """Client helper: ``(status, json)`` for one request to a control server.

    ``interrupts=False`` keeps the reply from consuming the unseen staff alerts (for
    polling inside a longer command, which shows them itself at the end).
    """
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if not interrupts:
        headers["X-Interrupts"] = "0"
    req = request.Request(
        f"http://127.0.0.1:{port}{path}", data=data, method=method, headers=headers
    )
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read() or b"null")
    except error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw)
        except ValueError:
            return exc.code, {"error": raw.decode("utf-8", "replace")}
