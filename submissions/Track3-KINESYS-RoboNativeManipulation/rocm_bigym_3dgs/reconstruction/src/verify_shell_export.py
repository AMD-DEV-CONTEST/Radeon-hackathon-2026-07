#!/usr/bin/env python3
"""Fail-closed structural acceptance for an exported visual shell."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("shell_dir", type=Path)
    parser.add_argument("--allow-pending-visual-review", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    profile_path = args.shell_dir / "scene-shell-profile.json"
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    required_layers = {
        "walls_fixed_kitchen.ply",
        "floor_perimeter.ply",
        "ceiling_lights.ply",
        "gaussians_shell.ply",
    }
    if set(profile.get("layers", {})) != required_layers:
        raise RuntimeError("shell profile does not contain exactly four expected layers")
    for name in required_layers:
        path = args.shell_dir / name
        item = profile["layers"][name]
        if not path.is_file() or path.stat().st_size != int(item["bytes"]):
            raise RuntimeError(f"missing or size-mismatched shell layer: {name}")
        if int(item["gaussians"]) <= 0:
            raise RuntimeError(f"empty shell layer: {name}")
    physics = profile.get("background_physics", {})
    observed = (
        physics.get("mujoco_body_count"),
        physics.get("mujoco_geom_count"),
        physics.get("collision_count"),
    )
    if observed != (0, 0, 0):
        raise RuntimeError(f"visual shell leaked into physics: {observed}")
    if profile["central_exclusion"]["visible_gaussian_violations"] != 0:
        raise RuntimeError("central workspace is not empty")
    if profile.get("status") != "passed" and not args.allow_pending_visual_review:
        raise RuntimeError(f"shell is not formally passed: {profile.get('status')}")
    print("SHELL_EXPORT_OK")


if __name__ == "__main__":
    main()
