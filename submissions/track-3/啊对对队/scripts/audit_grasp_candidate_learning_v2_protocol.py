#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys
import tomllib
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from parcel_sorter.grasp_scoring import (
    load_grasp_collection_activation_policy,
    load_grasp_split_protocol,
    sha256_file,
)
from scripts.select_grasp_candidate_learning_v2_episodes import select_episodes


EXPECTED_COUNTS = {"train": 32, "development": 16, "holdout": 16}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Audit the frozen v2 split against its hash-bound, physics-free "
            "episode selection evidence."
        )
    )
    parser.add_argument(
        "--protocol",
        type=Path,
        default=PROJECT_ROOT / "configs/grasp_candidate_learning_v2.toml",
    )
    parser.add_argument(
        "--selection",
        type=Path,
        default=(
            PROJECT_ROOT
            / "evidence/training/grasp-candidate-learning-v2-episode-selection.json"
        ),
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=PROJECT_ROOT / "configs/catalog_v2.toml",
    )
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def audit_protocol(
    protocol_path: Path,
    selection_path: Path,
    config_path: Path,
) -> dict[str, Any]:
    protocol_path = protocol_path.resolve()
    selection_path = selection_path.resolve()
    config_path = config_path.resolve()
    with protocol_path.open("rb") as stream:
        protocol = tomllib.load(stream)
    selection = json.loads(selection_path.read_text(encoding="utf-8"))

    selection_contract = selection.get("selection_contract", {})
    _require(
        selection.get("status") == "selected_without_physics_execution",
        "selection evidence has an unexpected status",
    )
    _require(
        selection_contract.get("outcome_fields_read") == [],
        "selection evidence records task outcome access",
    )
    _require(
        selection_contract.get("scene_constructed") is False,
        "selection evidence records scene construction",
    )
    _require(
        selection_contract.get("robot_action_executed") is False,
        "selection evidence records robot execution",
    )

    frozen_selection = protocol.get("selection", {})
    actual_selection_sha256 = sha256_file(selection_path)
    actual_config_sha256 = sha256_file(config_path)
    selector_path = PROJECT_ROOT / "scripts/select_grasp_candidate_learning_v2_episodes.py"
    actual_selector_sha256 = sha256_file(selector_path)
    _require(
        frozen_selection.get("evidence_sha256") == actual_selection_sha256,
        "selection evidence SHA-256 does not match the frozen protocol",
    )
    _require(
        frozen_selection.get("config_sha256") == actual_config_sha256,
        "catalog config SHA-256 does not match the frozen protocol",
    )
    _require(
        frozen_selection.get("selector_sha256") == actual_selector_sha256,
        "selector SHA-256 does not match the frozen protocol",
    )
    _require(
        selection.get("config", {}).get("sha256") == actual_config_sha256,
        "selection evidence is bound to a different catalog config",
    )
    _require(
        selection.get("selector", {}).get("sha256") == actual_selector_sha256,
        "selection evidence is bound to a different selector",
    )
    _require(
        frozen_selection.get("selection_without_physics") is True,
        "protocol does not freeze physics-free episode selection",
    )

    collection = protocol.get("collection", {})
    platform = protocol.get("platform", {})
    _require(
        load_grasp_collection_activation_policy(protocol_path) == "geometry-eligible",
        "v2 protocol must use geometry-eligible planning activation",
    )
    _require(
        collection.get("collision_checked_reset_enabled") is True,
        "collision-checked reset must remain enabled",
    )
    _require(
        collection.get("holdout_locked") is True,
        "holdout must remain locked before model selection",
    )
    _require(
        platform.get("backend") == "rocm"
        and platform.get("single_gpu") is True
        and platform.get("gpu_count") == 1,
        "protocol must remain a single-GPU ROCm experiment",
    )

    observed_assignments = {
        (str(row["profile_id"]), int(row["episode"])): str(row["split"])
        for row in selection.get("assignments", [])
    }
    _require(
        len(observed_assignments) == len(selection.get("assignments", [])),
        "selection evidence contains duplicate assignments",
    )
    frozen_assignments = load_grasp_split_protocol(protocol_path)
    _require(
        frozen_assignments == observed_assignments,
        "frozen TOML assignments differ from selection evidence",
    )
    counts = Counter(frozen_assignments.values())
    _require(dict(counts) == EXPECTED_COUNTS, "split counts differ from v2 protocol")

    recomputed = select_episodes(config_path)
    _require(
        recomputed["selection_contract"] == selection_contract,
        "selection contract is not reproducible",
    )
    _require(
        _canonical_json(recomputed["profiles"])
        == _canonical_json(selection.get("profiles")),
        "selected samples or geometry eligibility are not reproducible",
    )
    _require(
        recomputed["assignments"] == selection.get("assignments"),
        "selected episode IDs are not reproducible",
    )

    per_profile = Counter(profile for profile, _episode in frozen_assignments)
    _require(
        set(per_profile.values()) == {16} and len(per_profile) == 4,
        "each v2 profile must contain exactly 16 episodes",
    )
    return {
        "schema_version": "1.0",
        "status": "passed",
        "protocol": str(protocol_path),
        "protocol_sha256": sha256_file(protocol_path),
        "selection": str(selection_path),
        "selection_sha256": actual_selection_sha256,
        "selector_sha256": actual_selector_sha256,
        "config_sha256": actual_config_sha256,
        "planning_activation_policy": "geometry-eligible",
        "split_counts": {name: counts[name] for name in EXPECTED_COUNTS},
        "profile_counts": dict(sorted(per_profile.items())),
        "scene_constructed_during_selection": False,
        "robot_action_executed_during_selection": False,
        "holdout_locked": True,
    }


def main() -> int:
    args = parse_args()
    result = audit_protocol(args.protocol, args.selection, args.config)
    encoded = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
