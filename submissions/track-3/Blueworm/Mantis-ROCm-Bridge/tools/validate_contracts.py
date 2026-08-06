#!/usr/bin/env python3
"""Validate the checked-in port and task contracts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mantis_rocm_bridge.contracts import (
    validate_amd_cloud_runtime_contract,
    validate_competition_resources_contract,
    load_json,
    validate_contract_pair,
    validate_scene_gate_contracts,
    validate_fixed_base_plan,
    validate_rocm_container_contract,
    validate_rim_support_overlay_plan,
    validate_training_seed_manifest,
)
from mantis_rocm_bridge.amd_persistence import (
    validate_persistence_contract,
    validate_runtime_against_persistence,
)


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=Path, default=ROOT / "configs/mantis-port-config.json")
    parser.add_argument("--task", type=Path, default=ROOT / "configs/task-pack-v1.json")
    parser.add_argument(
        "--source-task",
        type=Path,
        default=ROOT / "configs/source-task-stack-bowls-three.json",
    )
    parser.add_argument(
        "--control-resampling",
        type=Path,
        default=ROOT / "configs/control-resampling-v1.json",
    )
    parser.add_argument(
        "--camera-extrinsics",
        type=Path,
        default=ROOT / "configs/camera-extrinsics-v1.json",
    )
    parser.add_argument(
        "--bowl-asset-plan",
        type=Path,
        default=ROOT / "configs/bowl-asset-plan.json",
    )
    parser.add_argument(
        "--rocm-container",
        type=Path,
        default=ROOT / "configs/rocm-container-v1.json",
    )
    parser.add_argument(
        "--amd-cloud-runtime",
        type=Path,
        default=ROOT / "configs/amd-cloud-runtime-v3.json",
    )
    parser.add_argument(
        "--amd-persistence",
        type=Path,
        default=ROOT / "configs/amd-persistence-layout-v2.json",
    )
    parser.add_argument(
        "--competition-resources",
        type=Path,
        default=ROOT / "configs/competition-resources-v1.json",
    )
    parser.add_argument(
        "--training-seeds",
        type=Path,
        default=ROOT / "configs/training-seeds-v1.json",
    )
    args = parser.parse_args()
    blockers = validate_contract_pair(
        load_json(args.port),
        load_json(args.task),
        load_json(args.source_task),
    )
    port = load_json(args.port)
    validate_scene_gate_contracts(
        port,
        load_json(args.control_resampling),
        load_json(args.camera_extrinsics),
        load_json(args.bowl_asset_plan),
    )
    asset_plan_path = ROOT / port["assets"]["fixed_base_plan"]
    validate_fixed_base_plan(load_json(asset_plan_path), port)
    overlay_plan_path = ROOT / port["assets"]["rim_support_overlay_plan"]
    validate_rim_support_overlay_plan(load_json(overlay_plan_path), port)
    validate_rocm_container_contract(load_json(args.rocm_container))
    amd_runtime = load_json(args.amd_cloud_runtime)
    amd_persistence = load_json(args.amd_persistence)
    validate_amd_cloud_runtime_contract(amd_runtime)
    validate_persistence_contract(amd_persistence)
    validate_runtime_against_persistence(amd_runtime, amd_persistence)
    validate_competition_resources_contract(load_json(args.competition_resources))
    task = load_json(args.task)
    validate_training_seed_manifest(load_json(args.training_seeds), task)
    print(
        json.dumps(
            {
                "valid": True,
                "scene_gate_contracts_valid": True,
                "rocm_container_contract_valid": True,
                "amd_cloud_runtime_contract_valid": True,
                "amd_persistence_contract_valid": True,
                "amd_runtime_persistence_consistent": True,
                "competition_resources_contract_valid": True,
                "training_seed_manifest_valid": True,
                "status": "provisional_blocked" if blockers else "ready",
                "blockers": blockers,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
