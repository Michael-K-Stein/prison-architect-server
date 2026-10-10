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
    GET  /area?x=&y=&w=&h=           what the map cells there are made of (a grid)
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

from src.bot import build, catalog
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
}
"""``/names/<table>``: the game's id -> name tables."""
AREA_DEFAULTS = (("x", 0), ("y", 0), ("w", 10), ("h", 10))


class ControlServer:
    """An HTTP server on 127.0.0.1 that drives ``session``."""

    def __init__(self, session: Any, port: int = DEFAULT_PORT) -> None:
        """Bind to ``port`` (0: any free port); call :meth:`start` to serve."""
        self.session = session
        self.stopped = threading.Event()

        handler = type("Handler", (_Handler,), {"control": self})
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
        """Block until /quit or a disconnect; returns which (Ctrl-C propagates)."""
        while not self.stopped.wait(poll):
            if self.session.disconnected is not None:
                return "disconnected"
        return "quit"

    # endpoint bodies: (status, json)
    def state(self) -> dict[str, Any]:
        """``/state``: summary plus room, players and connection."""
        session = self.session
        out = session.state.summary()
        room = getattr(session.client, "current_room", None)
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

    def node(self, path: str, depth: int) -> tuple[int, dict[str, Any]]:
        """``/state/<System>/<path>``: one node's ``to_dict(depth)``."""
        system, _, rest = path.strip("/").partition("/")
        state = self.session.state
        with state.lock:
            root = state.systems.get(system)
            node = root.find(rest) if root else None
            if node is None:
                return 404, {"error": f"no state node {path.strip('/')!r}"}
            return 200, node.to_dict(depth)

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
        }

    def send(self, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        """``/send``: parse, build and raise one RPC."""
        key = body.get("action")
        args = body.get("args") or []
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
        sent = self.session.raise_event(action.code, data)
        log.info("control /send %s %r -> sent=%s", action.name, args, sent)
        return 200, {
            "sent": bool(sent),
            "code": action.code,
            "name": action.name,
            "data_hex": data.hex(),
        }

    def build(self, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        """``/build``: ``{"jobs": [spec, ...]}`` (see :func:`build.job_from`)."""
        specs = body.get("jobs")
        if not isinstance(specs, list) or not specs:
            return 400, {"error": "jobs must be a non-empty list of job specs"}
        try:
            jobs = [build.job_from(s) for s in specs]
        except build.BuildError as exc:
            return 400, {"error": str(exc)}
        sent = self.session.build(jobs)
        log.info("control /build %r -> sent=%s", specs, sent)
        return 200, {"sent": bool(sent), "jobs": [vars(j) for j in jobs]}

    def names(self, table: str, query: str) -> tuple[int, dict[str, Any]]:
        """``/names/<table>``: id -> name for objects/materials/rooms/..."""
        found = NAME_TABLES.get(table)
        if found is None:
            return 404, {"error": f"unknown table; one of {', '.join(NAME_TABLES)}"}
        q = query.lower()
        return 200, {str(i): n for i, n in found.items() if q in n.lower()}

    def recent(self, since: int, limit: int) -> dict[str, Any]:
        """``/events``: logged lines with ``seq > since`` (at most ``limit``)."""
        state = self.session.state
        items = state.since(since, limit)
        return {
            "events": [{"seq": s, "at": at, "line": line} for s, at, line in items],
            "last": state.seq,
        }


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
                self._reply(*c.node(url.path[7:], int(query.get("depth", -1))))
            elif url.path == "/actions":
                show_all = query.get("all", "0").lower() in ("1", "true", "yes")
                self._reply(200, c.actions(query.get("kind") or None, show_all))
            elif url.path.startswith("/actions/"):
                self._reply(*c.action(unquote(url.path[9:])))
            elif url.path == "/area":
                x, y, w, h = (int(query.get(k, d)) for k, d in AREA_DEFAULTS)
                self._reply(200, c.session.state.area(x, y, min(w, 60), min(h, 60)))
            elif url.path.startswith("/names/"):
                self._reply(*c.names(url.path[7:], query.get("q", "")))
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
            if path == "/send":
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
) -> tuple[int, Any]:
    """Client helper: ``(status, json)`` for one request to a control server."""
    data = json.dumps(body).encode() if body is not None else None
    req = request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
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
