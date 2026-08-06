"""Feetech leader-arm reader, lerobot-calibrated.

Reads Present_Position via FeetechMotorsBus with the **leader's own**
MotorCalibration applied, so sync_read(..., normalize=True) returns
device-independent normalized values in [-100, +100] (or [0, 100] for
the gripper). The sender then converts those to radians using
`joint_angles.normalized_to_rad()` — the same conversion the follower
will invert — giving us a coordinate system the two arms actually share.

This replaces the old path where we read raw ticks and ran them through
a per-device linear interpolation (`servo_to_angle`) from a hand-written
JSON; that path required leader and follower JSONs to be hand-kept in
sync and drifted in practice.

Graceful fallbacks:
  - If `lerobot` isn't importable, `connect()` returns False and the
    sender falls back to dry-mode (synthetic motion).
  - If no calibration file is found on disk, `connect()` prints a loud
    WARN and refuses to connect — caller should push the user through
    the calibration wizard (Step 2) before retrying.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class TelemetryFrame:
    """One motor-read cycle. Positions are in lerobot-normalized units
    ([-100, +100] for joints, [0, 100] for gripper), keyed by motor name.
    Telemetry scalars are per-motor where available.
    """

    positions_normalized: Dict[str, float] = field(default_factory=dict)
    temperatures_c: Dict[str, Optional[float]] = field(default_factory=dict)
    currents_a: Dict[str, Optional[float]] = field(default_factory=dict)
    voltages_v: Dict[str, Optional[float]] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)


def _try_import_lerobot():
    try:
        from lerobot.motors.feetech import FeetechMotorsBus
        return FeetechMotorsBus
    except Exception as exc:
        print(f"[WARN] lerobot import failed, staying in dry mode: {exc}")
        return None


class LeaderArmReader:
    """Leader arm reader with lerobot calibration applied.

    Args:
      port: serial device path (e.g. /dev/ttyACM1).
      device_id: calibration device_id on disk (e.g. 'ethan_leader'). If
        None, we auto-discover by scanning the calibration folder.
      read_telemetry: if True, also read temp/current/voltage each cycle.
    """

    def __init__(
        self,
        port: str,
        device_id: Optional[str] = None,
        read_telemetry: bool = True,
        telemetry_hz: float = 5.0,
    ) -> None:
        self.port = port
        self.device_id_arg = device_id
        self.device_id: Optional[str] = None
        self.read_telemetry_enabled = read_telemetry
        # Telemetry (voltage/temp/current) is SLOW over Feetech serial —
        # ~3 sync_reads × ~1ms each ≈ 3-5ms/frame — so sampling it every
        # frame at 64Hz consumes 20-30% of the cycle and introduces
        # visible jitter in leader→follower tracking. These registers
        # barely change, so we throttle to a lower rate and cache the
        # last-seen values for the faster-running UI telemetry panel.
        self.telemetry_interval = 1.0 / max(1.0, float(telemetry_hz))
        self._cached_temps: Dict[str, Optional[float]] = {}
        self._cached_currents: Dict[str, Optional[float]] = {}
        self._cached_voltages: Dict[str, Optional[float]] = {}
        self._last_telemetry_at: float = 0.0
        self.motor_bus = None
        self.is_connected = False
        self._motor_names: List[str] = []
        # Populated on connect() failure for UI reporting.
        self._last_connect_error: str = ""

    def connect(self) -> bool:
        """Open the serial bus with lerobot calibration loaded.

        Returns False if:
          - lerobot not importable
          - no calibration file found for the leader (user must calibrate)
          - port open failed
        """
        FeetechMotorsBus = _try_import_lerobot()
        if FeetechMotorsBus is None:
            self._last_connect_error = "lerobot.motors unavailable"
            return False

        from .lerobot_calibration import build_motors_dict, resolve_and_load

        dev_id, calibration = resolve_and_load("leader", self.device_id_arg)
        if dev_id is None:
            self._last_connect_error = (
                "no leader calibration file found under "
                "~/.cache/huggingface/lerobot/calibration/teleoperators/so101_leader/. "
                "Run calibration first (Step 2)."
            )
            print(f"[ERR] {self._last_connect_error}")
            return False
        if calibration is None:
            self._last_connect_error = (
                f"calibration id '{dev_id}' resolved but file missing. "
                "Re-run calibration for this device."
            )
            print(f"[ERR] {self._last_connect_error}")
            return False
        self.device_id = dev_id

        try:
            print(f"[INFO] opening leader on {self.port} (calibration={dev_id})")
            # Build the bus from this calibration's actual motor set.
            # Some leader setups are 5-DOF (no gripper id=6), and forcing a
            # 6-motor bus makes connect() fail with "Missing motor IDs: 6".
            motor_names = list(calibration.keys())
            motors = build_motors_dict(motor_names)
            self._motor_names = list(motors.keys())
            self.motor_bus = FeetechMotorsBus(port=self.port, motors=motors, calibration=calibration)
            try:
                self.motor_bus.connect()
            except Exception as exc:
                msg = str(exc)
                # Some leader arms are effectively 5-DOF on the bus (id=6 not
                # responding) even though the calibration JSON still contains
                # "gripper". Retry once without gripper instead of hard-fail.
                if "Missing motor IDs" in msg and "6" in msg and "gripper" in motor_names:
                    motor_names = [n for n in motor_names if n != "gripper"]
                    calibration = {k: v for k, v in calibration.items() if k != "gripper"}
                    motors = build_motors_dict(motor_names)
                    self._motor_names = list(motors.keys())
                    self.motor_bus = FeetechMotorsBus(
                        port=self.port,
                        motors=motors,
                        calibration=calibration,
                    )
                    self.motor_bus.connect()
                else:
                    raise
            # Match lerobot SO101Leader.configure(): reduce bus latency + set
            # position mode before streaming reads (same as MakerMods teleop).
            from lerobot.motors.feetech import OperatingMode  # type: ignore

            self.motor_bus.disable_torque()
            self.motor_bus.configure_motors()
            for motor in self._motor_names:
                self.motor_bus.write("Operating_Mode", motor, OperatingMode.POSITION.value)
            self.is_connected = True
            print(f"[OK] leader arm connected (calibration applied for {len(calibration)} motors)")
            return True
        except Exception as exc:
            print(f"[ERR] leader connect failed: {exc}")
            self._last_connect_error = f"{type(exc).__name__}: {exc}"
            self.is_connected = False
            return False

    def _sync_read_scaled(self, register: str, scale: float = 1.0) -> Dict[str, Optional[float]]:
        """Batch read one register for all motors in a single sync_read.

        Roughly 6× cheaper on the wire than the old per-motor loop because
        it's one Feetech SYNC_READ packet instead of six single reads.
        """
        out: Dict[str, Optional[float]] = {n: None for n in self._motor_names}
        if self.motor_bus is None:
            return out
        try:
            raw = self.motor_bus.sync_read(register, self._motor_names, normalize=False)
        except Exception:
            return out
        for name in self._motor_names:
            v = raw.get(name)
            if v is None:
                continue
            try:
                out[name] = float(v) * scale
            except (TypeError, ValueError):
                out[name] = None
        return out

    def read(self) -> TelemetryFrame:
        """One read cycle.

        Positions are **normalized** (lerobot's calibrated -100..+100 /
        0..100). Conversion to URDF radians happens in sender._build_payload.

        Telemetry (voltage/temp/current) is refreshed at
        `telemetry_interval` (default 5Hz) to keep the loop fast; the
        last-seen values are cached and re-used on frames where we skip
        the actual read, so downstream consumers always see a populated
        dict.
        """
        frame = TelemetryFrame()
        if not self.is_connected or self.motor_bus is None:
            return frame
        try:
            positions = self.motor_bus.sync_read(
                "Present_Position", self._motor_names, normalize=True
            )
            frame.positions_normalized = {
                n: float(positions[n]) for n in self._motor_names if n in positions
            }
        except Exception as exc:
            frame.errors.append(f"positions: {exc}")
            return frame
        if self.read_telemetry_enabled:
            now = time.time()
            if now - self._last_telemetry_at >= self.telemetry_interval:
                # sts3215 register scale factors (Feetech datasheet):
                #   temp: deg C direct
                #   current: raw unit ~6.5 mA
                #   voltage: 0.1 V / tick
                self._cached_temps = self._sync_read_scaled("Present_Temperature", scale=1.0)
                self._cached_currents = self._sync_read_scaled("Present_Current", scale=0.0065)
                self._cached_voltages = self._sync_read_scaled("Present_Voltage", scale=0.1)
                self._last_telemetry_at = now
            frame.temperatures_c = dict(self._cached_temps)
            frame.currents_a = dict(self._cached_currents)
            frame.voltages_v = dict(self._cached_voltages)
        return frame

    def disconnect(self) -> None:
        if self.motor_bus is not None:
            try:
                self.motor_bus.disconnect()
            except Exception:
                pass
        self.motor_bus = None
        self.is_connected = False


__all__ = ["LeaderArmReader", "TelemetryFrame"]
