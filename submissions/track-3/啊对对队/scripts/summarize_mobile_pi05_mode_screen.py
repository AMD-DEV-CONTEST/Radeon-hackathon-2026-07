#!/usr/bin/env python3
"""Gate a frozen, stage-complete PI0.5 routing and action screen."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
from typing import Any, Mapping

from parcel_sorter.mobile_pi05_action_fidelity import action_fidelity_gate
from parcel_sorter.mobile_pi05_contract import PI05_GRASP_MODES
from parcel_sorter.mobile_pi05_research_protocol import (
    PI05_TASK_STAGES,
    thresholds_for_stage,
    validate_action_thresholds,
    validate_stage_panel,
)


SCREEN_PROTOCOL = "pi05-stage-complete-action-screen-v3"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe", type=Path, action="append", required=True)
    parser.add_argument("--design", type=Path, required=True)
    parser.add_argument("--thresholds", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    probes = []
    for path in args.probe:
        payload = json.loads(path.read_text(encoding="utf-8"))
        probes.extend(payload["screens"] if "screens" in payload else [payload])
    design = json.loads(args.design.read_text(encoding="utf-8"))
    thresholds = json.loads(args.thresholds.read_text(encoding="utf-8"))
    try:
        payload = summarize_mode_screen(
            probes, design=design, thresholds=thresholds
        )
    except ValueError as exc:
        parser.error(str(exc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["status"] == "passed" else 2


def summarize_mode_screen(
    probes: list[dict[str, Any]],
    *,
    design: Mapping[str, Any],
    thresholds: Mapping[str, Any],
) -> dict[str, Any]:
    panel_audit = validate_stage_panel(design)
    role = str(panel_audit["role"])
    validate_action_thresholds(thresholds, panel_role=role)
    expected = {
        str(item["observation_id"]): item for item in design["observations"]
    }
    observed_ids = [str(probe.get("observation_id") or "") for probe in probes]
    if len(observed_ids) != len(set(observed_ids)):
        raise ValueError("probe panel contains duplicate observation ids")
    if set(observed_ids) != set(expected):
        missing = sorted(set(expected) - set(observed_ids))
        extra = sorted(set(observed_ids) - set(expected))
        raise ValueError(
            "probe panel does not match frozen design: "
            f"missing={missing}, extra={extra}"
        )

    routing_errors: list[str] = []
    action_errors: list[str] = []
    structural_errors: list[str] = []
    checkpoints = {str(probe.get("checkpoint") or "") for probe in probes}
    datasets = {str(probe.get("dataset") or "") for probe in probes}
    action_contracts = {str(probe.get("action_contract") or "") for probe in probes}
    seed_panels = {
        tuple(int(seed) for seed in probe.get("sample_seeds") or ())
        for probe in probes
    }
    if len(checkpoints) != 1 or "" in checkpoints:
        structural_errors.append("checkpoint_mismatch")
    if datasets != {str(design.get("dataset_root"))}:
        structural_errors.append("dataset_mismatch")
    if action_contracts != {"pi05_absolute_v1"}:
        structural_errors.append("absolute_action_contract_required")
    if len(seed_panels) != 1 or not next(iter(seed_panels), ()):
        structural_errors.append("sampling_seed_panel_mismatch")

    rows = []
    mode_counts: Counter[str] = Counter()
    stage_counts: Counter[str] = Counter()
    for probe in probes:
        observation_id = str(probe["observation_id"])
        planned = expected[observation_id]
        mode = str(planned["grasp_mode"])
        stage = str(planned["stage"])
        mode_counts[mode] += 1
        stage_counts[stage] += 1
        prefix = f"{mode}:{stage}:{observation_id}"
        metadata_requirements = {
            "dataset_index": probe.get("dataset_index") == planned["dataset_index"],
            "episode_index": probe.get("episode_index") == planned["episode_index"],
            "source_identity": probe.get("source_identity") == planned["source_identity"],
            "stage": probe.get("stage") == stage,
            "expected_mode": probe.get("expected_grasp_mode") == mode,
            "panel_role": probe.get("observation_panel_role") == role,
            "panel_sha256": probe.get("stage_panel_sha256") == design["panel_sha256"],
            "dataset_manifest_sha256": (
                probe.get("dataset_manifest_sha256")
                == design["dataset_manifest_sha256"]
            ),
        }
        structural_requirements = {
            **metadata_requirements,
            "mode_input_hidden": probe.get("grasp_mode_conditioned") is False,
            "three_or_more_samples": int(probe.get("sample_count", 0)) >= 3,
            "finite": probe.get("finite") is True,
            "material_action": probe.get("material_action") is True,
            "no_expert_fallback": probe.get("fallback_to_expert") is False,
            "no_expert_reference": probe.get("expert_reference_used") is False,
            "full_absolute_authority": (
                probe.get("pure_vla_qualified") is True
                and float(probe.get("selected_scale_min", 0.0)) == 1.0
            ),
            "pi05_policy": probe.get("policy_type") == "pi05",
            "common_random_numbers": (
                probe.get("sampling_seed_protocol")
                == "common-random-numbers-per-observation-v1"
            ),
        }
        structural_errors.extend(
            f"{prefix}:{name}"
            for name, passed in structural_requirements.items()
            if not passed
        )
        if probe.get("grasp_mode_correct") is not True:
            routing_errors.append(f"{prefix}:mode_correct")

        fidelity = probe.get("action_fidelity")
        fidelity_requirements = (
            action_fidelity_gate(
                fidelity, **thresholds_for_stage(thresholds, stage)
            )
            if isinstance(fidelity, dict)
            else {}
        )
        if not fidelity_requirements:
            action_errors.append(f"{prefix}:action_fidelity_available")
        action_errors.extend(
            f"{prefix}:{name}"
            for name, passed in fidelity_requirements.items()
            if not passed
        )
        rows.append(
            {
                "observation_id": observation_id,
                "expected_mode": mode,
                "stage": stage,
                "dataset_index": planned["dataset_index"],
                "source_identity": planned["source_identity"],
                "predicted_mode": probe.get("predicted_grasp_mode"),
                "action_fidelity": fidelity,
                "action_fidelity_requirements": fidelity_requirements,
                "structural_requirements": structural_requirements,
            }
        )

    errors = structural_errors + routing_errors + action_errors
    correct = len(probes) - len(routing_errors)
    per_mode = {
        mode: {
            "probes": mode_counts[mode],
            "correct_probes": sum(
                probe.get("grasp_mode_correct") is True
                for probe in probes
                if probe.get("expected_grasp_mode") == mode
            ),
        }
        for mode in PI05_GRASP_MODES
    }
    return {
        "schema_version": 1,
        "protocol": SCREEN_PROTOCOL,
        "status": "passed" if not errors else "failed",
        "checkpoint": next(iter(checkpoints)) if len(checkpoints) == 1 else None,
        "dataset": next(iter(datasets)) if len(datasets) == 1 else None,
        "action_contract": (
            next(iter(action_contracts)) if len(action_contracts) == 1 else None
        ),
        "observation_panel_role": role,
        "stage_panel_sha256": design["panel_sha256"],
        "dataset_manifest_sha256": design["dataset_manifest_sha256"],
        "action_thresholds_sha256": thresholds["thresholds_sha256"],
        "deployment_calibrated_thresholds": (
            thresholds.get("deployment_calibrated") is True
        ),
        "sample_seeds": (
            list(next(iter(seed_panels))) if len(seed_panels) == 1 else None
        ),
        "sampling_seed_protocol": "common-random-numbers-per-observation-v1",
        "errors": errors,
        "error_count": len(errors),
        "routing_errors": routing_errors,
        "routing_error_count": len(routing_errors),
        "action_fidelity_errors": action_errors,
        "action_fidelity_error_count": len(action_errors),
        "structural_errors": structural_errors,
        "structural_error_count": len(structural_errors),
        "action_fidelity_required": True,
        "mode_stage_cells": len(PI05_GRASP_MODES) * len(PI05_TASK_STAGES),
        "probe_counts_by_mode": dict(mode_counts),
        "probe_counts_by_stage": dict(stage_counts),
        "metrics": {
            "probes": len(probes),
            "correct_probes": correct,
            "probe_accuracy": correct / len(probes) if probes else None,
            "per_mode": per_mode,
        },
        "modes": rows,
        "claim_boundary": (
            "Offline stage-complete routing/action contract evidence only. It is "
            "neither closed-loop success nor frozen benchmark evidence."
        ),
    }


if __name__ == "__main__":
    raise SystemExit(main())
