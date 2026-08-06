"""Cross-module identity and terminal telemetry contract checks."""

from __future__ import annotations

import socket
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(PROJECT_ROOT))
from match_protocol import (
    MSG_HELLO,
    capture_terminal_telemetry,
    identity_for_role,
    pack_handshake,
    recv_msg,
    validate_identity,
)


def test_worker_identity_is_role_derived_not_socket_order():
    assert identity_for_role("B_keeper", 0, "Rule", "a" * 64, False) == {
        "team": "B", "role": "keeper", "controller": "Rule",
        "model_sha": "a" * 64, "ball_authority": False,
    }


def test_handshake_round_trip_uses_json_bytes_frame():
    server, client = socket.socketpair()
    try:
        identity = {
            "team": "A", "role": "attacker", "controller": "ONNX",
            "model_sha": "a" * 64, "ball_authority": True,
        }
        client.sendall(pack_handshake(identity))
        msg_type, payload = recv_msg(server)
        assert msg_type == MSG_HELLO
        assert payload == identity
    finally:
        server.close()
        client.close()


def test_identity_validation_requires_declared_authority_and_sha256():
    identity = identity_for_role("A_attacker", 0, "ONNX", "b" * 64, True)
    assert validate_identity(identity, strict=True) == identity
    for mutation in (
        {**identity, "ball_authority": 1},
        {**identity, "model_sha": "short"},
        {**identity, "controller": "invalid"},
    ):
        try:
            validate_identity(mutation, strict=True)
        except ValueError:
            continue
        raise AssertionError(f"invalid identity accepted: {mutation}")


def test_terminal_capture_prefers_canonical_terminal_state():
    terminal_state = {"base_pos": np.asarray([[9.0, 8.0, 7.0]], dtype=np.float32)}
    result = capture_terminal_telemetry(
        {"terminal_state": terminal_state, "terminal": {"base_pos": [[1, 2, 3]]}},
        [0, 0, 0], [0, 0, 0], [0, 0, 0], [0, 0, 0],
    )
    np.testing.assert_allclose(result["base_pos"], [9, 8, 7])
    assert result["fallen"] is False


def test_hierarchical_env_exposes_pre_reset_terminal_state():
    source = (PROJECT_ROOT / "soccer_env_hierarchical.py").read_text(encoding="utf-8")
    assert 'self.extras["fallen"]' in source
    assert 'self.extras["scored"]' in source
    assert 'self.extras["terminal_state"]' in source
    assert '"base_pos": self.base_pos.detach().clone()' in source
    assert '"base_euler": self.base_euler.detach().clone()' in source
    assert '"ball_pos": self.ball_pos.detach().clone()' in source
    assert '"ball_vel": self.ball_vel.detach().clone()' in source
