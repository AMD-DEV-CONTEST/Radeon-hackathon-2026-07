"""Reachy Mini Runtime — second BotverseX runtime (M6.3).

Wraps the official `reachy_mini` SDK (`ReachyMini` class) behind the
`RuntimeReader` / `RuntimeWriter` protocols.

Reachy Mini has 9 controlled motors:
  Head (7): body_rotation, stewart_1..stewart_6
  Antennas (2): right_antenna, left_antenna

The SDK communicates with a daemon over WebSocket. For USB-only Reachy Mini
hardware, BotverseX runs Allan's daemon locally (127.0.0.1:8000) and that
daemon talks to the robot over serial.
For dry-run / smoke tests without hardware, `ReachyMiniMockWriter` and
`ReachyMiniMockReader` provide in-memory stand-ins.
"""
from __future__ import annotations

import time
from typing import Dict, List, Optional, Tuple

from .._protocol import RuntimeInfo, register_runtime

REACHY_MINI_JOINT_NAMES = [
    "body_rotation",
    "stewart_1", "stewart_2", "stewart_3",
    "stewart_4", "stewart_5", "stewart_6",
    "right_antenna", "left_antenna",
]

REACHY_MINI_INFO = RuntimeInfo(
    runtime_id="reachy_mini",
    robot_type="reachy_mini",
    display_name="Reachy Mini (Pollen Robotics, 9 DoF)",
    joint_count=9,
    joint_names=REACHY_MINI_JOINT_NAMES,
    urdf_url="/api/urdf/reachy_mini/reachy_mini.urdf",
    supports_telemetry=False,
)


def _try_import_sdk():
    """Lazy-import the reachy_mini SDK. Returns (ReachyMini_class, available)."""
    try:
        from reachy_mini import ReachyMini  # type: ignore
        return ReachyMini, True
    except ImportError:
        return None, False


class ReachyMiniReader:
    """RuntimeReader for Reachy Mini (reads via SDK's get_current_joint_positions)."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8000) -> None:
        self._host = host
        self._port = port
        self._robot = None
        self.is_connected = False

    def connect(self) -> bool:
        ReachyMini, available = _try_import_sdk()
        if not available:
            print("[ERR] reachy_mini SDK not installed; reader stays offline")
            return False
        try:
            self._robot = ReachyMini(host=self._host, port=self._port, timeout=5.0)
            self.is_connected = True
            print(f"[OK] Reachy Mini reader connected ({self._host}:{self._port})")
            return True
        except Exception as exc:
            print(f"[ERR] Reachy Mini connect failed: {exc}")
            self.is_connected = False
            return False

    def read_positions(self) -> Optional[List[float]]:
        if not self.is_connected or self._robot is None:
            return None
        try:
            head, antennas = self._robot.get_current_joint_positions()
            return list(head) + list(antennas)
        except Exception as exc:
            print(f"[WARN] Reachy Mini read failed: {exc}")
            return None

    def read_telemetry(self) -> Dict[str, Optional[List[Optional[float]]]]:
        return {}

    def disconnect(self) -> None:
        if self._robot is not None:
            try:
                self._robot.disable_motors()
            except Exception:
                pass
            self._robot = None
        self.is_connected = False


class ReachyMiniWriter:
    """RuntimeWriter for Reachy Mini (writes via SDK's _set_joint_positions)."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8000) -> None:
        self._host = host
        self._port = port
        self._robot = None
        self.is_connected = False
        self.torque_enabled = False

    def connect(self) -> bool:
        ReachyMini, available = _try_import_sdk()
        if not available:
            print("[ERR] reachy_mini SDK not installed; writer stays offline")
            return False
        try:
            self._robot = ReachyMini(host=self._host, port=self._port, timeout=5.0)
            self._robot.disable_motors()
            self.is_connected = True
            self.torque_enabled = False
            print(f"[OK] Reachy Mini writer connected ({self._host}:{self._port})")
            return True
        except Exception as exc:
            print(f"[ERR] Reachy Mini writer connect failed: {exc}")
            self.is_connected = False
            return False

    def preflight(self) -> Tuple[bool, str]:
        if not self.is_connected or self._robot is None:
            return (False, "not connected")
        try:
            head, antennas = self._robot.get_current_joint_positions()
            if len(head) != 7 or len(antennas) != 2:
                return (False, f"unexpected joint counts: head={len(head)}, ant={len(antennas)}")
            return (True, "preflight ok")
        except Exception as exc:
            return (False, f"preflight read failed: {exc}")

    def enable_torque(self) -> bool:
        if not self.is_connected or self._robot is None:
            print("[ERR] cannot enable torque: not connected")
            return False
        ok, reason = self.preflight()
        if not ok:
            print(f"[ERR] preflight failed, refusing torque: {reason}")
            return False
        try:
            self._robot.enable_motors()
            self.torque_enabled = True
            print("[OK] Reachy Mini torque ENABLED (all 9 motors)")
            return True
        except Exception as exc:
            print(f"[ERR] enable_motors failed: {exc}")
            return False

    def disable_torque(self) -> None:
        if not self.is_connected or self._robot is None:
            return
        try:
            self._robot.disable_motors()
        except Exception:
            pass
        self.torque_enabled = False
        print("[OK] Reachy Mini torque DISABLED")

    def write_positions(self, joints_rad: Dict[str, float]) -> int:
        """Write joint positions. Keys are joint names from REACHY_MINI_JOINT_NAMES
        or index strings "0".."8"."""
        if not self.is_connected or self._robot is None or not self.torque_enabled:
            return 0

        head = [0.0] * 7
        antennas = [0.0] * 2
        head_set = False
        ant_set = False

        name_to_idx = {n: i for i, n in enumerate(REACHY_MINI_JOINT_NAMES)}

        for key, val in joints_rad.items():
            idx = name_to_idx.get(key)
            if idx is None:
                try:
                    idx = int(key)
                except ValueError:
                    continue
            if 0 <= idx < 7:
                head[idx] = float(val)
                head_set = True
            elif 7 <= idx < 9:
                antennas[idx - 7] = float(val)
                ant_set = True

        try:
            self._robot._set_joint_positions(
                head_joint_positions=head if head_set else None,
                antennas_joint_positions=antennas if ant_set else None,
            )
            return sum(1 for _ in joints_rad)
        except Exception as exc:
            print(f"[ERR] Reachy Mini write failed: {exc}")
            return 0

    def disconnect(self) -> None:
        self.disable_torque()
        self._robot = None
        self.is_connected = False


# ── Mock implementations for dry-run / smoke ──

class ReachyMiniMockReader:
    """In-memory mock reader for Reachy Mini."""

    def __init__(self) -> None:
        self.is_connected = False
        self._t0 = 0.0

    def connect(self) -> bool:
        self.is_connected = True
        self._t0 = time.time()
        return True

    def read_positions(self) -> Optional[List[float]]:
        if not self.is_connected:
            return None
        import math
        t = time.time() - self._t0
        return [0.1 * math.sin(t * 0.5 + i) for i in range(9)]

    def read_telemetry(self) -> Dict[str, Optional[List[Optional[float]]]]:
        return {}

    def disconnect(self) -> None:
        self.is_connected = False


class ReachyMiniMockWriter:
    """In-memory mock writer for Reachy Mini."""

    def __init__(self, name: str = "reachy_mini_mock") -> None:
        self.name = name
        self.is_connected = False
        self.torque_enabled = False
        self.write_log: List[Dict[str, float]] = []
        self.events: List[str] = []

    def connect(self) -> bool:
        self.is_connected = True
        self.events.append("connect")
        return True

    def preflight(self) -> Tuple[bool, str]:
        self.events.append("preflight")
        return (True, "mock ok")

    def enable_torque(self) -> bool:
        self.torque_enabled = True
        self.events.append("torque_on")
        return True

    def disable_torque(self) -> None:
        self.torque_enabled = False
        self.events.append("torque_off")

    def write_positions(self, joints_rad: Dict[str, float]) -> int:
        if not self.is_connected or not self.torque_enabled:
            return 0
        self.write_log.append(dict(joints_rad))
        return len(joints_rad)

    def disconnect(self) -> None:
        self.disable_torque()
        self.is_connected = False
        self.events.append("disconnect")


class ReachyMiniRuntime:
    """Factory grouping reader + writer + info for Reachy Mini."""

    info = REACHY_MINI_INFO

    @staticmethod
    def create_reader(host: str = "127.0.0.1", port: int = 8000, **kwargs) -> ReachyMiniReader:
        return ReachyMiniReader(host=host, port=port)

    @staticmethod
    def create_writer(host: str = "127.0.0.1", port: int = 8000, **kwargs) -> ReachyMiniWriter:
        return ReachyMiniWriter(host=host, port=port)

    @staticmethod
    def create_mock_reader(**kwargs) -> ReachyMiniMockReader:
        return ReachyMiniMockReader()

    @staticmethod
    def create_mock_writer(**kwargs) -> ReachyMiniMockWriter:
        return ReachyMiniMockWriter(**kwargs)


register_runtime("reachy_mini", ReachyMiniRuntime)
