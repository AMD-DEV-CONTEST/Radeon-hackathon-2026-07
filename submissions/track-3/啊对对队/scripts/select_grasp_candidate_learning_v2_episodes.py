#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from parcel_sorter.config import load_config
from parcel_sorter.grasp_planning import (
    box_requires_geometry_aware_grasp_planning,
)
from parcel_sorter.randomization import DomainRandomizer


PROFILE_NAMESPACES = (
    ("medium_carton", 8_410_000),
    ("shoe_box_proxy", 8_510_000),
    ("large_narrow_carton", 8_710_000),
    ("near_limit_box", 8_810_000),
)
SCAN_EPISODES_PER_PROFILE = 256
TRAIN_EPISODES_PER_PROFILE = 8
DEVELOPMENT_EPISODES_PER_PROFILE = 4
HOLDOUT_EPISODES_PER_PROFILE = 4
HAND_CLEARANCE_M = 0.105
MIN_VERTICAL_SIDE_OVERLAP_M = 0.020


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Select fresh v2 grasp-learning episodes using only the frozen "
            "geometry-planning scope predicate. No scene is constructed."
        )
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=PROJECT_ROOT / "configs/catalog_v2.toml",
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def select_episodes(config_path: Path) -> dict[str, Any]:
    config = load_config(config_path)
    randomizer = DomainRandomizer(
        config.randomization,
        config.seed,
        config.parcel_profiles,
    )
    required = (
        TRAIN_EPISODES_PER_PROFILE
        + DEVELOPMENT_EPISODES_PER_PROFILE
        + HOLDOUT_EPISODES_PER_PROFILE
    )
    profiles: dict[str, Any] = {}
    assignments = []
    for profile_id, namespace_start in PROFILE_NAMESPACES:
        eligible = []
        for episode in range(
            namespace_start,
            namespace_start + SCAN_EPISODES_PER_PROFILE,
        ):
            sample = randomizer.sample_profile(profile_id, episode)
            if box_requires_geometry_aware_grasp_planning(
                sample,
                hand_clearance_m=HAND_CLEARANCE_M,
                min_vertical_side_overlap_m=MIN_VERTICAL_SIDE_OVERLAP_M,
            ):
                eligible.append(
                    {
                        "episode": episode,
                        "sample": asdict(sample),
                    }
                )
            if len(eligible) == required:
                break
        if len(eligible) != required:
            raise RuntimeError(
                f"{profile_id} produced {len(eligible)} eligible episodes; "
                f"required {required}"
            )
        split_rows = {
            "train": eligible[:TRAIN_EPISODES_PER_PROFILE],
            "development": eligible[
                TRAIN_EPISODES_PER_PROFILE:
                TRAIN_EPISODES_PER_PROFILE + DEVELOPMENT_EPISODES_PER_PROFILE
            ],
            "holdout": eligible[-HOLDOUT_EPISODES_PER_PROFILE:],
        }
        profiles[profile_id] = {
            "namespace_start": namespace_start,
            "namespace_end_exclusive": (
                namespace_start + SCAN_EPISODES_PER_PROFILE
            ),
            "selected": split_rows,
        }
        for split, rows in split_rows.items():
            assignments.extend(
                {
                    "split": split,
                    "profile_id": profile_id,
                    "episode": int(row["episode"]),
                }
                for row in rows
            )
    return {
        "schema_version": "1.0",
        "status": "selected_without_physics_execution",
        "selection_contract": {
            "profile_namespaces": [
                {"profile_id": profile, "start": start}
                for profile, start in PROFILE_NAMESPACES
            ],
            "scan_episodes_per_profile": SCAN_EPISODES_PER_PROFILE,
            "selection_order": "ascending episode ID",
            "predicate": (
                "box_requires_geometry_aware_grasp_planning with "
                "hand_clearance_m=0.105 and min_vertical_side_overlap_m=0.020"
            ),
            "outcome_fields_read": [],
            "scene_constructed": False,
            "robot_action_executed": False,
            "train_per_profile": TRAIN_EPISODES_PER_PROFILE,
            "development_per_profile": DEVELOPMENT_EPISODES_PER_PROFILE,
            "holdout_per_profile": HOLDOUT_EPISODES_PER_PROFILE,
        },
        "config": {
            "path": str(config_path.resolve()),
            "sha256": _sha256(config_path),
        },
        "selector": {
            "path": str(Path(__file__).resolve()),
            "sha256": _sha256(Path(__file__).resolve()),
        },
        "profiles": profiles,
        "assignments": sorted(
            assignments,
            key=lambda row: (
                str(row["split"]),
                str(row["profile_id"]),
                int(row["episode"]),
            ),
        ),
    }


def main() -> int:
    args = parse_args()
    payload = select_episodes(args.config.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    counts = {
        split: sum(row["split"] == split for row in payload["assignments"])
        for split in ("train", "development", "holdout")
    }
    print(
        json.dumps(
            {
                "output": str(args.output),
                "status": payload["status"],
                "counts": counts,
            },
            allow_nan=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
