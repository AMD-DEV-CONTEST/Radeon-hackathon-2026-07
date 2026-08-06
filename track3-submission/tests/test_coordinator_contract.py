"""CPU-only coordinator shutdown protocol checks."""

from __future__ import annotations

import socket
import threading
import time
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
import match_coordinator as coordinator_module
from match_coordinator import (
    MSG_END, MSG_STATE, MSG_WORLD, MatchCoordinator, pack_handshake, pack_state,
    recv_msg,
)


def test_broadcast_end_delivers_frame_before_eof(monkeypatch, tmp_path):
    server, client = socket.socketpair()
    try:
        monkeypatch.setattr(coordinator_module, "END_GRACE_SECONDS", 0)
        coordinator = MatchCoordinator(port=0, n_teams=2, log_dir=str(tmp_path))
        coordinator.clients = {"client_0": server}

        assert coordinator._broadcast_end() == 0
        msg_type, data = recv_msg(client)
        assert msg_type == MSG_END
        assert data == []
        assert client.recv(1) == b""
    finally:
        server.close()
        client.close()


def test_broadcast_end_reports_send_failure(monkeypatch, tmp_path):
    server, client = socket.socketpair()
    client.close()
    try:
        monkeypatch.setattr(coordinator_module, "END_GRACE_SECONDS", 0)
        coordinator = MatchCoordinator(port=0, n_teams=2, log_dir=str(tmp_path))
        coordinator.clients = {"client_0": server}
        server.close()
        assert coordinator._broadcast_end() == 1
    finally:
        server.close()


def test_slow_consumer_eventually_receives_end_after_backlog(monkeypatch, tmp_path):
    """A delayed reader must still observe END after queued updates."""
    server, client = socket.socketpair()
    client.settimeout(2)
    try:
        monkeypatch.setattr(coordinator_module, "END_GRACE_SECONDS", 0)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
        coordinator = MatchCoordinator(port=0, n_teams=2, log_dir=str(tmp_path), sync_hz=2)
        coordinator.clients = {"client_0": server}
        result = []

        def produce_backlog_then_end():
            for _ in range(128):
                assert coordinator._safe_send(server, MSG_WORLD, [0.0] * 100)
            result.append(coordinator._broadcast_end())

        producer = threading.Thread(target=produce_backlog_then_end)
        producer.start()
        time.sleep(0.1)  # deliberately slower than the producer

        saw_end = False
        for _ in range(256):
            msg_type, _ = recv_msg(client)
            if msg_type == MSG_END:
                saw_end = True
                break
        producer.join(timeout=2)
        assert not producer.is_alive()
        assert result == [0]
        assert saw_end
    finally:
        server.close()
        client.close()


def test_sync_hz_must_be_positive(tmp_path):
    for invalid in (0, float("nan"), float("inf"), float("-inf")):
        try:
            MatchCoordinator(port=0, n_teams=2, log_dir=str(tmp_path), sync_hz=invalid)
        except ValueError:
            continue
        raise AssertionError(f"sync_hz={invalid!r} should be rejected")


def test_handler_shutdown_is_unblocked_and_joined(tmp_path):
    server, client = socket.socketpair()
    try:
        coordinator = MatchCoordinator(port=0, n_teams=2, log_dir=str(tmp_path), sync_hz=2)
        coordinator.running = True
        handler = threading.Thread(target=coordinator._handle_client,
                                   args=(server, "client_0"))
        coordinator.client_threads.append(handler)
        handler.start()
        time.sleep(0.02)

        coordinator.ending = True
        coordinator.running = False
        server.shutdown(socket.SHUT_RDWR)
        handler.join(timeout=1)

        assert not handler.is_alive()
        assert coordinator.handler_errors == []
    finally:
        server.close()
        client.close()


def test_handshake_binds_identity_and_extended_events_without_accept_order(tmp_path):
    server, client = socket.socketpair()
    try:
        coordinator = MatchCoordinator(port=0, n_teams=2, log_dir=str(tmp_path), sync_hz=2)
        coordinator.clients = {"client_7": server}
        coordinator.identities = {}
        coordinator.states = {"client_7": {"x": 0, "y": 0, "z": 0.7,
                                             "pitch": 0, "roll": 0}}
        coordinator.running = True
        handler = threading.Thread(target=coordinator._handle_client,
                                   args=(server, "client_7"))
        handler.start()
        client.sendall(pack_handshake({
            "team": "B", "role": "keeper", "controller": "Rule",
            "model_sha": "a" * 64, "ball_authority": False,
        }))
        client.sendall(pack_state(MSG_STATE, [1, 2, 3, 4, 5, 1, 0]))
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline and "client_7" not in coordinator.identities:
            time.sleep(0.01)
        assert coordinator.identities["client_7"] == {
            "team": "B", "role": "keeper", "controller": "Rule",
            "model_sha": "a" * 64, "ball_authority": False,
        }
        assert coordinator.states["client_7"]["fallen"] is True
        assert coordinator.states["client_7"]["scored"] is False
    finally:
        coordinator.ending = True
        coordinator.running = False
        server.shutdown(socket.SHUT_RDWR)
        handler.join(timeout=1)
        server.close()
        client.close()
