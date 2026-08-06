#!/usr/bin/env python3
"""Measure the active MuJoCo workspace without modifying the MJCF.

The result is a conservative axis-aligned XY box around the robot and task
geometries.  Large world/floor geoms are excluded; the shell exporter applies
the requested safety margin afterward.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import mujoco
import numpy as np


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", default="DishwasherLoadPlates")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-geom-radius", type=float, default=3.0)
    parser.add_argument(
        "--bigym-dir",
        type=Path,
        default=Path(os.environ["BIGYM_DIR"]) if os.environ.get("BIGYM_DIR") else None,
        help="Patched BiGym checkout; defaults to the BIGYM_DIR environment variable.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.bigym_dir is None:
        raise SystemExit("set BIGYM_DIR or pass --bigym-dir")
    replay_dir = args.bigym_dir.expanduser().resolve() / "d" / "replay_generation"
    if not (replay_dir / "env_utils.py").is_file():
        raise SystemExit(f"patched BiGym replay helpers not found: {replay_dir}")
    sys.path.insert(0, str(replay_dir))
    from env_utils import build_env  # noqa: PLC0415

    env = build_env(args.task, with_cameras=False)
    try:
        env.reset(seed=20260727)
        model = env.action_mode._mojo.model
        data = env.action_mode._mojo.data
        mujoco.mj_forward(model, data)
        selected: list[int] = []
        selected_names: list[str] = []
        for geom_id in range(model.ngeom):
            name = (
                mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, geom_id)
                or f"geom-{geom_id}"
            )
            radius = float(model.geom_rbound[geom_id])
            if name == "floor" or not np.isfinite(radius):
                continue
            if radius <= 0.0 or radius > args.max_geom_radius:
                continue
            selected.append(geom_id)
            selected_names.append(name)
        if not selected:
            raise RuntimeError("no finite task geoms were selected")

        centers = np.asarray(data.geom_xpos[selected], dtype=np.float64)
        radii = np.asarray(model.geom_rbound[selected], dtype=np.float64)
        lower = (centers - radii[:, None]).min(axis=0)
        upper = (centers + radii[:, None]).max(axis=0)
        if not np.isfinite(lower).all() or not np.isfinite(upper).all():
            raise RuntimeError("workspace bounds are non-finite")
        width, depth = upper[:2] - lower[:2]
        if min(width, depth) <= 0.25 or max(width, depth) > 12.0:
            raise RuntimeError(
                f"implausible workspace dimensions: {width:.3f} x {depth:.3f}"
            )
        payload = {
            "schema_version": 1,
            "task": args.task,
            "method": "union of finite non-floor MuJoCo geom bounding spheres",
            "center_xy_m": ((lower[:2] + upper[:2]) / 2.0).tolist(),
            "width_m": float(width),
            "depth_m": float(depth),
            "clear_height_m": float(max(2.4, upper[2] - min(0.0, lower[2]))),
            "raw_min_m": lower.tolist(),
            "raw_max_m": upper.tolist(),
            "selected_geom_count": len(selected),
            "selected_geom_names": selected_names,
            "excluded_world_radius_above_m": args.max_geom_radius,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(payload, ensure_ascii=False))
    finally:
        env.close()


if __name__ == "__main__":
    main()
