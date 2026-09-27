"""Tests for Prison-Architect-only routing on the NameServer (port 4533).

A non-PA app id in the first (Init) packet must be transparently relayed
byte-for-byte to an upstream server instead of being served locally, so the
hosts-file redirect (ns.exitgames.com -> localhost) no longer breaks other
Photon-engine games. The upstream is pointed at a local mock -- the real
Photon cloud is never touched.

Tests:
  1. test_relay_is_verbatim_and_leaves_no_local_state
  2. test_relay_completes_init_handshake
  3. test_peek_unit (peek doesn't consume; garbage -> None; resolve parsing)

Run:  venv/bin/python test_proxy_routing.py
"""

import contextlib
import io
import socket
import sys
import threading
import time

sys.path.insert(0, ".")

from server.consts import PRISON_ARCHITECT_APP_ID
from server.local_servers.name_server import NameServer
from server.log import Verbosity
from server.photon.packet.init import InitRequestPacket, InitResponsePacket
from server.photon.packet.packet_stream import PhotonStreamParser
from server.photon.queue import upstream_router
from server.photon.queue.upstream_router import peek_init_app_id, resolve_upstream
from server.settings import Settings

NON_PA_APP_ID = "a" * 32
CANNED_REPLY = b"\xde\xad\xbe\xef" + b"\x00" * 100


class MockUpstream:
    """Tiny TCP server standing in for the real Photon name server."""

    def __init__(self, behavior):
        assert behavior in ("canned", "init_handshake")
        self.behavior = behavior
        self.received = b""
        self.done = threading.Event()
        self._srv = socket.socket()
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind(("127.0.0.1", 0))
        self._srv.listen(1)
        self.port = self._srv.getsockname()[1]

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def _read_exact(self, conn, n):
        data = b""
        while len(data) < n:
            chunk = conn.recv(n - len(data))
            if not chunk:
                raise OSError("upstream: client went away")
            data += chunk
        return data

    def _run(self):
        try:
            conn, _ = self._srv.accept()
            try:
                if self.behavior == "canned":
                    self.received = conn.recv(0x10000)
                    conn.sendall(CANNED_REPLY)
                else:  # init_handshake: read the full Init packet, answer it
                    header = self._read_exact(conn, 9)
                    total = int.from_bytes(header[1:5], byteorder="big")
                    self.received = header + self._read_exact(conn, total - 9)
                    conn.sendall(InitResponsePacket().serialize())
                while conn.recv(0x10000):  # wait for the client to go away
                    pass
            except OSError:
                pass
            finally:
                conn.close()
        except OSError:
            pass
        finally:
            self._srv.close()
            self.done.set()


def start_name_server(upstream):
    upstream_router._upstream_target = None  # don't reuse a cached target
    Settings().set(
        verbosity=Verbosity.Info,
        listen_host="127.0.0.1",
        ip="127.0.0.1",
        timeout=10,
        region_name="local",
        upstream=upstream,
    )
    ns = NameServer()
    ns.__enter__()
    return ns


def wait_for(predicate, timeout=5.0, what="condition"):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    raise AssertionError(f"timed out waiting for: {what}")


def relay_threads():
    return [t for t in threading.enumerate() if t.name.startswith("Upstream Relay")]


def test_relay_is_verbatim_and_leaves_no_local_state():
    print("TEST 1: non-PA client is relayed verbatim, no local state, clean teardown")
    mock = MockUpstream("canned")
    mock.start()
    log = io.StringIO()
    ns = start_name_server(f"127.0.0.1:{mock.port}")
    try:
        with contextlib.redirect_stdout(log):
            client = socket.create_connection(("127.0.0.1", 4533), timeout=5)
            client.settimeout(5)
            init_bytes = InitRequestPacket(app_id=NON_PA_APP_ID).serialize()
            client.sendall(init_bytes)

            # (a) the mock upstream received the client's Init bytes verbatim
            wait_for(lambda: mock.received != b"", what="mock to receive bytes")
            assert mock.received == init_bytes, (
                f"upstream got {mock.received!r}, expected {init_bytes!r}"
            )

            # (b) bytes the mock sends back arrive at the client verbatim
            reply = b""
            while len(reply) < len(CANNED_REPLY):
                chunk = client.recv(len(CANNED_REPLY) - len(reply))
                assert chunk, "client connection closed early"
                reply += chunk
            assert reply == CANNED_REPLY

            # (c) the local server never took ownership of this client
            assert ns._dispatcher.get_clients() == [], "client was added locally!"

            client.close()

            # (d) no relay threads or sockets linger after both sides disconnect
            assert wait_for(
                lambda: not relay_threads() and mock.done.is_set(),
                what="relay threads and mock handler to finish",
            )
    finally:
        ns.__exit__(None, None, None)

    assert "proxying to Photon cloud" in log.getvalue(), (
        "routing decision not logged; log was:\n" + log.getvalue()
    )
    print("  (a) mock upstream received client's Init bytes verbatim ... OK")
    print("  (b) mock's reply arrived at the client verbatim ... OK")
    print("  (c) no local client state created, routing logged ... OK")
    print("  (d) relay threads and sockets cleaned up ... OK")
    print("TEST 1 PASSED")


def test_relay_completes_init_handshake():
    print("TEST 2: relay works mid-protocol (Init -> InitResponse through proxy)")
    mock = MockUpstream("init_handshake")
    mock.start()
    ns = start_name_server(f"127.0.0.1:{mock.port}")
    try:
        client = socket.create_connection(("127.0.0.1", 4533), timeout=5)
        client.settimeout(5)
        init_bytes = InitRequestPacket(app_id=NON_PA_APP_ID).serialize()
        client.sendall(init_bytes)

        parser = PhotonStreamParser()
        packet = None
        deadline = time.monotonic() + 5
        while packet is None and time.monotonic() < deadline:
            chunk = client.recv(0x1000)
            assert chunk, "connection closed before InitResponse"
            parser.feed(chunk)
            for packet in parser.parse(expect_responses=True):
                break
        assert packet is not None, "no packet received"
        assert packet.get_header().get_command_name() == "InitResponse", (
            f"expected InitResponse, got {packet.get_header().get_command_name()}"
        )
        wait_for(lambda: mock.received != b"", what="mock to receive bytes")
        assert mock.received == init_bytes, "upstream did not get verbatim Init"
        assert ns._dispatcher.get_clients() == [], "client was added locally!"
        print("  Init -> InitResponse relayed through the proxy ... OK")

        client.close()
        assert wait_for(
            lambda: not relay_threads() and mock.done.is_set(),
            what="relay threads and mock handler to finish",
        )
        print("  teardown clean ... OK")
    finally:
        ns.__exit__(None, None, None)
    print("TEST 2 PASSED")


def test_peek_unit():
    print("TEST 3: peek_init_app_id unit behavior")
    # valid Init -> app id, and the bytes are NOT consumed
    a, b = socket.socketpair()
    try:
        init_bytes = InitRequestPacket(app_id=NON_PA_APP_ID).serialize()
        a.sendall(init_bytes)
        assert peek_init_app_id(b, timeout=2.0) == NON_PA_APP_ID
        assert b.recv(len(init_bytes)) == init_bytes, "peek consumed bytes!"
        print("  valid Init peeked without consuming ... OK")
    finally:
        a.close()
        b.close()

    # garbage -> None (fail closed to local handling)
    a, b = socket.socketpair()
    try:
        a.sendall(b"not-a-photon-packet")
        a.close()
        assert peek_init_app_id(b, timeout=2.0) is None
        print("  garbage -> None (fail closed) ... OK")
    finally:
        b.close()

    # upstream spec parsing
    assert resolve_upstream("127.0.0.1:9999") == ("127.0.0.1", 9999)
    assert resolve_upstream("example.com") == ("example.com", 4533)
    print("  resolve_upstream('host[:port]') parsing ... OK")
    print("TEST 3 PASSED")


if __name__ == "__main__":
    print(f"(sanity: PA app id is {PRISON_ARCHITECT_APP_ID})")
    test_peek_unit()
    test_relay_is_verbatim_and_leaves_no_local_state()
    test_relay_completes_init_handshake()
    print("ALL PROXY TESTS PASSED")
