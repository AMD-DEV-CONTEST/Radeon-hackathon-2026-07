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
from parcel_sorter.randomization import DomainRandomizer


PROFILE_NAMESPACES = (
    ("medium_carton", 9_100_000),
    ("shoe_box_proxy", 9_200_000),
    ("large_narrow_carton", 9_300_000),
    ("near_limit_box", 9_400_000),
    ("small_carton", 9_500_000),
    ("flat_mailer", 9_600_000),
    ("long_carton", 9_700_000),
    ("electronics_box", 9_800_000),
)
EPISODES_PER_PROFILE = 10
SCAN_EPISODES_PER_PROFILE = 512
HAND_CLEARANCE_M = 0.105
MIN_VERTICAL_SIDE_OVERLAP_M = 0.020


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def select_population(config_path: Path) -> dict[str, Any]:
    config = load_config(config_path)
    randomizer = DomainRandomizer(config.randomization, config.seed, config.parcel_profiles)
    profiles: dict[str, Any] = {}
    assignments: list[dict[str, Any]] = []
    for profile_id, namespace_start in PROFILE_NAMESPACES:
        eligible = []
        for episode in range(namespace_start, namespace_start + SCAN_EPISODES_PER_PROFILE):
            sample = randomizer.sample_profile(profile_id, episode)
            if sample.shape == "box" and sample.handling_class == "parallel_jaw":
                eligible.append({"episode": episode, "sample": asdict(sample)})
            if len(eligible) == EPISODES_PER_PROFILE:
                break
        if len(eligible) != EPISODES_PER_PROFILE:
            raise RuntimeError(
                f"{profile_id} produced {len(eligible)} eligible episodes; "
                f"required {EPISODES_PER_PROFILE}"
            )
        selected = [int(row["episode"]) for row in eligible]
        profiles[profile_id] = {
            "namespace_start": namespace_start,
            "namespace_end_exclusive": namespace_start + SCAN_EPISODES_PER_PROFILE,
            "selected": eligible,
        }
        assignments.extend(
            {"split": "confirmation", "profile_id": profile_id, "episode": episode}
            for episode in selected
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
            "episodes_per_profile": EPISODES_PER_PROFILE,
            "selection_order": "ascending episode ID",
            "predicate": (
                "rigid box with parallel_jaw handling class; no outcome, "
                "scene, IK, collision, force, or controller state is read"
            ),
            "outcome_fields_read": [],
            "scene_constructed": False,
            "robot_action_executed": False,
        },
        "config": {"path": str(config_path.resolve()), "sha256": _sha256(config_path)},
        "selector": {
            "path": str(Path(__file__).resolve()),
            "sha256": _sha256(Path(__file__).resolve()),
        },
        "profiles": profiles,
        "assignments": sorted(assignments, key=lambda row: (str(row["profile_id"]), int(row["episode"]))),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "configs/catalog_v2.toml")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = select_population(args.config.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "status": result["status"], "groups": len(result["assignments"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
