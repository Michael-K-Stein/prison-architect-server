"""Route non-Prison-Architect Photon clients to the real Photon cloud.

The hosts-file trick (``ns.exitgames.com`` -> localhost) is global to the
machine, so without this module every Photon-engine game on the machine would
hit our local server and die in ``check_app_id``.  The first packet a Photon
TCP client sends is always an Init request whose app id is plaintext, so we
can peek at it (MSG_PEEK: read without consuming) and decide before any
handshake happens:

- Prison Architect's app id, or anything we fail to parse -> serve locally,
  exactly as before (fail closed).
- Any other app id -> transparent byte-for-byte TCP relay to the real Photon
  name server, so other games keep working untouched.

Only the NameServer uses this: after GetRegions the real upstream name server
hands the client real master-server addresses, so non-PA clients never touch
our local Master/GameServer ports.
"""

import json
import time
import urllib.request
from socket import MSG_PEEK, socket
from threading import Lock, Thread
from typing import Optional, Tuple

from server.consts import (
    NAMESERVER_IP,
    NAMESERVER_PORT,
    PRISON_ARCHITECT_APP_ID,
    normalize_app_id,
)
from server.log import print_info, print_success, print_warning
from server.photon.command_code import CommandCode
from server.photon.packet.format import PacketFormat

# How long to wait for a newly accepted client to send its first packet
# before giving up and serving it locally.
INIT_PEEK_TIMEOUT = 5.0

_UPSTREAM_HOSTNAME = "ns.exitgames.com"

_upstream_target: Optional[Tuple[str, int]] = None
_upstream_lock = Lock()


def _peek_exact(sock: socket, n: int, timeout: float) -> bytes:
    """Peek up to ``n`` bytes without consuming them; waits up to ``timeout``."""
    deadline = time.monotonic() + timeout
    data = b""
    while len(data) < n:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        sock.settimeout(remaining)
        try:
            chunk = sock.recv(n, MSG_PEEK)
        except OSError:
            break
        if not chunk:
            break  # connection closed before the packet arrived
        data = chunk  # MSG_PEEK re-reads from the start, so replace, don't append
    return data


def peek_init_app_id(sock: socket, timeout: float = INIT_PEEK_TIMEOUT) -> Optional[str]:
    """Return the app id from the client's first (Init) packet, or None.

    Peeks only; the socket's receive buffer is left untouched so whichever path
    we choose (local handling or upstream relay) sees the full byte stream.
    Returns None when the first packet isn't a parseable Init request.
    """
    old_timeout = sock.gettimeout()
    try:
        header = _peek_exact(sock, 9, timeout)
        if len(header) < 9:
            return None
        # byte 0: format, bytes 1-4: total packet length, byte 8: command
        if header[0] != PacketFormat.Data or header[8] != CommandCode.Init:
            return None
        total_len = int.from_bytes(header[1:5], byteorder="big")
        if total_len < 9 or total_len > 0x10000:
            return None
        packet = _peek_exact(sock, total_len, timeout)
        if len(packet) < total_len:
            return None
        # Init payload: 7-byte protocol struct, then the app id to end of packet
        app_id = packet[16:total_len].decode("utf-8", errors="replace").strip("\x00")
        return app_id or None
    except (OSError, ValueError):
        return None
    finally:
        try:
            sock.settimeout(old_timeout)
        except OSError:
            pass


def _resolve_via_doh() -> Optional[str]:
    """Resolve the current IP of the Photon name server via DNS-over-HTTPS."""
    urls = (
        f"https://dns.google/resolve?name={_UPSTREAM_HOSTNAME}&type=A",
        f"https://cloudflare-dns.com/dns-query?name={_UPSTREAM_HOSTNAME}&type=A",
    )
    for url in urls:
        try:
            req = urllib.request.Request(
                url, headers={"Accept": "application/dns-json"}
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                answer = json.loads(resp.read().decode("utf-8"))
            for record in answer.get("Answer", []):
                if record.get("type") == 1 and record.get("data"):
                    return record["data"]
        except Exception:
            continue  # best effort; the hardcoded fallback is next
    return None


def resolve_upstream(spec: Optional[str]) -> Tuple[str, int]:
    """Resolve the upstream Photon name server to (host, port).

    ``spec`` is "auto"/None (resolve the current IP via DoH, falling back to
    the hardcoded ``NAMESERVER_IP``) or "host"/"host:port" (used as-is,
    handy for tests).
    """
    if spec and spec != "auto":
        host, _, port = spec.partition(":")
        return host, int(port) if port else NAMESERVER_PORT
    ip = _resolve_via_doh()
    if ip is not None:
        return ip, NAMESERVER_PORT
    return NAMESERVER_IP, NAMESERVER_PORT


def get_upstream_target(spec: Optional[str]) -> Tuple[str, int]:
    """Resolve once and cache the upstream target for the process."""
    global _upstream_target
    if _upstream_target is None:
        with _upstream_lock:
            if _upstream_target is None:
                _upstream_target = resolve_upstream(spec)
    return _upstream_target


def relay_connection(
    client_sock: socket, addr, upstream: Tuple[str, int], server_type
) -> bool:
    """Bidirectionally relay client <-> real Photon cloud until either side closes.

    Returns True when the relay was started (the caller must then leave
    ``client_sock`` alone); False when the upstream was unreachable, in which
    case the caller should fall back to serving the client locally.
    """
    upstream_sock = socket()
    try:
        upstream_sock.connect(upstream)
    except OSError as e:
        print_warning(
            server_type,
            f"Upstream {upstream[0]}:{upstream[1]} unreachable ({e}); serving locally",
        )
        try:
            upstream_sock.close()
        except OSError:
            pass
        return False

    def _forward(src: socket, dst: socket) -> None:
        try:
            while True:
                data = src.recv(0x10000)
                if not data:
                    break
                dst.sendall(data)
        except OSError:
            pass
        finally:
            # One direction ending kills both directions; the sibling thread's
            # recv then fails/returns empty and exits too.
            for s in (client_sock, upstream_sock):
                try:
                    s.shutdown(2)  # SHUT_RDWR
                except OSError:
                    pass
                try:
                    s.close()
                except OSError:
                    pass

    for src, dst in ((client_sock, upstream_sock), (upstream_sock, client_sock)):
        Thread(
            target=_forward,
            args=(src, dst),
            daemon=True,
            name=f"Upstream Relay {addr[0]}:{addr[1]}",
        ).start()

    print_success(
        server_type,
        f"Routing non-PA client {addr[0]}:{addr[1]} "
        f"to upstream {upstream[0]}:{upstream[1]}",
    )
    return True


def route_or_local(
    sock: socket, addr, server_type, upstream_spec: Optional[str]
) -> bool:
    """Decide how to handle a newly accepted client.

    Returns True when the socket was taken over by an upstream relay (do not
    add it to the local client list); False to handle it locally as before.
    """
    app_id = peek_init_app_id(sock)
    if app_id is None:
        print_warning(
            server_type,
            f"Could not read app id for {addr[0]}:{addr[1]}; serving locally",
        )
        return False
    if normalize_app_id(app_id) == normalize_app_id(PRISON_ARCHITECT_APP_ID):
        print_info(
            server_type,
            f"Prison Architect client {addr[0]}:{addr[1]}; serving locally",
        )
        return False
    print_info(
        server_type,
        f"Non-PA app id {app_id!r} from {addr[0]}:{addr[1]}; proxying to Photon cloud",
    )
    return relay_connection(sock, addr, get_upstream_target(upstream_spec), server_type)
