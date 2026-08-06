"""BotclawSender — connects to realtime /ws/teleop and streams JointUpdate (BotClaw v0.4).

v0.4 additions vs legacy `apps/realtime/sender.py`:
- Telemetry: temperatures_c / currents_a / voltages_v included as top-level optional fields
  (per spec, JointUpdate now accepts them; RobotState WS aggregates).
- arm_id URL parameter (M4.2 multi-arm placeholder).
- Dry mode: when LeRobot unavailable or --dry_run, emits synthetic sine-wave motion so the
  full closed loop (UI, record, compare echo) is testable without hardware.
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import sys
import time
from typing import Optional

# BotClaw contract package must be importable (run from apps/realtime root or via `python -m apps.realtime.sender`).
_SPEC_PY = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "packages", "botclaw-spec", "python")
)
if os.path.isdir(_SPEC_PY) and _SPEC_PY not in sys.path:
    sys.path.insert(0, _SPEC_PY)

from .joint_angles import MOTOR_NAME_TO_ID, normalized_to_rad
from .reader import LeaderArmReader, TelemetryFrame


DEFAULT_API_WS = "ws://localhost:8002/ws/teleop"


def _build_payload(
    robot_id: str,
    frame: TelemetryFrame,
    fps: float,
) -> dict:
    """Build a BotClaw v0.4 JointUpdate payload from a normalized-position frame.

    Wire protocol (unchanged):
      - joints:        {'1'..'6' -> radians}
      - servo_values:  {'1'..'6' -> normalized * 100 (kept as int for
                       back-compat with existing viewers that ignore it)}

    The magic here is that `frame.positions_normalized` is already
    device-independent (came out of lerobot sync_read with the leader's
    own calibration applied), so the normalized→rad mapping in
    `joint_angles.normalized_to_rad` can be the single source of truth
    shared between leader and follower.
    """
    joints: dict[str, float] = {}
    servo_values: dict[str, int] = {}
    for name, norm in (frame.positions_normalized or {}).items():
        motor_id = MOTOR_NAME_TO_ID.get(name)
        if motor_id is None:
            continue
        key = str(motor_id)
        joints[key] = float(normalized_to_rad(name, norm))
        # Keep a numeric sentinel for legacy consumers. Not raw ticks
        # anymore — they'd be meaningless across devices — but still
        # handy as a debug signal proportional to joint extension.
        servo_values[key] = int(round(norm * 100))

    payload: dict = {
        "type": "joint_update",
        "robot_id": robot_id,
        "timestamp": time.time(),
        "joints": joints,
        "servo_values": servo_values,
        "meta": {"fps": float(fps), "source": "leader_arm"},
    }

    def _remap(series: dict[str, Optional[float]] | None) -> Optional[dict[str, Optional[float]]]:
        if not series:
            return None
        out: dict[str, Optional[float]] = {}
        for name, v in series.items():
            motor_id = MOTOR_NAME_TO_ID.get(name)
            if motor_id is None:
                continue
            out[str(motor_id)] = None if v is None else float(v)
        return out or None

    remapped_t = _remap(frame.temperatures_c)
    if remapped_t:
        payload["temperatures_c"] = remapped_t
    remapped_c = _remap(frame.currents_a)
    if remapped_c:
        payload["currents_a"] = remapped_c
    remapped_v = _remap(frame.voltages_v)
    if remapped_v:
        payload["voltages_v"] = remapped_v
    return payload


def _dry_frame(t_start: float) -> TelemetryFrame:
    """Smooth synthetic motion in normalized units for dry-run."""
    t = time.time() - t_start
    base_normalized = {
        "shoulder_pan":  40.0 * math.sin(t * 0.5),
        "shoulder_lift": 30.0 * math.sin(t * 0.4 + 1.0),
        "elbow_flex":    25.0 * math.sin(t * 0.3 + 2.0),
        "wrist_flex":    20.0 * math.sin(t * 0.6 + 3.0),
        "wrist_roll":    30.0 * math.sin(t * 0.7),
        "gripper":       50.0 + 30.0 * math.sin(t * 0.9),  # 0_100 range
    }
    return TelemetryFrame(
        positions_normalized=base_normalized,
        temperatures_c={n: 35.0 + 0.5 * math.sin(t * 0.1 + i) for i, n in enumerate(base_normalized)},
        currents_a={n: 0.1 + 0.05 * abs(math.sin(t * 0.4 + i)) for i, n in enumerate(base_normalized)},
        voltages_v={n: 12.0 + 0.1 * math.sin(t * 0.05 + i) for i, n in enumerate(base_normalized)},
    )


class BotclawSender:
    """Async websocket client streaming JointUpdate to realtime /ws/teleop."""

    def __init__(
        self,
        com_port: str = "/dev/ttyACM0",
        device_id: Optional[str] = None,
        robot_id: Optional[str] = None,
        arm_id: str = "arm_0",
        api_url: str = DEFAULT_API_WS,
        send_hz: float = 60.0,
        dry_run: bool = False,
        read_telemetry: bool = True,
    ) -> None:
        """
        Args:
          com_port: leader arm serial device.
          device_id: leader calibration id under
            ~/.cache/huggingface/lerobot/calibration/teleoperators/so101_leader/.
            None auto-discovers if exactly one file is present.
        """
        self.robot_id = robot_id or os.environ.get("BOTVERSEX_ROBOT_ID", "so101-001")
        self.arm_id = arm_id
        self.api_url = api_url
        # Match lerobot_teleoperate default (TeleoperateConfig.fps = 60).
        self.send_hz = max(1.0, float(send_hz))
        self.send_interval = 1.0 / self.send_hz
        self.running = False
        self.reader = LeaderArmReader(
            port=com_port,
            device_id=device_id,
            read_telemetry=read_telemetry,
        )
        self.dry_run = dry_run
        if not self.dry_run:
            if not self.reader.connect():
                print(
                    f"[INFO] hardware unavailable ({self.reader._last_connect_error}); "
                    "falling back to dry mode"
                )
                self.dry_run = True
        else:
            print("[INFO] dry mode: generating synthetic motion (no hardware)")
        self._dry_start = time.time()

    async def _send_one(self, ws, payload: dict) -> None:
        import websockets.exceptions as _wse

        try:
            await ws.send(json.dumps(payload))
        except (_wse.ConnectionClosed, ConnectionResetError, OSError):
            raise

    async def run_async(self) -> None:
        import websockets

        # append arm_id to URL, but only if not already present
        sep = "&" if "?" in self.api_url else "?"
        url = (
            self.api_url
            if "arm_id=" in self.api_url
            else f"{self.api_url}{sep}arm_id={self.arm_id}"
        )
        print(f"[INFO] robot_id={self.robot_id} arm_id={self.arm_id} api={url}")

        while self.running:
            try:
                async with websockets.connect(url, ping_interval=10, ping_timeout=5) as ws:
                    print("[OK] connected to realtime /ws/teleop")
                    fps_counter = 0
                    fps_window_start = time.perf_counter()

                    while self.running:
                        # Same cadence as lerobot_teleoperate.teleop_loop: one
                        # iteration per 1/send_hz seconds, busy-waiting the
                        # remainder so jitter from variable read/send times does
                        # not accumulate into uneven frame spacing.
                        loop_start = time.perf_counter()

                        if self.dry_run or not self.reader.is_connected:
                            frame = _dry_frame(self._dry_start)
                        else:
                            frame = self.reader.read()
                            if not frame.positions_normalized:
                                await asyncio.sleep(0.001)
                                dt_s = time.perf_counter() - loop_start
                                rem = max(0.0, self.send_interval - dt_s)
                                if rem > 0:
                                    await asyncio.sleep(rem)
                                continue

                        now = time.perf_counter()
                        fps_est = fps_counter / max(now - fps_window_start, 1e-6)
                        payload = _build_payload(self.robot_id, frame, fps_est)
                        try:
                            await self._send_one(ws, payload)
                        except Exception as exc:
                            print(f"[ERR] send failed, reconnecting: {exc}")
                            break

                        fps_counter += 1
                        if now - fps_window_start >= 1.0:
                            print(
                                f"\r[sender] robot={self.robot_id} arm={self.arm_id} "
                                f"fps={fps_counter / (now - fps_window_start):.1f}",
                                end="",
                                flush=True,
                            )
                            fps_counter = 0
                            fps_window_start = now

                        dt_s = time.perf_counter() - loop_start
                        rem = max(0.0, self.send_interval - dt_s)
                        if rem > 0:
                            await asyncio.sleep(rem)
            except Exception as exc:
                print(f"\n[ERR] ws connect failed: {exc}, retry in 3s")
                await asyncio.sleep(3)

        self.reader.disconnect()

    def run(self) -> None:
        # Same SIGTERM->KeyboardInterrupt trick as BotclawFollower.run. Leader
        # doesn't manage torque, but we still want an orderly serial-port
        # close so the next teleop start can reopen /dev/ttyACMx without the
        # OS holding it busy for a few seconds.
        import signal as _signal

        def _handle_term(signum, frame):  # noqa: ARG001
            raise KeyboardInterrupt(f"signal {signum}")

        try:
            _signal.signal(_signal.SIGTERM, _handle_term)
            if hasattr(_signal, "SIGHUP"):
                _signal.signal(_signal.SIGHUP, _handle_term)
        except (ValueError, OSError):
            pass

        self.running = True
        try:
            asyncio.run(self.run_async())
        except KeyboardInterrupt:
            print("\n[INFO] interrupted")
        finally:
            self.running = False

    def stop(self) -> None:
        self.running = False
