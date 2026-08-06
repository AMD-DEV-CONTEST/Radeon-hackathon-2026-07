#!/usr/bin/env python3
"""Live-probe follower wrist_flex while teleop is running.

You CAN'T just open /dev/ttyACM0 from another process while lerobot-
teleoperate owns it — the bus is half-duplex RS-485 and we'd corrupt the
CLI's sync_read/sync_write frames. So this script assumes teleop was
already STOPPED (so the port is free), reads a single snapshot, prints,
exits. Run it IMMEDIATELY after you hit "stop" in the wizard, before
anything else can touch the port.

What you get:
    wrist_flex row with Present_Position, Goal_Position, the delta, and
    the raw range limits. If present is pinned at max and goal also at
    max, we've hit the configured ceiling (either JSON range_max or
    physical stop). If present is way past max, the motor crashed into
    a mechanical hard stop. If goal is low and present is high, torque
    isn't actually getting applied.

Usage:
    source apps/realtime/.venv/bin/activate
    python scripts/tap_wrist_during_teleop.py /dev/ttyACM0 ethan_follower
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

CALIB_ROOT = Path.home() / ".cache" / "huggingface" / "lerobot" / "calibration"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("serial_port")
    p.add_argument("device_id")
    args = p.parse_args()

    from lerobot.motors import Motor, MotorNormMode, MotorCalibration  # type: ignore
    from lerobot.motors.feetech import FeetechMotorsBus  # type: ignore

    cal_path = CALIB_ROOT / "robots" / "so101_follower" / f"{args.device_id}.json"
    raw = json.load(cal_path.open())
    calibration = {
        name: MotorCalibration(
            id=int(e["id"]),
            drive_mode=int(e.get("drive_mode", 0)),
            homing_offset=int(e["homing_offset"]),
            range_min=int(e["range_min"]),
            range_max=int(e["range_max"]),
        )
        for name, e in raw.items()
    }

    motors = {
        "shoulder_pan":  Motor(1, "sts3215", MotorNormMode.RANGE_M100_100),
        "shoulder_lift": Motor(2, "sts3215", MotorNormMode.RANGE_M100_100),
        "elbow_flex":    Motor(3, "sts3215", MotorNormMode.RANGE_M100_100),
        "wrist_flex":    Motor(4, "sts3215", MotorNormMode.RANGE_M100_100),
        "wrist_roll":    Motor(5, "sts3215", MotorNormMode.RANGE_M100_100),
        "gripper":       Motor(6, "sts3215", MotorNormMode.RANGE_0_100),
    }
    bus = FeetechMotorsBus(port=args.serial_port, motors=motors, calibration=calibration)
    bus.connect()
    try:
        # One-shot snapshot. Read raw so we see the motor ticks directly.
        wf = "wrist_flex"
        present = bus.read("Present_Position", wf, normalize=False)
        goal = bus.read("Goal_Position", wf, normalize=False)
        torque = bus.read("Torque_Enable", wf, normalize=False)
        op_mode = bus.read("Operating_Mode", wf, normalize=False)
        min_limit = bus.read("Min_Position_Limit", wf, normalize=False)
        max_limit = bus.read("Max_Position_Limit", wf, normalize=False)
        homing = bus.read("Homing_Offset", wf, normalize=False)

        print(f"\n=== wrist_flex snapshot on {args.serial_port} ({args.device_id}) ===\n")
        print(f"  Torque_Enable      : {torque}  {'(torque ON)' if torque else '(torque OFF)'}")
        print(f"  Operating_Mode     : {op_mode} {'(position)' if op_mode == 0 else '(NON-POSITION — bad!)'}")
        print(f"  Present_Position   : {present}")
        print(f"  Goal_Position      : {goal}")
        print(f"  Delta (P - G)      : {present - goal}")
        print(f"  Min_Position_Limit : {min_limit}")
        print(f"  Max_Position_Limit : {max_limit}")
        print(f"  Homing_Offset      : {homing}")
        print()
        print(f"  JSON range_min     : {calibration[wf].range_min}")
        print(f"  JSON range_max     : {calibration[wf].range_max}")
        print(f"  JSON homing_offset : {calibration[wf].homing_offset}")
        print()

        if torque and abs(present - goal) > 200:
            print("  DIAGNOSIS: torque is on, large Present-Goal gap — motor is")
            print("  being asked to move but physically can't (mechanical stop,")
            print("  overload, or torque_limit=0).")
        elif torque and present >= max_limit - 20:
            print("  DIAGNOSIS: wrist is pinned at Max_Position_Limit. Goal is")
            print("  at or above the ceiling — this is your 'stuck at highest'.")
        elif not torque:
            print("  Torque is OFF. This is either the expected state AFTER stop,")
            print("  or teleop never actually got to write_torque_enable. Check")
            print("  the realtime log for an error between 'connected' and the ")
            print("  first tick.")
    finally:
        try:
            bus.disconnect()
        except Exception:
            pass


if __name__ == "__main__":
    main()
