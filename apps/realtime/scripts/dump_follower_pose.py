#!/usr/bin/env python3
"""Quick diagnostic — read each follower motor's raw Present_Position and
compare against its calibrated [range_min, range_max] window.

Why this exists:
    When a joint starts outside its own calibrated window (e.g. because
    someone hand-moved the follower while torque was off, or a previous
    crash left it parked past a limit), lerobot-teleoperate writes to
    Min/Max_Position_Limit inside SOFollower.configure() and the motor
    kernel then REFUSES further Goal_Position writes on that joint ->
    "the joint is dead, nothing I do moves it". Meanwhile, enabling
    torque yanks the other joints in the kinematic chain -> "wrist jumped
    on start". Both symptoms come from this one cause.

Usage:
    source apps/realtime/.venv/bin/activate
    python scripts/dump_follower_pose.py /dev/ttyACM0 ethan_follower

Output columns:
    motor            Present_Position    range window         status
    --------------   ----------------    ------------------   -----------------
    wrist_flex       3510                [ 853 .. 3241]        OUT OF RANGE  ← troubling
    elbow_flex       1842                [ 933 .. 3161]        ok (mid)

Nothing is written to the motor. Torque state is NOT changed.
"""
from __future__ import annotations

import argparse
import json
import sys
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


def classify(present: int, lo: int, hi: int) -> str:
    span = hi - lo
    if span <= 0:
        return "?"
    if present < lo:
        return f"OUT OF RANGE (below min by {lo - present} ticks)"
    if present > hi:
        return f"OUT OF RANGE (above max by {present - hi} ticks)"
    pct = (present - lo) / span * 100
    if pct < 10:
        return f"ok (near min, {pct:4.1f}% of window)"
    if pct > 90:
        return f"ok (near max, {pct:4.1f}% of window)"
    return f"ok ({pct:4.1f}% of window)"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("serial_port", help="e.g. /dev/ttyACM0")
    p.add_argument("device_id", help="calibration file stem, e.g. ethan_follower")
    p.add_argument(
        "--device-type",
        default="follower",
        choices=["leader", "follower"],
        help="default: follower",
    )
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
        present = bus.sync_read("Present_Position", normalize=False)
        print(f"\nArm pose on {args.serial_port}  ({args.device_id}):\n")
        print(
            f"  {'motor':15s}  {'present':>8s}    {'range':>16s}    status"
        )
        print("  " + "-" * 78)
        any_out = False
        for name, cal in calibration.items():
            raw = int(present.get(name, -1))
            lo, hi = cal.range_min, cal.range_max
            status = classify(raw, lo, hi)
            print(
                f"  {name:15s}  {raw:>8d}    [{lo:5d}..{hi:5d}]    {status}"
            )
            if "OUT OF RANGE" in status:
                any_out = True
        print()
        if any_out:
            print(
                "One or more joints are physically outside their calibrated\n"
                "window. While in that state, lerobot's Min/Max_Position_Limit\n"
                "will clamp Goal_Position writes and the affected joint will\n"
                "appear dead during teleop.\n\n"
                "Fix: with torque OFF (the bus is already holding torque off\n"
                "after this script connects — you can hear them click loose),\n"
                "physically grab the joint and nudge it back INTO its window\n"
                "(anywhere between min..max works; the middle is safest).\n"
                "Then re-run this script to confirm, then start teleop again."
            )
            sys.exit(2)
        else:
            print("All joints are inside their calibrated windows — the "
                  "'dead wrist' symptom is NOT a range-limit issue. Tell me\n"
                  "and we'll dig deeper.")
    finally:
        try:
            bus.disconnect()
        except Exception:
            pass


if __name__ == "__main__":
    main()
