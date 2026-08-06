#!/usr/bin/env python3
"""Diagnostic — print every EEPROM register on the follower that could
explain 'wrist_flex refuses to move'. Does NOT write anything.

Reads for all 6 motors (so we can compare wrist_flex against peers):
    Operating_Mode       — 0=position, 1=velocity, 3=PWM. Must be 0 for teleop.
    Torque_Enable        — should be 1 only while a teleop session holds us.
    Torque_Limit         — 0 => "motor refuses to apply any torque" => dead.
    Min/Max_Position_Limit — the clamp we saw in feetech.py.
    Homing_Offset        — just for cross-check against the JSON.
    Present_Position     — current raw tick.
    Goal_Position        — last commanded tick (0 after a cold boot).
    Present_Temperature  — >70C => motor throttles hard; seen on stuck motors.
    Hardware_Error_Status / Moving_Status — non-zero means the motor latched
                                            an error (overload, overheat, etc.)
                                            and will ignore Goal_Position
                                            until it's reset.

Usage:
    source apps/realtime/.venv/bin/activate
    python scripts/dump_wrist_flex_regs.py /dev/ttyACM0 ethan_follower
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

CALIB_ROOT = Path.home() / ".cache" / "huggingface" / "lerobot" / "calibration"


def load_calibration(device_type: str, device_id: str):
    from lerobot.motors import MotorCalibration  # type: ignore
    folder = (
        CALIB_ROOT / "teleoperators" / "so101_leader"
        if device_type == "leader"
        else CALIB_ROOT / "robots" / "so101_follower"
    )
    path = folder / f"{device_id}.json"
    if not path.is_file():
        raise SystemExit(f"calibration file not found: {path}")
    raw = json.load(path.open("r"))
    return {
        m: MotorCalibration(
            id=int(e["id"]),
            drive_mode=int(e.get("drive_mode", 0)),
            homing_offset=int(e["homing_offset"]),
            range_min=int(e["range_min"]),
            range_max=int(e["range_max"]),
        )
        for m, e in raw.items()
    }


def build_motors():
    from lerobot.motors import Motor, MotorNormMode  # type: ignore
    return {
        "shoulder_pan":  Motor(1, "sts3215", MotorNormMode.RANGE_M100_100),
        "shoulder_lift": Motor(2, "sts3215", MotorNormMode.RANGE_M100_100),
        "elbow_flex":    Motor(3, "sts3215", MotorNormMode.RANGE_M100_100),
        "wrist_flex":    Motor(4, "sts3215", MotorNormMode.RANGE_M100_100),
        "wrist_roll":    Motor(5, "sts3215", MotorNormMode.RANGE_M100_100),
        "gripper":       Motor(6, "sts3215", MotorNormMode.RANGE_0_100),
    }


# Registers we want to inspect. All safe reads (no side effects).
REGISTERS = [
    "Operating_Mode",
    "Torque_Enable",
    "Torque_Limit",
    "Min_Position_Limit",
    "Max_Position_Limit",
    "Homing_Offset",
    "Present_Position",
    "Goal_Position",
    "Present_Temperature",
    "Hardware_Error_Status",
    "Moving_Status",
]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("serial_port")
    p.add_argument("device_id")
    p.add_argument("--device-type", default="follower", choices=["leader", "follower"])
    args = p.parse_args()

    from lerobot.motors.feetech import FeetechMotorsBus  # type: ignore

    calibration = load_calibration(args.device_type, args.device_id)
    bus = FeetechMotorsBus(
        port=args.serial_port,
        motors=build_motors(),
        calibration=calibration,
    )
    bus.connect()
    try:
        motors = list(calibration.keys())
        print(f"\nRegister dump on {args.serial_port}  ({args.device_id})\n")

        header = f"  {'register':25s}  " + "  ".join(f"{m[:13]:>13s}" for m in motors)
        print(header)
        print("  " + "-" * (len(header) - 2))

        for reg in REGISTERS:
            values = {}
            for m in motors:
                try:
                    v = bus.read(reg, m, normalize=False)
                    values[m] = int(v)
                except Exception as exc:
                    values[m] = f"ERR:{type(exc).__name__}"
            row = f"  {reg:25s}  " + "  ".join(
                f"{str(values[m]):>13s}" for m in motors
            )
            print(row)

        print()
        print("Things to look for in the row for wrist_flex specifically:")
        print("  Operating_Mode         0  (anything else = joint won't track Goal_Position)")
        print("  Torque_Limit          1000 ish  (0 = 'zero torque output' = dead joint)")
        print("  Hardware_Error_Status  0  (non-zero = latched fault until reboot)")
        print("  Present_Temperature  < 60  (>70 => motor in thermal throttle)")
    finally:
        try:
            bus.disconnect()
        except Exception:
            pass


if __name__ == "__main__":
    main()
