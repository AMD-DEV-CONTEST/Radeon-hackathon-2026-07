#!/usr/bin/env python3
"""Export grasp_planner results (both frozen designs, every object in the 36-object
generalization pool + the 3 core fruits) to a single JSON the interactive viewer
(demo/grasp_planner_viz/index.html) loads at runtime.

This is a read-only export of the SAME plan_grasp_with_geometry(...) calls the real
controller makes when use_planner=True -- nothing here is a separate/approximate
code path, and no simulation runs (grasp planning is pure geometry, no physics).

Run from the repo root:
    uv run python franka_fruit_pick/codesign/export_grasp_planner_viz.py
"""
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(_ROOT.parent))

from grasp_planner import plan_grasp_with_geometry  # noqa: E402
from ycb_generalization_eval import GENERALIZATION_OBJECTS  # noqa: E402
from run_attribution import BASELINE_PARAMS, JOINT_BEST_PARAMS  # noqa: E402

OUT_PATH = _ROOT.parent.parent / "demo" / "grasp_planner_viz" / "grasp_planner_data.json"

# GENERALIZATION_OBJECTS already includes the 3 core fruits (013_apple's siblings
# 014_lemon/018_plum are not in that list since they're the *originally* solved
# objects, not held-out ones) -- add them explicitly so the viewer covers every
# object this project ever evaluated on, not just the generalization set.
ALL_OBJECTS = sorted(set(GENERALIZATION_OBJECTS) | {"014_lemon", "018_plum"})


def main():
    designs = {"baseline": BASELINE_PARAMS, "winner": JOINT_BEST_PARAMS}
    entries = []
    for obj in ALL_OBJECTS:
        for label, params in designs.items():
            try:
                g = plan_grasp_with_geometry(obj, params)
            except FileNotFoundError as e:
                print(f"skip {obj} ({label}): {e}")
                continue
            g["design"] = label
            g["aperture"] = params.aperture
            g["n_fingers_design"] = params.n_fingers
            entries.append(g)
            status = "OK" if g["feasible"] else "infeasible"
            print(f"[{label:8s}] {obj:25s} {status}")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps({"objects": ALL_OBJECTS, "entries": entries}, indent=1))
    print(f"wrote {OUT_PATH} ({len(entries)} entries, {OUT_PATH.stat().st_size / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()
