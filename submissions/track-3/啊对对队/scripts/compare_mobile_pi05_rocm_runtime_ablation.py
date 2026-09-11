#!/usr/bin/env python3
"""Compare matched cold/resident PI0.5 runtime arms on Radeon."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from parcel_sorter.mobile_pi05_evaluation import exact_mcnemar_p


ARM_IDS = ("P0_COLD_FIRST_HOLD", "P1_RESIDENT_FIRST_HOLD", "P2_RESIDENT_STAGE_QUEUE")


def compare_runtime_arms(summaries: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if set(summaries) != set(ARM_IDS):
        raise ValueError(f"runtime comparison requires exactly {ARM_IDS}")
    fingerprints = {item.get("design_fingerprint_sha256") for item in summaries.values()}
    checkpoints = {tuple(item.get("checkpoints") or ()) for item in summaries.values()}
    if len(fingerprints) != 1 or None in fingerprints:
        raise ValueError("runtime arms do not share one frozen design fingerprint")
    if len(checkpoints) != 1 or not next(iter(checkpoints)):
        raise ValueError("runtime arms do not share one checkpoint")

    outcomes = {
        arm: {str(item["episode_id"]): item for item in summary.get("outcomes") or ()}
        for arm, summary in summaries.items()
    }
    episode_sets = {tuple(sorted(items)) for items in outcomes.values()}
    if len(episode_sets) != 1 or not next(iter(episode_sets)):
        raise ValueError("runtime arms do not contain the same non-empty episode set")
    episode_ids = next(iter(episode_sets))
    baseline = summaries[ARM_IDS[0]]
    baseline_outcomes = outcomes[ARM_IDS[0]]
    baseline_successes = int(baseline["pure_vla_complete_success"]["successes"])
    baseline_energy = (baseline.get("telemetry") or {}).get(
        "wh_per_pure_vla_success"
    )

    arms = []
    for arm_id in ARM_IDS:
        summary = summaries[arm_id]
        arm_outcomes = outcomes[arm_id]
        improvements = sum(
            not bool(baseline_outcomes[item]["pure_vla_complete_success"])
            and bool(arm_outcomes[item]["pure_vla_complete_success"])
            for item in episode_ids
        )
        regressions = sum(
            bool(baseline_outcomes[item]["pure_vla_complete_success"])
            and not bool(arm_outcomes[item]["pure_vla_complete_success"])
            for item in episode_ids
        )
        successes = int(summary["pure_vla_complete_success"]["successes"])
        energy = (summary.get("telemetry") or {}).get(
            "wh_per_pure_vla_success"
        )
        energy_reduction = (
            1.0 - float(energy) / float(baseline_energy)
            if arm_id != ARM_IDS[0]
            and energy is not None
            and baseline_energy is not None
            and float(baseline_energy) > 0.0
            else (0.0 if arm_id == ARM_IDS[0] else None)
        )
        all_pure = all(bool(item["pure_vla_action"]) for item in arm_outcomes.values())
        eligible = bool(
            arm_id != ARM_IDS[0]
            and successes >= baseline_successes
            and int(summary.get("force_violation_count") or 0)
            <= int(baseline.get("force_violation_count") or 0)
            and int(summary.get("expert_fallback_count") or 0) == 0
            and int(summary.get("emergency_stop_count") or 0) == 0
            and all_pure
            and energy_reduction is not None
            and energy_reduction >= 0.20
        )
        arms.append(
            {
                "id": arm_id,
                "successes": successes,
                "trials": int(summary["pure_vla_complete_success"]["trials"]),
                "success_delta_vs_p0": successes - baseline_successes,
                "discordant_improvements_vs_p0": improvements,
                "discordant_regressions_vs_p0": regressions,
                "mcnemar_exact_two_sided_p_vs_p0": exact_mcnemar_p(
                    improvements, regressions
                ),
                "wh_per_pure_vla_success": energy,
                "energy_reduction_vs_p0": energy_reduction,
                "force_violation_count": int(summary.get("force_violation_count") or 0),
                "all_runs_pure_vla": all_pure,
                "promotion_eligible": eligible,
            }
        )
    eligible_arms = [item for item in arms if item["promotion_eligible"]]
    selected = (
        max(
            eligible_arms,
            key=lambda item: (
                item["successes"],
                item["energy_reduction_vs_p0"],
            ),
        )["id"]
        if eligible_arms
        else None
    )
    return {
        "schema_version": 1,
        "protocol": "pi05-radeon-persistent-runtime-comparison-v1",
        "status": "passed" if selected is not None else "no_promotion",
        "design_fingerprint_sha256": next(iter(fingerprints)),
        "checkpoint": list(next(iter(checkpoints))),
        "independent_contexts": len(episode_ids),
        "arms": arms,
        "selected_arm": selected,
        "claim_boundary": (
            "Matched development comparison. Energy promotion requires at least 20% "
            "lower raw Radeon package Wh per pure-VLA success with no success or safety regression."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for arm in ARM_IDS:
        parser.add_argument(f"--{arm.lower().replace('_', '-')}", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    summaries = {
        arm: json.loads(
            getattr(args, arm.lower()).read_text(encoding="utf-8")
        )
        for arm in ARM_IDS
    }
    result = compare_runtime_arms(summaries)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
