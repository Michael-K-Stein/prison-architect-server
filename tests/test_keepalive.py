"""Regression tests for the idle-timeout disconnect fixes (2026-09-27).

Reproduces the LAN session failure where the host's GameServer connection went
quiet for >10s (sitting in the created-game lobby while the second player
joined) and the server reaped it mid-session, because the default --timeout
was 10s. The send worker then died with WinError 10038 (only
ConnectionAbortedError was caught), killing that client's outbound traffic.

Covers:
  1. The server pings a quiet client with a keep-alive request instead of
     staying silent until the idle timeout fires.
  2. A client that answers keep-alives is NOT disconnected, even past the old
     10s death window.
  3. A send racing a closed socket shuts the queue down quietly -- no uncaught
     thread exception, no traceback.
"""

import socket
import sys
from pathlib import Path
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.consts import ServerType
from server.log import Verbosity
from server.photon.packet.keep_alive import (
    PhotonKeepAliveRequest,
    PhotonKeepAliveResponse,
)
from server.photon.packet.packet_stream import PhotonStreamParser
from server.photon.queue.photon_queue import PhotonQueue
from server.settings import Settings


def make_queue(soft_timeout, hard_timeout):
    Settings().set(
        verbosity=Verbosity.Critical,
        listen_host="127.0.0.1",
        ip="127.0.0.1",
        timeout=60,
        region_name="local",
        upstream=None,
    )
    server_sock, client_sock = socket.socketpair()
    queue = PhotonQueue(server_sock, "test-client", ServerType.GameServer)
    # Shrink the per-server-type thresholds so the test runs in seconds.
    queue._keep_alive_soft_timeout = soft_timeout
    queue._keep_alive_hard_timeout = hard_timeout
    queue.__enter__()

    # Stand-in for PhotonQueueDispatcher's global keep-alive worker.
    def keep_alive_loop():
        while not queue._closing:
            time.sleep(1)
            queue.check_keep_alive()

    queue._test_keep_alive_worker = threading.Thread(
        target=keep_alive_loop, name="Test KeepAlive Worker"
    )
    queue._test_keep_alive_worker.start()
    return queue, client_sock


def read_keepalive_request(sock, parser, timeout_s):
    """Block up to timeout_s for a server keep-alive request; None on timeout."""
    deadline = time.time() + timeout_s
    sock.settimeout(timeout_s)
    while time.time() < deadline:
        try:
            data = sock.recv(0x1000)
        except socket.timeout:
            return None
        if not data:
            return None
        parser.feed(data)
        for packet in parser.parse(expect_responses=False):
            if isinstance(packet, PhotonKeepAliveRequest):
                return packet
    return None


def assert_workers_dead(queue):
    for worker in (
        queue._send_worker,
        queue._recv_worker,
        queue._test_keep_alive_worker,
    ):
        worker.join(10)
        assert not worker.is_alive(), f"worker {worker.name} did not stop"


def test_quiet_client_is_pinged_and_survives():
    # Soft timeout 4s -> server pings after 4s idle. Answer every ping for
    # 14s, well past the 8s hard timeout: the client must stay connected.
    queue, client = make_queue(soft_timeout=4, hard_timeout=8)
    parser = PhotonStreamParser()
    try:
        end = time.time() + 14
        pings_answered = 0
        while time.time() < end:
            pkt = read_keepalive_request(client, parser, timeout_s=2)
            if pkt is not None:
                pings_answered += 1
                client.sendall(
                    PhotonKeepAliveResponse(0, pkt.get_client_time()).serialize()
                )
            assert not queue._closing, (
                "server reaped a live client that answers keep-alives"
            )
        assert pings_answered >= 1, "server never pinged the quiet client"
        assert not queue._closing
        print(f"OK: pinged {pings_answered}x, client survived 14s idle")
    finally:
        client.close()
        queue.__exit__(None, None, None)
        assert_workers_dead(queue)


def test_send_on_dead_socket_shuts_down_quietly():
    thread_errors = []
    old_hook = threading.excepthook
    threading.excepthook = lambda args: thread_errors.append(args)
    queue, client = make_queue(soft_timeout=60, hard_timeout=120)
    try:
        # Abruptly destroy the server side of the socket, then queue a send:
        # this is the WinError 10038 race from the LAN session.
        queue._sock.close()
        queue.push(PhotonKeepAliveRequest(0))
        queue._send_worker.join(10)
        assert not queue._send_worker.is_alive(), "send worker did not exit"
        assert queue._closing, "queue did not shut down after send failure"
        assert not thread_errors, (
            f"uncaught thread exceptions: {[e.exc_type for e in thread_errors]}"
        )
        print("OK: send on dead socket closed the queue quietly, no thread crash")
    finally:
        threading.excepthook = old_hook
        client.close()
        queue.__exit__(None, None, None)
        assert_workers_dead(queue)


if __name__ == "__main__":
    test_quiet_client_is_pinged_and_survives()
    test_send_on_dead_socket_shuts_down_quietly()
    print("All keepalive regression tests passed.")
