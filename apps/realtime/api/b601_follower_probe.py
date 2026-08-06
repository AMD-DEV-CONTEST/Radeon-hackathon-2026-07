"""Read B601 follower joints in one motorbridge session (radians, URDF keys joint1..7).

READ-ONLY: passive get_state only. Never ensure_mode / enable / write-param —
those change motor registers and have caused field incidents when agents improvised.
"""
from __future__ import annotations

import argparse
import json
import sys

MODELS = {
    1: "rs-06",
    2: "rs-06",
    3: "rs-06",
    4: "rs-00",
    5: "rs-00",
    6: "rs-00",
    7: "rs-00",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--channel", default="can0")
    args = parser.parse_args()

    try:
        from motorbridge import Controller
    except ImportError as exc:
        print(json.dumps({"ok": False, "error": f"motorbridge not installed: {exc}"}))
        return 2

    ctrl = Controller(channel=args.channel)
    motors: list = []
    joints: dict[str, float] = {}
    try:
        for mid, model in MODELS.items():
            motors.append((f"joint{mid}", ctrl.add_robstride_motor(mid, 0xFD, model)))
        for key, motor in motors:
            try:
                state = motor.get_state()
                if state is not None:
                    joints[key] = float(state.pos)
            except Exception:
                pass
    finally:
        for _, motor in motors:
            try:
                motor.close()
            except Exception:
                pass
        try:
            ctrl.close()
        except Exception:
            pass

    if len(joints) < 4:
        print(json.dumps({"ok": False, "error": "从臂读数不完整（只读探测）", "joints_rad": joints}))
        return 1
    print(json.dumps({"ok": True, "joints_rad": joints}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
