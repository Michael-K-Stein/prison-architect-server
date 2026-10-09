"""Regression tests for proxy-mode session teardown.

Covers:
  1. When the upstream server drops the connection, the tunnel disconnects
     the matching client and forgets the session, instead of leaving the
     client attached to a dead upstream.
  2. When the upstream can't be reached at all, the client is disconnected
     and the tunnel keeps running.
"""

import socket
import sys
import threading
import time

sys.path.insert(0, ".")

from server.consts import PRISON_ARCHITECT_APP_ID
from server.log import Verbosity
from server.proxy_servers.proxy_tunnel import ProxyTunnel
from server.settings import Settings


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def wait_for(predicate, timeout_s, step=lambda: None):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        step()
        if predicate():
            return True
        time.sleep(0.1)
    return False


def connected_client(tunnel, local_port):
    client = socket.create_connection(("127.0.0.1", local_port), timeout=5)
    dispatcher = tunnel.downstream._dispatcher
    assert wait_for(lambda: dispatcher.get_clients(), 5), "client never registered"
    return client, dispatcher.get_clients()[0]


def make_tunnel(remote_port):
    Settings().set(
        verbosity=Verbosity.Critical,
        listen_host="127.0.0.1",
        ip="127.0.0.1",
        timeout=60,
        region_name="local",
    )
    local_port = free_port()
    tunnel = ProxyTunnel(
        local_port=local_port,
        remote_ip="127.0.0.1",
        remote_port=remote_port,
        app_id=PRISON_ARCHITECT_APP_ID,
    ).__enter__()
    return tunnel, local_port


def test_upstream_drop_disconnects_client():
    upstream_listener = socket.socket()
    upstream_listener.bind(("127.0.0.1", 0))
    upstream_listener.listen(1)
    remote_port = upstream_listener.getsockname()[1]

    def accept_then_drop():
        conn, _ = upstream_listener.accept()
        time.sleep(0.5)
        conn.close()

    threading.Thread(target=accept_then_drop, daemon=True).start()

    tunnel, local_port = make_tunnel(remote_port)
    client = None
    try:
        client, client_socket = connected_client(tunnel, local_port)
        upstream = tunnel._get_upstream_for_client(client_socket)
        assert upstream is not None, "upstream connect failed"

        assert wait_for(
            lambda: not tunnel._upstreams_entered, 10, step=tunnel.process
        ), "session was not reaped after the upstream dropped"
        assert client_socket.is_disconnected(), "client was left connected"
        assert upstream.is_closed()
        print("OK: upstream drop disconnected the client and reaped the session")
    finally:
        if client is not None:
            client.close()
        tunnel.__exit__(None, None, None)
        upstream_listener.close()


def test_unreachable_upstream_disconnects_client():
    tunnel, local_port = make_tunnel(free_port())  # nothing listening there
    client = None
    try:
        client, client_socket = connected_client(tunnel, local_port)
        assert tunnel._get_upstream_for_client(client_socket) is None
        assert client_socket.is_disconnected(), "client was left connected"
        assert not tunnel._upstreams_entered
        tunnel.process()  # tunnel must keep working afterwards
        print("OK: unreachable upstream disconnected the client, tunnel survived")
    finally:
        if client is not None:
            client.close()
        tunnel.__exit__(None, None, None)


if __name__ == "__main__":
    test_upstream_drop_disconnects_client()
    test_unreachable_upstream_disconnects_client()
    print("All proxy tunnel tests passed.")
