#!/usr/bin/env python3
"""Create a compact, hash-linked audit of a mobile VLA campaign."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics
from typing import Any

from parcel_sorter.metrics import wilson_interval
from parcel_sorter.mobile_policy_attribution import (
    ABSOLUTE_VLA_AUTHORITY,
    HYBRID_VLA_AUTHORITY,
    SHIELDED_VLA_CONTROL_CLASS,
    summarize_mobile_policy_attribution,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _profile_summaries(runs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    summaries: dict[str, dict[str, Any]] = {}
    for profile in sorted({str(run.get("profile")) for run in runs}):
        group = [run for run in runs if str(run.get("profile")) == profile]
        trials = len(group)
        successes = sum(bool(run.get("success")) for run in group)
        low, high = wilson_interval(successes, trials)
        placement_errors = [
            float(run["placement_error_m"])
            for run in group
            if run.get("success") and run.get("placement_error_m") is not None
        ]
        summaries[profile] = {
            "successes": successes,
            "trials": trials,
            "success_rate": successes / trials if trials else 0.0,
            "wilson_95": [low, high],
            "mean_success_placement_error_m": (
                statistics.fmean(placement_errors) if placement_errors else None
            ),
            "force_violation_count": sum(
                float((run.get("suction") or {}).get("max_contact_force_n") or 0.0)
                >= 35.0
                for run in group
            ),
            "failure_stages": {
                stage: sum(str(run.get("failure_stage")) == stage for run in group)
                for stage in sorted(
                    {
                        str(run.get("failure_stage"))
                        for run in group
                        if run.get("failure_stage") is not None
                    }
                )
            },
        }
    return summaries


def _material_pi05_residual(policy: dict[str, Any]) -> tuple[bool, float]:
    maximum = 0.0
    for item in policy.get("trace", ()):
        projection = item.get("residual_projection") or {}
        for key in (
            "base_residual",
            "left_contact_residual_m",
            "right_contact_residual_m",
        ):
            values = projection.get(key) or ()
            if len(values) == 3:
                maximum = max(
                    maximum,
                    math.sqrt(sum(float(value) ** 2 for value in values)),
                )
    return maximum > 1e-5, maximum


def _material_pi05_absolute(policy: dict[str, Any]) -> tuple[bool, float]:
    maximum = 0.0
    for item in policy.get("trace", ()):
        base = item.get("raw_base_action") or ()
        if len(base) == 3:
            maximum = max(
                maximum,
                math.sqrt(sum(float(value) ** 2 for value in base)),
            )
        arm = item.get("arm_residual") or {}
        maximum = max(
            maximum,
            float(arm.get("residual_norm_m") or 0.0),
            float(arm.get("right_residual_norm_m") or 0.0),
        )
    return maximum > 1e-5, maximum


def _vla_qualified(
    policy: dict[str, Any],
    *,
    material_residual: bool,
    material_absolute_action: bool = False,
) -> bool:
    """Require evidence that PI0.5, not an expert label, controlled the run."""

    common = bool(
        policy.get("enabled")
        and policy.get("checkpoint")
        and policy.get("policy_type") == "pi05"
        and policy.get("vla_routes_grasp_mode") is True
        and policy.get("grasp_mode_verdict_required") is True
        and policy.get("goal_verdict_required") is True
        and policy.get("goal_arrival_verified") is True
        and policy.get("grasp_mode_match") is True
        and policy.get("selected_grasp_mode")
        == policy.get("expected_grasp_mode")
        == policy.get("executed_grasp_mode")
        and int(policy.get("applied_physics_steps") or 0) > 0
        and int(policy.get("expert_fallback_count") or 0) == 0
    )
    if not common:
        return False
    if policy.get("mode") == "pi05_absolute":
        return bool(
            material_absolute_action
            and policy.get("policy_authority") == ABSOLUTE_VLA_AUTHORITY
            and policy.get("system_control_class") == "pure_vla"
            and int(policy.get("task_action_correction_count") or 0) == 0
            and policy.get("expert_reference_used") is False
            and policy.get("absolute_full_authority") is True
            and int(policy.get("emergency_stop_count") or 0) == 0
            and policy.get("transport_deadline_handoff") is not True
        )
    return bool(policy.get("mode") == "pi05_residual" and material_residual)


def _vla_attribution_class(policy: dict[str, Any]) -> str:
    """Separate VLA actuation from the nominal action source used underneath it."""

    attribution = summarize_mobile_policy_attribution(policy.get("trace") or ())
    if attribution.system_control_class == SHIELDED_VLA_CONTROL_CLASS:
        return "shielded_vla_external_routing_or_task_interlock"
    if attribution.policy_authority == HYBRID_VLA_AUTHORITY:
        return "hybrid_vla_residual_with_expert_reference"
    if attribution.policy_authority == ABSOLUTE_VLA_AUTHORITY:
        return "absolute_vla_action_with_harness_only"
    if policy.get("mode") == "pi05_residual":
        return "legacy_unattributed_pi05_residual"
    return "not_pi05_vla"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection-summary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    collection = json.loads(args.collection_summary.read_text(encoding="utf-8"))
    compact_runs: list[dict[str, Any]] = []
    errors = []
    for result in collection.get("results", ()):
        summary_path = Path(str(result.get("summary", "")))
        if not summary_path.is_file():
            errors.append(f"missing_summary:{result.get('episode_id')}")
            continue
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        runtime = summary.get("runtime") or {}
        policy = summary.get("policy") or {}
        material_residual, maximum_residual_norm = _material_pi05_residual(policy)
        material_absolute, maximum_absolute_norm = _material_pi05_absolute(policy)
        vla_qualified = _vla_qualified(
            policy,
            material_residual=material_residual,
            material_absolute_action=material_absolute,
        )
        attribution_class = _vla_attribution_class(policy)
        attribution = summarize_mobile_policy_attribution(policy.get("trace") or ())
        compact_runs.append(
            {
                "episode_id": result.get("episode_id"),
                "profile": result.get("profile"),
                "parameters": result.get("parameters"),
                "success": bool(summary.get("success")),
                "failure_stage": result.get("failure_stage"),
                "placement_error_m": summary.get("placement_error_m"),
                "lift_delta_m": summary.get("lift_delta_m"),
                "suction": summary.get("suction"),
                "cradle": summary.get("cradle"),
                "media": summary.get("media"),
                "policy": {key: value for key, value in policy.items() if key != "trace"},
                "vla_qualified": vla_qualified,
                "vla_attribution_class": attribution_class,
                "policy_authority": attribution.policy_authority,
                "system_control_class": attribution.system_control_class,
                "task_routing_authorities": list(
                    attribution.task_routing_authorities
                ),
                "task_action_correction_count": (
                    attribution.task_action_correction_count
                ),
                "expert_reference_used": attribution.expert_reference_used,
                "expert_reference_semantics": list(
                    attribution.expert_reference_semantics
                ),
                "policy_authority_consistent": attribution.internally_consistent,
                "material_pi05_residual": material_residual,
                "maximum_pi05_residual_norm": maximum_residual_norm,
                "material_pi05_absolute_action": material_absolute,
                "maximum_pi05_absolute_action_norm": maximum_absolute_norm,
                "pure_vla_complete_success": bool(
                    summary.get("success")
                    and policy.get("pure_vla_complete_success") is True
                ),
                "runtime": {
                    "torch": runtime.get("torch"),
                    "rocm": runtime.get("rocm"),
                    "cuda": runtime.get("cuda"),
                    "gpu_count": runtime.get("gpu_count"),
                    "gpu_name": runtime.get("gpu_name"),
                },
                "source_summary": str(summary_path.resolve()),
                "source_summary_sha256": _sha256(summary_path),
            }
        )

    successes = sum(bool(run["success"]) for run in compact_runs)
    trials = len(compact_runs)
    wilson_low, wilson_high = wilson_interval(successes, trials)
    successful_errors = [
        float(run["placement_error_m"])
        for run in compact_runs
        if run["success"] and run["placement_error_m"] is not None
    ]
    policy_modes = sorted(
        {
            str((run.get("policy") or {}).get("mode"))
            for run in compact_runs
            if (run.get("policy") or {}).get("enabled")
        }
    )
    checkpoints = sorted(
        {
            str((run.get("policy") or {}).get("checkpoint"))
            for run in compact_runs
            if (run.get("policy") or {}).get("checkpoint")
        }
    )
    vla_campaign = bool(policy_modes and checkpoints)
    payload = {
        "schema_version": 1,
        "protocol": "mobile-vla-campaign-audit-v1",
        "status": "passed" if not errors and trials == int(collection["requested_episodes"]) else "failed",
        "errors": errors,
        "collection_summary": str(args.collection_summary.resolve()),
        "collection_summary_sha256": _sha256(args.collection_summary),
        "audit_only": collection.get("merged_dataset_root") is None,
        "successes": successes,
        "trials": trials,
        "success_rate": successes / trials if trials else 0.0,
        "wilson_95": [wilson_low, wilson_high],
        "mean_success_placement_error_m": (
            statistics.fmean(successful_errors) if successful_errors else None
        ),
        "force_violation_count": sum(
            max(
                float((run.get("suction") or {}).get("max_contact_force_n") or 0.0),
                float((run.get("suction") or {}).get("max_suction_force_n") or 0.0),
                float(
                    ((run.get("cradle") or {}).get("physical") or {}).get(
                        "max_contact_force_n"
                    )
                    or 0.0
                ),
            )
            >= 35.0
            for run in compact_runs
        ),
        "vla_actuated_run_count": sum(
            int((run.get("policy") or {}).get("applied_physics_steps") or 0) > 0
            for run in compact_runs
        ),
        "vla_qualified_run_count": sum(bool(run["vla_qualified"]) for run in compact_runs),
        "vla_attribution_counts": {
            attribution: sum(
                run["vla_attribution_class"] == attribution for run in compact_runs
            )
            for attribution in sorted(
                {run["vla_attribution_class"] for run in compact_runs}
            )
        },
        "material_pi05_residual_run_count": sum(
            bool(run["material_pi05_residual"]) for run in compact_runs
        ),
        "material_pi05_absolute_action_run_count": sum(
            bool(run["material_pi05_absolute_action"]) for run in compact_runs
        ),
        "pure_vla_complete_success_count": sum(
            bool(run["pure_vla_complete_success"]) for run in compact_runs
        ),
        "expert_fallback_count": sum(
            int((run.get("policy") or {}).get("expert_fallback_count") or 0)
            for run in compact_runs
        ),
        "vla_goal_verified_run_count": sum(
            bool((run.get("policy") or {}).get("goal_arrival_verified"))
            for run in compact_runs
        ),
        "policy_modes": policy_modes,
        "checkpoints": checkpoints,
        "single_radeon_rocm_run_count": sum(
            (run.get("runtime") or {}).get("gpu_count") == 1
            and (run.get("runtime") or {}).get("cuda") is None
            and bool((run.get("runtime") or {}).get("rocm"))
            for run in compact_runs
        ),
        "profile_summaries": _profile_summaries(compact_runs),
        "runs": compact_runs,
        "claim_boundary": (
            f"frozen {trials}-trial PI0.5 VLA simulation campaign over "
            f"{len({run['profile'] for run in compact_runs})} configured parcel profiles; "
            "VLA qualification, material residual actuation, fallback, and safety are "
            "reported separately; not sim-to-real evidence"
            if vla_campaign
            else f"frozen {trials}-trial simulation campaign over "
            f"{len({run['profile'] for run in compact_runs})} configured parcel profiles; "
            "deterministic execution baseline only, not VLA-actuated or sim-to-real evidence"
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload))
    return 0 if payload["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
