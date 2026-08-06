"""Load / inspect a LeRobot SO-101 dataset, or point at how to generate one.

Thin helpers over the LeRobot 0.6.x dataset API:

  * ``load_dataset(repo_id, root)``   -> a ``LeRobotDataset`` for training/inspection.
  * ``dataset_summary(repo_id, root)`` -> a dict of shapes/fps/episode counts.
  * ``validate_dataset(...)``          -> assert the feature layout matches what
    the SmolVLA fine-tune + eval expect (state/action 6-D, world+wrist images).

If no dataset exists yet, generate synthetic demonstrations with
``scripts/record_dataset.py`` (scripted SO-101 pick-place).

CLI:
    python dataset/lerobot_loader.py --repo-id so101/cube_pick --dataset-root datasets/cube_pick

NOTE: Requires ``lerobot``; run on the machine that has it installed.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from simulation import so101

EXPECTED_FEATURES = (
    "observation.state",
    "action",
    "observation.images.world",
    "observation.images.wrist",
)


def load_dataset(repo_id: str, root: str | None = None):
    """Return a LeRobotDataset (episodes lazily read on access)."""
    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    return LeRobotDataset(repo_id, root=root)


def _metadata(repo_id: str, root: str | None):
    from lerobot.datasets.lerobot_dataset import LeRobotDatasetMetadata

    return LeRobotDatasetMetadata(repo_id, root=root)


def dataset_summary(repo_id: str, root: str | None = None) -> dict:
    """Return fps, feature shapes and episode/frame counts without reading frames."""
    meta = _metadata(repo_id, root)
    features = {k: v.get("shape") for k, v in meta.features.items()}
    return {
        "repo_id": repo_id,
        "fps": meta.fps,
        "num_episodes": getattr(meta, "total_episodes", None),
        "num_frames": getattr(meta, "total_frames", None),
        "features": features,
        "image_keys": [k for k in meta.features if k.startswith("observation.images")],
    }


def validate_dataset(repo_id: str, root: str | None = None) -> list[str]:
    """Check the dataset matches the SO-101 VLA layout. Returns a list of problems."""
    meta = _metadata(repo_id, root)
    problems: list[str] = []
    for key in EXPECTED_FEATURES:
        if key not in meta.features:
            problems.append(f"missing feature {key!r}")
    for vec_key in ("observation.state", "action"):
        if vec_key in meta.features:
            shape = tuple(meta.features[vec_key]["shape"])
            if shape != (so101.N_DOF,):
                problems.append(f"{vec_key} shape {shape} != ({so101.N_DOF},)")
    return problems


def main() -> None:
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Inspect / validate a LeRobot SO-101 dataset.")
    parser.add_argument("--repo-id", required=True)
    parser.add_argument("--dataset-root", default=None)
    parser.add_argument("--validate", action="store_true", help="Also run the layout check.")
    args = parser.parse_args()

    summary = dataset_summary(args.repo_id, args.dataset_root)
    print(json.dumps(summary, indent=2, default=str))

    if args.validate:
        problems = validate_dataset(args.repo_id, args.dataset_root)
        if problems:
            print("[validate] PROBLEMS:")
            for p in problems:
                print(f"  - {p}")
            raise SystemExit(1)
        print("[validate] OK: dataset matches the SO-101 VLA layout.")


if __name__ == "__main__":
    main()
