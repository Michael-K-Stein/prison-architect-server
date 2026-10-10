"""A local JSON-over-HTTP control server for a live bot :class:`Session`.

Lets a non-interactive agent (a script, an AI using a shell) read the game state
and send RPCs. Listens on 127.0.0.1 only. Endpoints::

    GET  /state                      summary, room, players, connection
    GET  /state/<System>[/<path>]    one StateNode (?depth=N)
    GET  /actions                    the RPC catalog (?kind=player&all=0)
    POST /send   {"action", "args"}  parse, build and raise an RPC
    GET  /events                     numbered feed lines (?since=N&limit=M)
    POST /wait   {"seconds"}         sleep (max 30 s), then /state
    POST /quit                       disconnect and stop the server

Events: ``GameState.feed`` is a bounded deque without sequence numbers, so the
server swaps it for a same-sized deque subclass that also hands every appended
line to its own numbered log. Lines appended before the server started are
numbered on start-up.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib import error, request
from urllib.parse import parse_qs, urlsplit

from src.bot import catalog
from src.protocol import rpc

log = logging.getLogger(__name__)

DEFAULT_PORT = 8765
MAX_WAIT = 30.0
EVENT_LOG_SIZE = 2000


class _ObservedFeed(deque):
    """A deque that also reports every appended item to ``on_append``."""

    def __init__(self, items: Any, maxlen: int | None, on_append: Callable) -> None:
        super().__init__(items, maxlen)
        self.on_append = on_append

    def append(self, item: Any) -> None:
        """Append and report ``item``."""
        super().append(item)
        self.on_append(item)


class ControlServer:
    """An HTTP server on 127.0.0.1 that drives ``session``."""

    def __init__(self, session: Any, port: int = DEFAULT_PORT) -> None:
        """Bind to ``port`` (0: any free port); call :meth:`start` to serve."""
        self.session = session
        self.stopped = threading.Event()
        self.events: deque[dict[str, Any]] = deque(maxlen=EVENT_LOG_SIZE)
        self.total = 0
        self._events_lock = threading.Lock()
        self._install_feed()
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

    def _install_feed(self) -> None:
        state = self.session.state
        with state.lock:
            old = state.feed
            for line in old:
                self._log_event(line)
            state.feed = _ObservedFeed(old, old.maxlen, self._log_event)

    def _log_event(self, line: Any) -> None:
        with self._events_lock:
            self.total += 1
            self.events.append({"seq": self.total, "at": time.time(), "line": line})

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
                "args": [
                    {"name": x.name, "type": x.type, "hint": x.hint} for x in a.args
                ],
                "blocked": a.blocked,
            }
            for a in catalog.ACTIONS.values()
            if (kind is None or a.kind == kind) and (show_all or not a.blocked)
        ]

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
            values = catalog.parse_args(action, args, self.session.state.uid_of)
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

    def recent(self, since: int, limit: int) -> dict[str, Any]:
        """``/events``: logged lines with ``seq > since`` (at most ``limit``)."""
        with self._events_lock:
            items = [e for e in self.events if e["seq"] > since][:limit]
            return {"events": items, "last": self.total}


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
