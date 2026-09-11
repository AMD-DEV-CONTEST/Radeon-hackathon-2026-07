#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tomllib
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from parcel_sorter.controller_probe_confirmation import (
    CONFIRMATION_POLICY,
    CONFIRMATION_SPLIT,
)
from parcel_sorter.grasp_scoring import load_grasp_split_protocol, sha256_file


PROTOCOL_ID = "controller-faithful-probe-v5-independent-confirmation"


def _load_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        payload = tomllib.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"expected TOML table: {path}")
    return payload


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def audit_protocol(path: Path) -> dict[str, Any]:
    payload = _load_toml(path)
    metadata = payload["metadata"]
    population = payload["population"]
    collection = payload["collection"]
    implementation = payload["implementation"]
    gates = payload["gates"]
    errors: list[str] = []
    if str(metadata["protocol_id"]) != PROTOCOL_ID:
        errors.append("protocol_id")
    if str(population["split"]) != CONFIRMATION_SPLIT:
        errors.append("split_changed")
    if str(payload["fixed"]["policy"]) != CONFIRMATION_POLICY:
        errors.append("policy_changed")
    if str(collection["planning_activation_policy"]) != "all-boxes":
        errors.append("activation_policy_changed")
    if int(collection["max_candidates_per_episode"]) != 6 or int(collection["repeats"]) != 1:
        errors.append("collection_budget_changed")
    if bool(collection["v2_development_forbidden"]) is not True or bool(
        collection["v2_holdout_forbidden"]
    ) is not True:
        errors.append("old_population_not_forbidden")

    assignments = load_grasp_split_protocol(path)
    expected_groups = int(population["expected_groups"])
    episodes_per_profile = int(population["episodes_per_profile"])
    profile_ids = tuple(str(value) for value in population["profile_ids"])
    legacy = frozenset(str(value) for value in population["legacy_profiles"])
    unseen = frozenset(str(value) for value in population["unseen_profiles"])
    if len(assignments) != expected_groups or any(
        split != CONFIRMATION_SPLIT for split in assignments.values()
    ):
        errors.append("population_assignment_count")
    observed_profiles = {profile for profile, _ in assignments}
    if observed_profiles != set(profile_ids):
        errors.append("population_profiles")
    if legacy & unseen or legacy | unseen != observed_profiles or len(unseen) < 4:
        errors.append("novelty_partition")
    for profile in profile_ids:
        if sum(key[0] == profile for key in assignments) != episodes_per_profile:
            errors.append("profile_assignment_count")

    old_protocol = PROJECT_ROOT / str(population["old_population_protocol"])
    old_assignments = load_grasp_split_protocol(old_protocol)
    if set(assignments) & set(old_assignments):
        errors.append("old_population_overlap")

    catalog_path = PROJECT_ROOT / str(population["catalog"])
    if sha256_file(catalog_path) != str(population["catalog_sha256"]):
        errors.append("catalog_hash_mismatch")
    catalog = _load_toml(catalog_path)
    catalog_profiles = {
        str(row["profile_id"]): row for row in catalog.get("parcel_profiles", ())
    }
    for profile in profile_ids:
        row = catalog_profiles.get(profile)
        if row is None or str(row.get("shape")) != "box" or str(
            row.get("handling_class")
        ) != "parallel_jaw":
            errors.append("unsupported_population_profile")

    selection_path = PROJECT_ROOT / str(population["selection_evidence"])
    if sha256_file(selection_path) != str(population["selection_evidence_sha256"]):
        errors.append("selection_evidence_hash_mismatch")
    else:
        selection = _load_json(selection_path)
        selected = {
            (str(row["profile_id"]), int(row["episode"])): str(row["split"])
            for row in selection.get("assignments", ())
        }
        if selected != assignments:
            errors.append("selection_evidence_assignments")
        contract = selection.get("selection_contract", {})
        if contract.get("outcome_fields_read") != [] or bool(
            contract.get("scene_constructed")
        ) or bool(contract.get("robot_action_executed")):
            errors.append("selection_used_physics_or_outcomes")

    for key in (
        "module",
        "probe_extractor",
        "runner",
        "audit",
        "selector",
        "collection_runner",
        "collection_helpers",
        "labeler",
        "genesis_env",
        "grasp_planning",
        "expert_runner",
    ):
        declared = str(implementation[f"{key}_sha256"])
        implementation_path = PROJECT_ROOT / str(implementation[key])
        if declared == "PENDING_AFTER_FREEZE":
            errors.append(f"{key}_hash_not_frozen")
        elif sha256_file(implementation_path) != declared:
            errors.append(f"{key}_hash_mismatch")

    if int(gates["min_safety_abort_reductions"]) < 1:
        errors.append("safety_reduction_gate_weakened")
    if int(gates["min_profiles_with_safety_reduction"]) < 2:
        errors.append("benefit_concentration_gate_weakened")
    if not 0.0 < float(gates["safety_one_sided_alpha"]) <= 0.05:
        errors.append("statistical_alpha_weakened")
    return {
        "schema_version": "1.0",
        "status": "protocol_valid" if not errors else "protocol_invalid",
        "protocol": str(path.resolve()),
        "protocol_sha256": sha256_file(path),
        "protocol_id": str(metadata["protocol_id"]),
        "group_count": len(assignments),
        "profiles": sorted(observed_profiles),
        "legacy_profiles": sorted(legacy),
        "unseen_profiles": sorted(unseen),
        "old_population_overlap_count": len(set(assignments) & set(old_assignments)),
        "v2_development_forbidden": bool(collection["v2_development_forbidden"]),
        "v2_holdout_forbidden": bool(collection["v2_holdout_forbidden"]),
        "errors": list(dict.fromkeys(errors)),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit_protocol(args.protocol)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "errors": result["errors"]}))
    return 0 if result["status"] == "protocol_valid" else 1


if __name__ == "__main__":
    raise SystemExit(main())
