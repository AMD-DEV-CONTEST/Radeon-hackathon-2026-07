#!/usr/bin/env python3
"""Force-sync a lerobot calibration JSON file back into the motor EEPROM.

Why this exists:
    `SOLeader.connect()` / `SOFollower.connect()` call `bus.is_calibrated`,
    which compares the JSON on disk to whatever's in the motor's EEPROM.
    If they disagree even by one tick (e.g. an earlier auto-calibration run
    overwrote the EEPROM), stock lerobot treats the arm as uncalibrated and
    drops into an `input()` prompt — which, under a subprocess pipe, loses
    its stdin connection and the CLI will try to RE-run record_ranges_of_motion,
    which then dies with "min==max" because no one is moving the arm.

    Running this script once flushes JSON → EEPROM so `is_calibrated` flips
    back to True and subsequent teleop starts use the cached calibration.

Usage:
    source apps/realtime/.venv/bin/activate
    python scripts/sync_calibration_to_eeprom.py leader /dev/ttyACM1 ethan_leader
    python scripts/sync_calibration_to_eeprom.py follower /dev/ttyACM0 ethan_follower

Arguments:
    device_type   'leader' | 'follower'
    serial_port   e.g. /dev/ttyACM1
    device_id     Calibration file stem (without .json) — the script expects
                  ~/.cache/huggingface/lerobot/calibration/
                    teleoperators/so101_leader/<device_id>.json  (for leader)
                    robots/so101_follower/<device_id>.json       (for follower)

Safety:
    disable_torque() is called before EEPROM writes (Homing_Offset write is a
    no-op on motion ONLY when torque is off — otherwise the motor instantly
    tries to lurch to a new reference frame). If torque is left on from a
    previous crash, we still disable it first. You may hear the motors go
    limp as this runs — that's expected and correct.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


CALIB_ROOT = Path.home() / ".cache" / "huggingface" / "lerobot" / "calibration"


def load_json_calibration(device_type: str, device_id: str):
    """Load the JSON and convert to dict[str, MotorCalibration]."""
    from lerobot.motors import MotorCalibration  # type: ignore

    if device_type == "leader":
        folder = CALIB_ROOT / "teleoperators" / "so101_leader"
    elif device_type == "follower":
        folder = CALIB_ROOT / "robots" / "so101_follower"
    else:
        raise SystemExit(f"device_type must be 'leader' or 'follower', got {device_type!r}")

    path = folder / f"{device_id}.json"
    if not path.is_file():
        raise SystemExit(f"calibration file not found: {path}")

    with path.open("r") as fh:
        raw = json.load(fh)

    out = {}
    for motor, entry in raw.items():
        out[motor] = MotorCalibration(
            id=int(entry["id"]),
            drive_mode=int(entry.get("drive_mode", 0)),
            homing_offset=int(entry["homing_offset"]),
            range_min=int(entry["range_min"]),
            range_max=int(entry["range_max"]),
        )
    return path, out


def build_motors():
    """Same motor layout SOLeader/SOFollower use internally."""
    from lerobot.motors import Motor, MotorNormMode  # type: ignore

    # norm_mode doesn't matter for write_calibration — it only affects
    # normalize=True read/write paths, which this script does not touch.
    # But it must match SOLeader/SOFollower so the bus accepts the motors
    # dict layout without complaining.
    return {
        "shoulder_pan":  Motor(1, "sts3215", MotorNormMode.RANGE_M100_100),
        "shoulder_lift": Motor(2, "sts3215", MotorNormMode.RANGE_M100_100),
        "elbow_flex":    Motor(3, "sts3215", MotorNormMode.RANGE_M100_100),
        "wrist_flex":    Motor(4, "sts3215", MotorNormMode.RANGE_M100_100),
        "wrist_roll":    Motor(5, "sts3215", MotorNormMode.RANGE_M100_100),
        "gripper":       Motor(6, "sts3215", MotorNormMode.RANGE_0_100),
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("device_type", choices=["leader", "follower"])
    p.add_argument("serial_port")
    p.add_argument("device_id")
    args = p.parse_args()

    from lerobot.motors.feetech import FeetechMotorsBus  # type: ignore

    json_path, calibration = load_json_calibration(args.device_type, args.device_id)
    print(f"Loaded {json_path} with {len(calibration)} motors")

    bus = FeetechMotorsBus(
        port=args.serial_port,
        motors=build_motors(),
        calibration=calibration,
    )

    print(f"Opening {args.serial_port} ...")
    bus.connect()

    try:
        before = bus.is_calibrated
        print(f"is_calibrated BEFORE sync: {before}")

        print("Disabling torque (arm will go limp — that is expected) ...")
        bus.disable_torque()

        print("Writing calibration to motor EEPROM ...")
        bus.write_calibration(calibration)

        after = bus.is_calibrated
        print(f"is_calibrated AFTER  sync: {after}")

        if after:
            print("\nSUCCESS — subsequent `lerobot-teleoperate` calls will use")
            print("the cached calibration and will NOT drop into record_ranges_of_motion.")
        else:
            print("\nEEPROM readback still disagrees with the JSON. This usually")
            print("means the motor IDs in your JSON file don't match the hardware")
            print("(e.g. you plugged in a different arm). Inspect read_calibration()")
            print("output to debug:")
            for motor, cal in bus.read_calibration().items():
                want = calibration.get(motor)
                print(f"  {motor}: EEPROM={cal} WANTED={want}")
            sys.exit(2)
    finally:
        try:
            bus.disconnect()
        except Exception:
            pass


if __name__ == "__main__":
    main()
