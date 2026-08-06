"""Run the fixed-room learned one-lap, four-object TidyBot mission."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("MUJOCO_GL", "egl")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from realtime_cleanup.tidybot_full_runtime import (  # noqa: E402
    DEFAULT_ARM_DIRECTORY,
    DEFAULT_DETECTOR,
    DEFAULT_OBJECT_ROUTE_DIRECTORY,
    DEFAULT_OUTPUT,
    DEFAULT_ROUTE_CHECKPOINT,
    run_full_mission,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--route-checkpoint", type=Path, default=DEFAULT_ROUTE_CHECKPOINT)
    parser.add_argument("--arm-directory", type=Path, default=DEFAULT_ARM_DIRECTORY)
    parser.add_argument(
        "--object-route-directory",
        type=Path,
        default=DEFAULT_OBJECT_ROUTE_DIRECTORY,
    )
    parser.add_argument("--detector-weights", type=Path, default=DEFAULT_DETECTOR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--device", type=int, default=0)
    parser.add_argument("--control-hz", type=float, default=20.0)
    parser.add_argument("--basket-threshold", type=float, default=0.008)
    parser.add_argument("--print-full-result", action="store_true")
    args = parser.parse_args()
    result = run_full_mission(
        route_checkpoint=args.route_checkpoint,
        arm_directory=args.arm_directory,
        object_route_directory=args.object_route_directory,
        detector_weights=args.detector_weights,
        output=args.output,
        device_index=args.device,
        control_hz=args.control_hz,
        basket_threshold=args.basket_threshold,
    )
    printable = (
        result
        if args.print_full_result
        else {
            "success": result["success"],
            "failure": result["failure"],
            "output": str(args.output),
            "control_steps": result["control_steps"],
            "video_frames": result["video_frames"],
            "object_results": [
                {
                    "object_name": item["object_name"],
                    "sensor_verified": item["manipulation"]["sensor_verified"],
                    "stable_deposit": item["manipulation"][
                        "evaluation_truth_stable_deposit"
                    ],
                }
                for item in result["object_results"]
            ],
        }
    )
    print(
        json.dumps(
            printable,
            indent=2,
            allow_nan=False,
        )
    )


if __name__ == "__main__":
    main()
