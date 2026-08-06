#!/usr/bin/env python3
"""Create non-overwriting markers around training and evaluation jobs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mantis_rocm_bridge.ops import begin_run, finish_run, get_run_status


def _object(value: str) -> dict:
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise argparse.ArgumentTypeError("JSON value must be an object")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("run_id")
    parser.add_argument("action", choices=["status", "begin", "complete", "fail", "stop"])
    parser.add_argument("--details", type=_object, default={})
    args = parser.parse_args()
    if args.action == "status":
        print(get_run_status(args.root, args.run_id))
        return 0
    if args.action == "begin":
        marker = begin_run(args.root, args.run_id, args.details)
    else:
        state = {"complete": "completed", "fail": "failed", "stop": "stopped"}[args.action]
        marker = finish_run(args.root, args.run_id, state, args.details)
    print(marker)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

