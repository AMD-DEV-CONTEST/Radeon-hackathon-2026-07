"""CPU-only wire and telemetry helpers shared by workers and coordinator."""

from __future__ import annotations

import json
import re
import struct

MSG_STATE = 1
MSG_BALL = 2
MSG_CMD = 3
MSG_END = 4
MSG_WORLD = 5
MSG_HELLO = 6
MAX_HELLO_BYTES = 64 * 1024
MAX_MSG_BYTES = 16 * 1024 * 1024  # cap for non-HELLO payloads (16 MB)

IDENTITY_KEYS = ("team", "role", "controller", "model_sha", "ball_authority")
VALID_TEAMS = {"A", "B"}
VALID_ROLES = {"attacker", "defender", "keeper"}
VALID_CONTROLLERS = {"ONNX", "Rule"}


def pack_state(msg_type, data):
    payload = struct.pack(f"<{len(data)}f", *data) if data else b""
    return struct.pack("<BI", msg_type, len(data)) + payload


def pack_handshake(identity):
    payload = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(payload) > MAX_HELLO_BYTES:
        raise ValueError("identity handshake is too large")
    return struct.pack("<BI", MSG_HELLO, len(payload)) + payload


def recv_all(sock, n):
    data = b""
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            return None
        data += chunk
    return data


def recv_msg(sock):
    header = recv_all(sock, 5)
    if not header:
        return None, None
    msg_type, length = struct.unpack("<BI", header)
    if msg_type == MSG_HELLO:
        if length > MAX_HELLO_BYTES:
            raise ValueError("identity handshake is too large")
        payload = recv_all(sock, length)
        if payload is None:
            return None, None
        return msg_type, json.loads(payload.decode("utf-8"))
    if length * 4 > MAX_MSG_BYTES:
        print(f"[match_protocol] refusing oversized message (type={msg_type}, length={length} floats)")
        return None, None
    if length == 0:
        return msg_type, []
    data = recv_all(sock, length * 4)
    if not data:
        return None, None
    return msg_type, struct.unpack(f"<{length}f", data)


def identity_for_role(role, team_id=0, controller="Rule", model_sha="unknown",
                      ball_authority=False):
    """Build declared identity without relying on coordinator accept order."""
    role = str(role)
    prefix, separator, role_name = role.partition("_")
    if separator and prefix in VALID_TEAMS:
        team = prefix
        role_name = role_name or "unknown"
    else:
        team = str(team_id)
        role_name = role
    return {
        "team": team,
        "role": role_name,
        "controller": str(controller),
        "model_sha": model_sha if model_sha else "unknown",
        "ball_authority": bool(ball_authority),
    }


def validate_identity(identity, *, strict=True):
    """Return a normalized identity, optionally enforcing the match contract."""
    if not isinstance(identity, dict):
        raise ValueError("identity handshake must be a JSON object")
    normalized = {}
    for key in IDENTITY_KEYS:
        value = identity.get(key)
        if value is None:
            if strict:
                raise ValueError(f"identity missing {key}")
            value = "unknown"
        if key == "ball_authority":
            if not isinstance(value, bool):
                raise ValueError("identity ball_authority must be boolean")
            normalized[key] = value
            continue
        if not isinstance(value, (str, int, float, bool)):
            raise ValueError(f"identity {key} must be scalar")
        value = str(value)
        if not value:
            raise ValueError(f"identity {key} must be non-empty")
        normalized[key] = value
    if strict:
        if normalized["team"] not in VALID_TEAMS:
            raise ValueError("identity team must be A or B")
        if normalized["role"] not in VALID_ROLES:
            raise ValueError("identity role must be attacker, defender, or keeper")
        if normalized["controller"] not in VALID_CONTROLLERS:
            raise ValueError("identity controller must be ONNX or Rule")
        if not re.fullmatch(r"[0-9a-f]{64}", normalized["model_sha"]):
            raise ValueError("identity model_sha must be a 64-character SHA-256 hex digest")
    return normalized


def _flatten(value):
    if value is None:
        return None
    try:
        value = value.detach().cpu()
    except AttributeError:
        pass
    try:
        value = value.reshape(-1)
    except AttributeError:
        pass
    try:
        value = value.tolist()
    except AttributeError:
        pass
    if isinstance(value, (list, tuple)):
        result = []
        for item in value:
            if isinstance(item, (list, tuple)):
                result.extend(_flatten(item) or [])
            else:
                result.append(float(item))
        return result
    try:
        return [float(value)]
    except (TypeError, ValueError):
        return None


def _scalar_bool(value, default=False):
    if value is None:
        return bool(default)
    try:
        value = value.detach().cpu()
    except AttributeError:
        pass
    try:
        value = value.reshape(-1)
        value = value[0]
    except (AttributeError, IndexError, TypeError):
        if isinstance(value, (list, tuple)):
            if not value:
                return bool(default)
            return _scalar_bool(value[0], default)
    try:
        return bool(value.item())
    except AttributeError:
        try:
            return bool(value)
        except (TypeError, ValueError):
            return bool(default)


def capture_terminal_telemetry(extras, fallback_pos, fallback_euler,
                               fallback_ball_pos, fallback_ball_vel):
    """Capture pre-reset state and event flags from an env step result.

    ``terminal_state`` is canonical; ``terminal`` remains a compatibility
    alias for older environments.  The function deliberately has no torch or
    numpy dependency so protocol tests run in a CPU-only collection sandbox.
    """
    extras = extras if isinstance(extras, dict) else {}
    terminal = extras.get("terminal_state") or extras.get("terminal") or {}
    return {
        "fallen": _scalar_bool(extras.get("fallen"), _scalar_bool(terminal.get("fallen"), False)),
        "scored": _scalar_bool(extras.get("scored"), _scalar_bool(terminal.get("scored"), False)),
        "done": _scalar_bool(extras.get("done"), _scalar_bool(terminal.get("done"), False)),
        "base_pos": _flatten(terminal.get("base_pos")) or _flatten(fallback_pos) or [],
        "base_euler": _flatten(terminal.get("base_euler")) or _flatten(fallback_euler) or [],
        "ball_pos": _flatten(terminal.get("ball_pos")) or _flatten(fallback_ball_pos) or [],
        "ball_vel": _flatten(terminal.get("ball_vel")) or _flatten(fallback_ball_vel) or [],
    }
