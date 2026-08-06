"""One-shot read of reBot Arm 102 leader joint angles (degrees) for alignment preflight."""
from __future__ import annotations

import argparse
import json
import sys

JOINT_IDS = {
    "shoulder_pan": 0,
    "shoulder_lift": 1,
    "elbow_flex": 2,
    "wrist_flex": 3,
    "wrist_yaw": 4,
    "wrist_roll": 5,
    "gripper": 6,
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", required=True)
    parser.add_argument("--id", required=True)
    args = parser.parse_args()

    try:
        from motorbridge_smart_servo import FashionStarServo
    except ImportError as exc:
        print(json.dumps({"ok": False, "error": f"motorbridge_smart_servo not installed: {exc}"}))
        return 2

    bus = FashionStarServo(args.port, baudrate=1_000_000)
    try:
        ids = list(JOINT_IDS.values())
        result = bus.sync_monitor(ids)
        id_to_name = {v: k for k, v in JOINT_IDS.items()}
        joints: dict[str, float] = {}
        for motor_id, monitor in result.items():
            name = id_to_name.get(motor_id)
            if name is None or monitor is None:
                continue
            joints[name] = float(monitor.angle_deg)
        if len(joints) < 4:
            print(json.dumps({"ok": False, "error": "主臂读数不完整，检查 USB 连接"}))
            return 1
        print(json.dumps({"ok": True, "joints_deg": joints, "leader_id": args.id}))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1
    finally:
        try:
            bus.close()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
