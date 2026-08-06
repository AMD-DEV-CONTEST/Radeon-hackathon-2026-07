"""Feetech follower-arm writer, lerobot-calibrated.

Takes joint targets in **normalized units** (lerobot's [-100, +100] for
joints, [0, 100] for gripper), applies the follower's own
MotorCalibration, and writes Goal_Position via FeetechMotorsBus with
normalize=True. This is the inverse of `reader.py`'s sync_read; because
both sides use their own calibration, the normalized values on the
wire describe the arm pose in a device-independent way — leader and
follower "speak the same language" without any ad-hoc tick↔angle maps.

Lifecycle:
  connect() → preflight() → enable_torque() → [write_positions()]* → disable_torque() → disconnect()

enable_torque() does two things that matter for "follower doesn't
twitch on startup":
  1. Seeds Goal_Position = Present_Position BEFORE flipping torque on,
     so the servo doesn't lurch toward whatever stale target was in
     its EEPROM. Matches lerobot's so101_follower.configure().
  2. Records `_start_normalized` so write_positions() can smoothly
     ramp from the follower's actual pose to the leader's target over
     `warmup_seconds` (default 0.4s, short vs native lerobot which has none).
     Avoids the "snap to leader on first frame" failure mode when the two
     arms are physically mis-aligned.
"""
from __future__ import annotations

import json
import time
from typing import Dict, Iterable, List, Optional, Protocol


# ------------------ Protocol + Mock -------------------


class BaseArmWriter(Protocol):
    is_connected: bool
    torque_enabled: bool

    def connect(self) -> bool: ...
    def preflight(self) -> tuple[bool, str]: ...
    def enable_torque(self) -> bool: ...
    def disable_torque(self) -> None: ...
    def write_positions(self, normalized: Dict[str, float]) -> int: ...
    def disconnect(self) -> None: ...


class MockArmWriter:
    """In-memory stand-in used by smokes. Records every call so tests can assert."""

    def __init__(self, name: str = "mock") -> None:
        self.name = name
        self.is_connected = False
        self.torque_enabled = False
        self.write_log: List[Dict[str, float]] = []
        self.events: List[str] = []
        self.preflight_ok = True
        # Back-compat shim for follower.py status printer.
        self._last_write_clamped: bool = False

    def connect(self) -> bool:
        self.is_connected = True
        self.events.append("connect")
        return True

    def preflight(self) -> tuple[bool, str]:
        self.events.append("preflight")
        return (self.preflight_ok, "mock ok" if self.preflight_ok else "mock fail")

    def enable_torque(self) -> bool:
        self.torque_enabled = True
        self.events.append("torque_on")
        return True

    def disable_torque(self) -> None:
        self.torque_enabled = False
        self.events.append("torque_off")

    def write_positions(self, normalized: Dict[str, float]) -> int:
        if not self.is_connected or not self.torque_enabled:
            return 0
        self.write_log.append(dict(normalized))
        return len(normalized)

    def disconnect(self) -> None:
        self.disable_torque()
        self.is_connected = False
        self.events.append("disconnect")


# ------------------ Real Feetech writer -------------------


def _try_import_lerobot():
    try:
        from lerobot.motors.feetech import FeetechMotorsBus
        return FeetechMotorsBus
    except Exception as exc:
        print(f"[WARN] lerobot import failed (follower stays in mock mode): {exc}")
        return None


class FollowerArmWriter:
    """Feetech follower writer, lerobot-calibrated.

    Accepts joint targets in normalized units (dict[motor_name, float]).
    Applies the follower's own MotorCalibration when writing, so the same
    normalized value always drives the follower to the pose the leader
    was in when it read that value — regardless of the two arms having
    different homing offsets.
    """

    # Preflight thresholds — refuse to enable torque outside these bands.
    #
    # Why 7.0V (not 10.5V): SO-101 is specced for 7.4–12V. The old 10.5V cut
    # was tuned for the 12V wall-adapter setup and rejects any 2S Li-ion /
    # 7.4V pack as "undervolt". On top of that, a fresh bus read right after
    # connect() sometimes returns a single-shot 7–8V sample (USB enumerate
    # glitch / shared-ground transient) even when a voltmeter shows 11.8V,
    # which is why lerobot-teleoperate skips this check entirely. We keep the
    # check (undervolt on 1S Li-ion / loose power lead is a real failure) but
    # combine it with a 3-sample max in preflight() so a single bad sample
    # doesn't lock the arm out.
    MIN_VOLTAGE_V: float = 7.0
    MAX_TEMPERATURE_C: float = 55.0
    # How many times preflight() re-reads Present_Voltage / Present_Temperature
    # and aggregates (max for voltage, min for temperature). 3 reads ≈ 3ms per
    # motor on Feetech STS3215, negligible vs. the startup cost we already pay.
    PREFLIGHT_SAMPLES: int = 3

    def __init__(
        self,
        port: str,
        device_id: Optional[str] = None,
        warmup_seconds: float = 0.4,
    ) -> None:
        """
        Args:
          port: serial device path.
          device_id: follower calibration id under
            ~/.cache/huggingface/lerobot/calibration/robots/so101_follower/.
            If None, auto-discovers if exactly one file exists.
          warmup_seconds: after enable_torque(), the writer linearly
            blends from `start_normalized` (follower's actual pose at
            torque-on) to the leader target over this window. At t=0
            the goal == follower's current position (no motion); at
            t=warmup_seconds the goal == leader target. Prevents
            violent snaps when the two arms start mis-aligned.
        """
        self.port = port
        self.device_id_arg = device_id
        self.device_id: Optional[str] = None
        self.warmup_seconds = float(warmup_seconds)

        self.motor_bus = None
        self.is_connected = False
        self.torque_enabled = False

        self._motor_names: List[str] = []
        self._motor_ids: List[int] = []
        # Populated on torque-on: motor_name → normalized value at the
        # instant torque came on. Used as the start point for the warmup
        # ramp in write_positions().
        self._start_normalized: Dict[str, float] = {}
        self._torque_enabled_at: float = 0.0

        # Status surfaced to follower.py's periodic status printer.
        self._last_write_clamped: bool = False

        # Human-readable error captured during connect()/enable_torque()
        # for the setup wizard UI to render.
        self._last_connect_error: str = ""
        self._last_torque_error: str = ""
        self._debug_run_id: str = f"writer-{int(time.time() * 1000)}"

    def _debug_log(self, hypothesis_id: str, location: str, message: str, data: Dict[str, object]) -> None:
        try:
            payload = {
                "sessionId": "59adc0",
                "runId": self._debug_run_id,
                "hypothesisId": hypothesis_id,
                "location": location,
                "message": message,
                "data": data,
                "timestamp": int(time.time() * 1000),
            }
            with open("/home/amd/Downloads/botversex/.cursor/debug-59adc0.log", "a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=True) + "\n")
        except Exception:
            pass

    # -- lifecycle ---------------------------------------------------------
    def connect(self) -> bool:
        FeetechMotorsBus = _try_import_lerobot()
        if FeetechMotorsBus is None:
            self._last_connect_error = "lerobot.motors unavailable"
            return False

        from .lerobot_calibration import build_motors_dict, resolve_and_load

        dev_id, calibration = resolve_and_load("follower", self.device_id_arg)
        if dev_id is None:
            self._last_connect_error = (
                "no follower calibration file found under "
                "~/.cache/huggingface/lerobot/calibration/robots/so101_follower/. "
                "Run calibration first (Step 2)."
            )
            print(f"[ERR] {self._last_connect_error}")
            return False
        if calibration is None:
            self._last_connect_error = (
                f"calibration id '{dev_id}' resolved but file missing."
            )
            print(f"[ERR] {self._last_connect_error}")
            return False
        self.device_id = dev_id

        try:
            print(f"[INFO] follower: opening {self.port} (calibration={dev_id})")
            # Match the follower bus to the motors present in its calibration
            # file instead of assuming all 6 always exist.
            motors = build_motors_dict(calibration.keys())
            self._motor_names = list(motors.keys())
            self._motor_ids = [motors[n].id for n in self._motor_names]
            self.motor_bus = FeetechMotorsBus(
                port=self.port,
                motors=motors,
                calibration=calibration,
            )
            self.motor_bus.connect()
            # Match lerobot SO101Follower.configure() (MakerMods / HF SO-101):
            # Return_Delay_Time min, accel profile, lower P gain to reduce
            # mechanical shake, gripper torque limits. Do NOT use
            # torque_disabled() context manager here — it re-enables torque on
            # exit; we keep torque OFF until enable_torque().
            from lerobot.motors.feetech import OperatingMode  # type: ignore

            self.motor_bus.disable_torque()
            self.motor_bus.configure_motors()
            for motor in self._motor_names:
                self.motor_bus.write("Operating_Mode", motor, OperatingMode.POSITION.value)
                self.motor_bus.write("P_Coefficient", motor, 16)
                self.motor_bus.write("I_Coefficient", motor, 0)
                self.motor_bus.write("D_Coefficient", motor, 32)
                if motor == "gripper":
                    self.motor_bus.write("Max_Torque_Limit", motor, 500)
                    self.motor_bus.write("Protection_Current", motor, 250)
                    self.motor_bus.write("Overload_Torque", motor, 25)
            # Torque stays off until enable_torque() is called.
            self._bulk_torque(False)
            self.is_connected = True
            print(f"[OK] follower connected (torque OFF, calibration={dev_id})")
            # region agent log
            self._debug_log(
                "H1",
                "sender/writer.py:connect",
                "connect_success",
                {
                    "port": self.port,
                    "device_id": dev_id,
                    "motor_names": list(self._motor_names),
                    "motor_ids": list(self._motor_ids),
                },
            )
            # endregion
            return True
        except Exception as exc:
            print(f"[ERR] follower connect failed: {exc}")
            self._last_connect_error = f"{type(exc).__name__}: {exc}"
            self.is_connected = False
            return False

    def preflight(self) -> tuple[bool, str]:
        """Read voltages + temperatures; refuse if any motor is out-of-band.

        Each register is sampled PREFLIGHT_SAMPLES times and aggregated:
          - voltage   -> max (first read can land on a transient low)
          - temperature -> min (same reasoning inverted; trust a cool reading
            over a one-off spike that's usually a read glitch, not a real
            thermal event)
        A real fault — loose power lead, single-cell pack, motor actually
        hot — shows up on ALL samples and still fails the gate.
        """
        if not self.is_connected or self.motor_bus is None:
            return (False, "not connected")
        issues: List[str] = []
        samples = max(1, int(self.PREFLIGHT_SAMPLES))
        for name in self._motor_names:
            v_samples: List[float] = []
            t_samples: List[float] = []
            last_err: Optional[str] = None
            for _ in range(samples):
                try:
                    v = float(self.motor_bus.read("Present_Voltage", name, normalize=False)) * 0.1
                    t = float(self.motor_bus.read("Present_Temperature", name, normalize=False))
                    v_samples.append(v)
                    t_samples.append(t)
                except Exception as exc:
                    last_err = f"{type(exc).__name__}: {exc}"
                    continue
            if not v_samples or not t_samples:
                issues.append(f"{name}:read_fail({last_err or 'no samples'})")
                continue
            v_hi = max(v_samples)
            t_lo = min(t_samples)
            if v_hi < self.MIN_VOLTAGE_V:
                issues.append(
                    f"{name}:V={v_hi:.1f}<{self.MIN_VOLTAGE_V} "
                    f"(samples={['%.1f' % x for x in v_samples]})"
                )
            if t_lo > self.MAX_TEMPERATURE_C:
                issues.append(
                    f"{name}:T={t_lo:.1f}>{self.MAX_TEMPERATURE_C} "
                    f"(samples={['%.1f' % x for x in t_samples]})"
                )
            # region agent log
            self._debug_log(
                "H3",
                "sender/writer.py:preflight",
                "preflight_motor_samples",
                {
                    "motor": name,
                    "voltage_samples": [round(x, 2) for x in v_samples],
                    "temperature_samples": [round(x, 2) for x in t_samples],
                    "voltage_max": round(v_hi, 2),
                    "temperature_min": round(t_lo, 2),
                },
            )
            # endregion
        if issues:
            # region agent log
            self._debug_log(
                "H3",
                "sender/writer.py:preflight",
                "preflight_failed",
                {"issues": list(issues)},
            )
            # endregion
            return (False, "; ".join(issues))
        # region agent log
        self._debug_log(
            "H3",
            "sender/writer.py:preflight",
            "preflight_ok",
            {"motor_count": len(self._motor_names)},
        )
        # endregion
        return (True, "preflight ok")

    def enable_torque(self) -> bool:
        if not self.is_connected or self.motor_bus is None:
            print("[ERR] cannot enable torque: not connected")
            self._last_torque_error = "not connected"
            return False
        ok, reason = self.preflight()
        # region agent log
        self._debug_log(
            "H2",
            "sender/writer.py:enable_torque",
            "enable_torque_after_preflight",
            {"ok": bool(ok), "reason": reason},
        )
        # endregion
        if not ok:
            print(f"[ERR] preflight failed, refusing to enable torque: {reason}")
            self._last_torque_error = reason
            return False

        # Seed Goal_Position = Present_Position BEFORE flipping torque on.
        # Also record the normalized start pose so write_positions() can
        # ramp smoothly from here to the leader target.
        try:
            present_normalized = self.motor_bus.sync_read(
                "Present_Position", self._motor_names, normalize=True
            )
            present_raw = self.motor_bus.sync_read(
                "Present_Position", self._motor_names, normalize=False
            )
            # Write raw ticks to Goal_Position so the servo has no stale target.
            try:
                self.motor_bus.sync_write(
                    "Goal_Position", {n: int(present_raw[n]) for n in self._motor_names},
                    normalize=False,
                )
            except Exception:
                for n in self._motor_names:
                    self.motor_bus.write(
                        "Goal_Position", n, int(present_raw[n]), normalize=False,
                    )
            self._start_normalized = {
                n: float(present_normalized[n]) for n in self._motor_names if n in present_normalized
            }
            print(
                f"[OK] seeded Goal_Position = Present_Position for {len(self._start_normalized)} motors"
            )
            # region agent log
            self._debug_log(
                "H2",
                "sender/writer.py:enable_torque",
                "seed_goal_position_ok",
                {
                    "seeded_motor_count": len(self._start_normalized),
                    "seeded_motors": list(self._start_normalized.keys()),
                },
            )
            # endregion
        except Exception as exc:
            print(f"[WARN] failed to seed before torque-on: {exc}; follower may twitch")
            self._start_normalized = {}

        if self._bulk_torque(True):
            self.torque_enabled = True
            self._torque_enabled_at = time.time()
            print(
                f"[OK] torque ENABLED on {len(self._motor_names)} motors "
                f"(ramp present → leader over {self.warmup_seconds:.1f}s)"
            )
            return True
        print("[ERR] torque enable failed on one or more motors")
        # region agent log
        self._debug_log(
            "H2",
            "sender/writer.py:enable_torque",
            "bulk_torque_enable_failed",
            {"motor_names": list(self._motor_names)},
        )
        # endregion
        return False

    def disable_torque(self) -> None:
        if not self.is_connected:
            return
        self._bulk_torque(False)
        self.torque_enabled = False
        print(f"[OK] torque DISABLED on {len(self._motor_names)} motors")

    # -- writes ------------------------------------------------------------
    def write_positions(self, normalized: Dict[str, float]) -> int:
        """Write target joint positions, normalized.

        `normalized` is a mapping from motor name ('shoulder_pan', ..., 'gripper')
        to lerobot-normalized values:
          - M100_100 motors: float in [-100, +100]
          - gripper (0_100): float in [0, 100]

        During the first `warmup_seconds` after torque-on, the written goal
        is a linear blend of `self._start_normalized` and `normalized`:
            goal = start + alpha * (target - start),  alpha = t / warmup
        At alpha=0 the goal equals the pose the follower had when torque
        came on (→ no motion). At alpha=1 the goal is the real leader
        target (→ full tracking).
        """
        if not self.is_connected or self.motor_bus is None:
            return 0
        if not self.torque_enabled:
            return 0
        if not normalized:
            return 0

        # Warmup ramp
        now = time.time()
        elapsed = now - self._torque_enabled_at if self._torque_enabled_at > 0 else 0.0
        in_warmup = 0.0 < elapsed < self.warmup_seconds and bool(self._start_normalized)

        goals: Dict[str, float] = {}
        if in_warmup:
            alpha = max(0.0, min(1.0, elapsed / self.warmup_seconds))
            for name in self._motor_names:
                if name not in normalized:
                    continue
                start = float(self._start_normalized.get(name, normalized[name]))
                target = float(normalized[name])
                goals[name] = start + alpha * (target - start)
            self._last_write_clamped = True
        else:
            for name in self._motor_names:
                if name in normalized:
                    goals[name] = float(normalized[name])
            self._last_write_clamped = False

        if not goals:
            return 0

        try:
            self.motor_bus.sync_write("Goal_Position", goals, normalize=True)
        except Exception as exc:
            # Older bus / firmware may not support sync_write — fall back.
            try:
                for n, v in goals.items():
                    self.motor_bus.write("Goal_Position", n, v, normalize=True)
            except Exception as exc2:
                print(f"[ERR] write_positions failed: {exc} / {exc2}")
                return 0
        return len(goals)

    # -- teardown ----------------------------------------------------------
    def disconnect(self) -> None:
        if self.motor_bus is not None:
            try:
                self._bulk_torque(False)
                self.motor_bus.disconnect()
            except Exception:
                pass
        self.motor_bus = None
        self.is_connected = False
        self.torque_enabled = False

    # -- internals ---------------------------------------------------------
    def _bulk_torque(self, on: bool) -> bool:
        if self.motor_bus is None:
            return False
        value = 1 if on else 0
        ok = True
        for name in self._motor_names:
            try:
                self.motor_bus.write("Torque_Enable", name, value, normalize=False)
                # region agent log
                self._debug_log(
                    "H1",
                    "sender/writer.py:_bulk_torque",
                    "torque_write_ok",
                    {"motor": name, "value": value, "on": bool(on)},
                )
                # endregion
            except Exception as exc:
                print(f"[ERR] Torque_Enable {name}={value}: {exc}")
                # region agent log
                self._debug_log(
                    "H1",
                    "sender/writer.py:_bulk_torque",
                    "torque_write_fail",
                    {
                        "motor": name,
                        "value": value,
                        "on": bool(on),
                        "error": f"{type(exc).__name__}: {exc}",
                    },
                )
                # endregion
                ok = False
        return ok


__all__ = [
    "BaseArmWriter",
    "MockArmWriter",
    "FollowerArmWriter",
]
