"""Frozen PI0.5 validation design and strict pure-VLA reporting."""

from __future__ import annotations

from collections import Counter, defaultdict
import copy
import hashlib
import json
import math
from pathlib import Path
import random
import statistics
import tomllib
from typing import Any, Iterable, Mapping

from .metrics import wilson_interval
from .mobile_grasp_routing import route_mobile_grasp


GRASP_MODES = ("top_suction", "side_suction", "cooperative_cradle")
MODE_CODES = {
    "top_suction": "top",
    "side_suction": "side",
    "cooperative_cradle": "cradle",
}
VALIDATION_BLOCKS = 20
VALIDATION_SEED = 20260728
OFFSETS_M = (
    (0.000, 0.000),
    (0.010, 0.000),
    (-0.010, 0.000),
    (0.000, 0.010),
    (0.000, -0.010),
)
YAWS_RAD = (0.0, -0.12, 0.12, -0.25, 0.25)


def _lerp(low: float, high: float, quantile: float) -> float:
    return float(low) + (float(high) - float(low)) * quantile


def _physical_values(profile: Mapping[str, Any], quantile: float) -> dict[str, Any]:
    size = [
        _lerp(low, high, quantile)
        for low, high in zip(
            profile["dimensions_min_m"],
            profile["dimensions_max_m"],
            strict=True,
        )
    ]
    if profile["shape"] == "cylinder":
        diameter_indices = (
            (0, 1) if profile["orientation_mode"] == "upright" else (1, 2)
        )
        diameter = statistics.fmean(size[index] for index in diameter_indices)
        for index in diameter_indices:
            size[index] = diameter
    return {
        "size_m": size,
        "mass_kg": _lerp(profile["mass_kg_min"], profile["mass_kg_max"], quantile),
        "friction": _lerp(profile["friction_min"], profile["friction_max"], quantile),
    }


def _mass_stratum(quantile: float) -> str:
    if quantile < 1.0 / 3.0:
        return "low"
    if quantile < 2.0 / 3.0:
        return "medium"
    return "high"


def _context_fingerprint(contexts: Iterable[Mapping[str, Any]]) -> str:
    canonical = sorted(
        (dict(context) for context in contexts),
        key=lambda item: str(item["physical_context_id"]),
    )
    encoded = json.dumps(
        canonical,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _eligible_profiles(
    profiles: list[dict[str, Any]], quantile: float, mode: str
) -> list[tuple[dict[str, Any], dict[str, Any], Any]]:
    eligible = []
    for profile in profiles:
        physical = _physical_values(profile, quantile)
        route = route_mobile_grasp(
            shape=str(profile["shape"]),
            orientation_mode=str(profile["orientation_mode"]),
            size_m=physical["size_m"],
            mass_kg=float(physical["mass_kg"]),
            handling_class=str(profile["handling_class"]),
        )
        if route.mode == mode:
            eligible.append((profile, physical, route))
    return eligible


def build_pi05_validation_design(
    catalog_path: Path,
    *,
    seed: int = VALIDATION_SEED,
    blocks: int = VALIDATION_BLOCKS,
    context_prefix: str = "pv60",
    validation_collection_id: str = "mobile-pi05-frozen-validation-60-v1",
    long_run_collection_id: str = "mobile-pi05-frozen-long-run-120-v1",
    validation_split: str = "frozen_validation_do_not_train",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Create 60 unique contexts and a two-cycle long-running schedule."""

    if blocks < 3:
        raise ValueError("at least three complete blocks are required")
    catalog = tomllib.loads(catalog_path.read_text(encoding="utf-8"))
    profiles = [dict(item) for item in catalog.get("parcel_profiles", ())]
    if not profiles:
        raise ValueError("catalog contains no parcel profiles")

    selection_rng = random.Random(seed)
    mode_profile_offsets = {
        mode: selection_rng.randrange(max(1, len(profiles))) for mode in GRASP_MODES
    }
    contexts = []
    for block_index in range(blocks):
        quantile = (block_index + 0.5) / blocks
        for mode_index, mode in enumerate(GRASP_MODES):
            eligible = _eligible_profiles(profiles, quantile, mode)
            if not eligible:
                raise ValueError(f"no {mode} profile is available in block {block_index + 1}")
            profile, physical, route = eligible[
                (block_index + mode_profile_offsets[mode]) % len(eligible)
            ]
            context_id = f"{context_prefix}-{MODE_CODES[mode]}-{block_index + 1:02d}"
            contexts.append(
                {
                    "episode_id": context_id,
                    "physical_context_id": context_id,
                    "evaluation_block": block_index + 1,
                    "mass_stratum": _mass_stratum(quantile),
                    "sampling_quantile": quantile,
                    "profile": str(profile["profile_id"]),
                    "profile_evaluation_only": bool(profile.get("evaluation_only")),
                    "shape": str(profile["shape"]),
                    "orientation_mode": str(profile["orientation_mode"]),
                    "yaw_rad": YAWS_RAD[(block_index + mode_index) % len(YAWS_RAD)],
                    "handling_class": str(profile["handling_class"]),
                    "grasp_mode": mode,
                    "minimum_sealed_cups": route.minimum_sealed_cups,
                    "cooperative_cradle": route.cooperative_cradle,
                    "grasp_route_reason": route.reason,
                    **physical,
                    "offset_m": list(
                        OFFSETS_M[(2 * block_index + mode_index) % len(OFFSETS_M)]
                    ),
                    "recovery_contact_offset_m": [0.0, 0.0],
                    "recovery_contact_penetration_delta_m": 0.0,
                    "recovery_cradle_engagement_delta_m": 0.0,
                    "recovery_left_lift_offset_m": [0.0, 0.0, 0.0],
                    "recovery_right_lift_offset_m": [0.0, 0.0, 0.0],
                    "retry_index": 0,
                    "expert_reference_allowed": False,
                    "split": validation_split,
                    "task_text": (
                        "Pick up the parcel, transport it to the marked destination, "
                        "place it safely, and release it."
                    ),
                }
            )

    fingerprint = _context_fingerprint(contexts)
    block_order = list(range(1, blocks + 1))
    order_rng = random.Random(seed + 1)
    order_rng.shuffle(block_order)
    by_block = defaultdict(list)
    for context in contexts:
        by_block[int(context["evaluation_block"])].append(context)
    ordered_contexts = []
    for block_id in block_order:
        block = list(by_block[block_id])
        order_rng.shuffle(block)
        ordered_contexts.extend(copy.deepcopy(block))

    validation = {
        "schema_version": 1,
        "collection_id": validation_collection_id,
        "protocol": "pi05-pure-vla-randomized-complete-block-validation-v1",
        "frozen_seed": seed,
        "independent_physical_contexts": len(contexts),
        "randomized_complete_blocks": blocks,
        "contexts_per_grasp_mode": blocks,
        "design_fingerprint_sha256": fingerprint,
        "source_catalog": str(catalog_path.as_posix()),
        "episodes": ordered_contexts,
        "primary_gate": {
            "minimum_pure_vla_successes": math.ceil(0.75 * len(contexts)),
            "minimum_successes_per_mode": math.ceil(0.65 * blocks),
            "minimum_routing_correct": math.ceil(0.90 * len(contexts)),
            "maximum_force_violations": 1,
            "maximum_expert_fallbacks": 0,
            "maximum_emergency_stops": 0,
        },
        "claim_boundary": (
            "Frozen simulation validation. Only absolute PI0.5 actions without an "
            "expert reference or fallback count as pure VLA; not sim-to-real evidence."
        ),
    }

    long_run_episodes = []
    for cycle_index in (1, 2):
        cycle_blocks = list(range(1, blocks + 1))
        cycle_rng = random.Random(seed + 100 + cycle_index)
        cycle_rng.shuffle(cycle_blocks)
        for block_id in cycle_blocks:
            block = list(by_block[block_id])
            cycle_rng.shuffle(block)
            for context in block:
                episode = copy.deepcopy(context)
                episode["episode_id"] = (
                    f"{context['physical_context_id']}-cycle-{cycle_index}"
                )
                episode["cycle_index"] = cycle_index
                episode["split"] = "frozen_long_run_repeated_measure_do_not_train"
                long_run_episodes.append(episode)
    long_run = {
        "schema_version": 1,
        "collection_id": long_run_collection_id,
        "protocol": "pi05-pure-vla-two-cycle-long-run-v1",
        "frozen_seed": seed,
        "independent_physical_contexts": len(contexts),
        "descriptive_rollouts": len(long_run_episodes),
        "repeated_cycles": 2,
        "design_fingerprint_sha256": fingerprint,
        "source_validation_collection": validation["collection_id"],
        "episodes": long_run_episodes,
        "stability_gate": {
            "maximum_cycle_success_rate_drop": 0.10,
            "maximum_force_violations": 2,
            "maximum_expert_fallbacks": 0,
            "maximum_emergency_stops": 0,
            "maximum_vram_growth_percentage_points": 3.0,
        },
        "analysis_note": (
            "The second cycle is a repeated measurement. The independent sample "
            "count remains 60 and must not be reported as n=120."
        ),
        "claim_boundary": (
            "Continuous-campaign simulation evidence. Persistent-policy uptime may "
            "only be claimed when one runtime session id spans consecutive tasks."
        ),
    }
    validate_pi05_validation_design(validation, long_run)
    return validation, long_run


def validate_pi05_validation_design(
    validation: Mapping[str, Any], long_run: Mapping[str, Any]
) -> None:
    episodes = list(validation.get("episodes") or ())
    expected_blocks = int(validation.get("randomized_complete_blocks", 0))
    expected_contexts = expected_blocks * len(GRASP_MODES)
    if (
        expected_blocks < 3
        or len(episodes) != expected_contexts
        or int(validation.get("independent_physical_contexts", 0)) != expected_contexts
    ):
        raise ValueError("validation context count does not match its complete blocks")
    ids = [str(item.get("physical_context_id")) for item in episodes]
    if len(set(ids)) != expected_contexts:
        raise ValueError("validation physical context ids must be unique")
    mode_counts = Counter(str(item.get("grasp_mode")) for item in episodes)
    if mode_counts != Counter({mode: expected_blocks for mode in GRASP_MODES}):
        raise ValueError(f"validation grasp modes are not balanced: {mode_counts}")
    blocks = defaultdict(set)
    for item in episodes:
        blocks[int(item["evaluation_block"])].add(str(item["grasp_mode"]))
        if item.get("expert_reference_allowed") is not False:
            raise ValueError("validation cannot authorize an expert reference")
    if len(blocks) != expected_blocks or any(
        modes != set(GRASP_MODES) for modes in blocks.values()
    ):
        raise ValueError("each validation block must contain all three grasp modes")
    if _context_fingerprint(episodes) != validation.get("design_fingerprint_sha256"):
        raise ValueError("validation design fingerprint mismatch")

    repeated = list(long_run.get("episodes") or ())
    if len(repeated) != expected_contexts * 2:
        raise ValueError("long-run rollout count must be twice the context count")
    repeated_counts = Counter(str(item.get("physical_context_id")) for item in repeated)
    if set(repeated_counts) != set(ids) or set(repeated_counts.values()) != {2}:
        raise ValueError("every physical context must occur once in each long-run cycle")
    for context_id in ids:
        cycles = {
            int(item["cycle_index"])
            for item in repeated
            if item["physical_context_id"] == context_id
        }
        if cycles != {1, 2}:
            raise ValueError(f"invalid repeated cycles for {context_id}")
    if long_run.get("design_fingerprint_sha256") != validation.get(
        "design_fingerprint_sha256"
    ):
        raise ValueError("long-run and validation context fingerprints differ")


def _force_violation(run: Mapping[str, Any]) -> bool:
    suction = run.get("suction") or {}
    cradle = (run.get("cradle") or {}).get("physical") or {}
    return max(
        float(suction.get("max_contact_force_n") or 0.0),
        float(suction.get("max_suction_force_n") or 0.0),
        float(cradle.get("max_contact_force_n") or 0.0),
    ) >= 35.0


def _pure_absolute_vla(run: Mapping[str, Any]) -> bool:
    policy = run.get("policy") or {}
    authority = run.get("policy_authority") or policy.get("policy_authority")
    return bool(
        policy.get("mode") == "pi05_absolute"
        and authority == "absolute_vla_action_candidate"
        and (
            run.get("system_control_class")
            or policy.get("system_control_class")
        )
        == "pure_vla"
        and int(
            run.get("task_action_correction_count")
            or policy.get("task_action_correction_count")
            or 0
        )
        == 0
        and policy.get("absolute_full_authority") is True
        and not bool(run.get("expert_reference_used"))
        and policy.get("expert_reference_used") is False
        and int(policy.get("expert_fallback_count") or 0) == 0
        and int(policy.get("applied_physics_steps") or 0) > 0
    )


def _routing_correct(run: Mapping[str, Any], expected_mode: str) -> bool:
    policy = run.get("policy") or {}
    return bool(
        policy.get("selected_grasp_mode")
        == policy.get("executed_grasp_mode")
        == expected_mode
        and policy.get("grasp_mode_match") is True
    )


def _rate_summary(successes: int, trials: int) -> dict[str, Any]:
    low, high = wilson_interval(successes, trials)
    return {
        "successes": successes,
        "trials": trials,
        "rate": successes / trials if trials else 0.0,
        "wilson_95": [low, high],
    }


def _policy_metric_summary(runs: list[Mapping[str, Any]]) -> dict[str, Any]:
    policies = [run.get("policy") or {} for run in runs]

    def mean(name: str) -> float | None:
        values = [
            float(policy[name])
            for policy in policies
            if policy.get(name) is not None
        ]
        return statistics.fmean(values) if values else None

    session_ids = {
        str(policy["policy_runtime_session_id"])
        for policy in policies
        if policy.get("policy_runtime_session_id")
    }
    return {
        "mean_policy_inference_count_per_attempt": mean("policy_inference_count"),
        "mean_policy_selection_count_per_attempt": mean("policy_selection_count"),
        "mean_cold_start_latency_ms": mean("cold_start_latency_ms"),
        "mean_warm_p95_latency_ms": mean("warm_p95_latency_ms"),
        "persistent_policy_run_count": sum(
            bool(policy.get("persistent_policy_service")) for policy in policies
        ),
        "policy_runtime_session_count": len(session_ids),
        "policy_runtime_session_ids": sorted(session_ids),
    }


def summarize_pi05_frozen_validation(
    design: Mapping[str, Any],
    audit: Mapping[str, Any],
    *,
    telemetry: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Summarize validation without crediting expert or hybrid actions."""

    design_episodes = list(design.get("episodes") or ())
    design_by_id = {str(item["episode_id"]): item for item in design_episodes}
    runs = list(audit.get("runs") or ())
    run_by_id = {str(item.get("episode_id")): item for item in runs}
    errors = []
    if set(run_by_id) != set(design_by_id):
        errors.append("campaign_episode_set_mismatch")
    ordered = [run_by_id[item_id] for item_id in design_by_id if item_id in run_by_id]

    pure_flags = [_pure_absolute_vla(run) for run in ordered]
    success_flags = [
        pure
        and bool(run.get("success"))
        and bool(run.get("pure_vla_complete_success"))
        for run, pure in zip(ordered, pure_flags, strict=True)
    ]
    routing_flags = [
        _routing_correct(run, str(design_by_id[str(run["episode_id"])]["grasp_mode"]))
        for run in ordered
    ]
    force_violations = sum(_force_violation(run) for run in ordered)
    expert_fallbacks = sum(
        int((run.get("policy") or {}).get("expert_fallback_count") or 0)
        for run in ordered
    )
    emergency_stops = sum(
        int((run.get("policy") or {}).get("emergency_stop_count") or 0)
        for run in ordered
    )
    overall = _rate_summary(sum(success_flags), len(ordered))
    routing = _rate_summary(sum(routing_flags), len(ordered))
    by_mode = {}
    for mode in GRASP_MODES:
        indices = [
            index
            for index, run in enumerate(ordered)
            if design_by_id[str(run["episode_id"])]["grasp_mode"] == mode
        ]
        by_mode[mode] = _rate_summary(
            sum(success_flags[index] for index in indices), len(indices)
        )

    gate = design.get("primary_gate") or {}
    gate_checks = {
        "overall_success": overall["successes"]
        >= int(gate.get("minimum_pure_vla_successes", 45)),
        "per_mode_success": all(
            item["successes"] >= int(gate.get("minimum_successes_per_mode", 13))
            for item in by_mode.values()
        ),
        "routing_accuracy": routing["successes"]
        >= int(gate.get("minimum_routing_correct", 54)),
        "all_runs_pure_vla": sum(pure_flags) == len(design_episodes),
        "force_safety": force_violations
        <= int(gate.get("maximum_force_violations", 1)),
        "zero_expert_fallback": expert_fallbacks
        <= int(gate.get("maximum_expert_fallbacks", 0)),
        "zero_emergency_stop": emergency_stops
        <= int(gate.get("maximum_emergency_stops", 0)),
        "complete_campaign": len(ordered) == len(design_episodes),
    }
    telemetry_result = dict(telemetry) if telemetry is not None else None
    if telemetry_result is not None:
        total_wh = telemetry_result.get("energy_wh")
        telemetry_result["wh_per_attempt"] = (
            float(total_wh) / len(ordered)
            if total_wh is not None and ordered
            else None
        )
        telemetry_result["wh_per_pure_vla_success"] = (
            float(total_wh) / overall["successes"]
            if total_wh is not None and overall["successes"]
            else None
        )
    gate_checks["rocm_telemetry_complete"] = bool(
        telemetry_result
        and int(telemetry_result.get("sample_count") or 0) >= 2
        and telemetry_result.get("energy_wh") is not None
        and int(telemetry_result.get("sampling_error_count") or 0) == 0
    )
    outcomes = []
    for index, run in enumerate(ordered):
        context = design_by_id[str(run["episode_id"])]
        outcomes.append(
            {
                "episode_id": str(run["episode_id"]),
                "physical_context_id": str(context["physical_context_id"]),
                "grasp_mode": str(context["grasp_mode"]),
                "pure_vla_action": pure_flags[index],
                "routing_correct": routing_flags[index],
                "pure_vla_complete_success": success_flags[index],
                "force_violation": _force_violation(run),
            }
        )
    result = {
        "schema_version": 1,
        "protocol": "pi05-pure-vla-frozen-validation-summary-v1",
        "status": "passed" if not errors and all(gate_checks.values()) else "failed",
        "errors": errors,
        "design_fingerprint_sha256": design.get("design_fingerprint_sha256"),
        "independent_physical_contexts": len(design_episodes),
        "pure_vla_action_runs": sum(pure_flags),
        "pure_vla_complete_success": overall,
        "routing_accuracy": routing,
        "per_grasp_mode": by_mode,
        "force_violation_count": force_violations,
        "expert_fallback_count": expert_fallbacks,
        "emergency_stop_count": emergency_stops,
        "gate_checks": gate_checks,
        "checkpoints": list(audit.get("checkpoints") or ()),
        "policy_runtime": _policy_metric_summary(ordered),
        "telemetry": telemetry_result,
        "outcomes": outcomes,
        "claim_boundary": (
            "Pure absolute PI0.5 simulation score on a frozen 60-context design. "
            "Hybrid/expert-reference actions receive zero success credit."
        ),
    }
    return result


def summarize_pi05_long_run(
    design: Mapping[str, Any],
    audit: Mapping[str, Any],
    *,
    telemetry: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    design_by_id = {
        str(item["episode_id"]): item for item in design.get("episodes") or ()
    }
    runs = list(audit.get("runs") or ())
    run_by_id = {str(item.get("episode_id")): item for item in runs}
    errors = []
    if set(run_by_id) != set(design_by_id):
        errors.append("campaign_episode_set_mismatch")

    cycle_summaries = {}
    pure_success_by_cycle = {}
    for cycle in (1, 2):
        cycle_runs = [
            run_by_id[episode_id]
            for episode_id, context in design_by_id.items()
            if int(context["cycle_index"]) == cycle and episode_id in run_by_id
        ]
        flags = [
            _pure_absolute_vla(run)
            and bool(run.get("success"))
            and bool(run.get("pure_vla_complete_success"))
            for run in cycle_runs
        ]
        cycle_summaries[str(cycle)] = {
            **_rate_summary(sum(flags), len(flags)),
            "policy_runtime": _policy_metric_summary(cycle_runs),
        }
        pure_success_by_cycle[cycle] = flags

    first = cycle_summaries["1"]["rate"]
    second = cycle_summaries["2"]["rate"]
    all_runs = [run_by_id[item] for item in design_by_id if item in run_by_id]
    policies = [run.get("policy") or {} for run in all_runs]
    session_ids = [policy.get("policy_runtime_session_id") for policy in policies]
    persistent_evidence = bool(session_ids and all(session_ids) and len(set(session_ids)) == 1)
    longest_session_streak = 0
    current_session = object()
    current_streak = 0
    for session_id in session_ids:
        if session_id and session_id == current_session:
            current_streak += 1
        elif session_id:
            current_session = session_id
            current_streak = 1
        else:
            current_session = object()
            current_streak = 0
        longest_session_streak = max(longest_session_streak, current_streak)

    force_violations = sum(_force_violation(run) for run in all_runs)
    expert_fallbacks = sum(
        int(policy.get("expert_fallback_count") or 0) for policy in policies
    )
    emergency_stops = sum(
        int(policy.get("emergency_stop_count") or 0) for policy in policies
    )
    stability = design.get("stability_gate") or {}
    vram_growth = (
        float(telemetry.get("vram_growth_percentage_points"))
        if telemetry and telemetry.get("vram_growth_percentage_points") is not None
        else None
    )
    gate_checks = {
        "cycle_success_drop": first - second
        <= float(stability.get("maximum_cycle_success_rate_drop", 0.10)) + 1e-12,
        "force_safety": force_violations
        <= int(stability.get("maximum_force_violations", 2)),
        "zero_expert_fallback": expert_fallbacks == 0,
        "zero_emergency_stop": emergency_stops == 0,
        "complete_campaign": len(all_runs) == len(design_by_id),
        "vram_stability": vram_growth is not None
        and vram_growth
        <= float(stability.get("maximum_vram_growth_percentage_points", 3.0)),
    }
    successes = sum(item["successes"] for item in cycle_summaries.values())
    telemetry_result = dict(telemetry) if telemetry is not None else None
    if telemetry_result is not None:
        total_wh = telemetry_result.get("energy_wh")
        telemetry_result["wh_per_attempt"] = (
            float(total_wh) / len(all_runs) if total_wh is not None and all_runs else None
        )
        telemetry_result["wh_per_pure_vla_success"] = (
            float(total_wh) / successes if total_wh is not None and successes else None
        )
    return {
        "schema_version": 1,
        "protocol": "pi05-pure-vla-long-run-summary-v1",
        "status": "passed" if not errors and all(gate_checks.values()) else "failed",
        "errors": errors,
        "independent_physical_contexts": int(
            design.get("independent_physical_contexts", 0)
        ),
        "descriptive_repeated_rollouts": len(all_runs),
        "cycles": cycle_summaries,
        "cycle_2_minus_cycle_1_success_rate": second - first,
        "force_violation_count": force_violations,
        "expert_fallback_count": expert_fallbacks,
        "emergency_stop_count": emergency_stops,
        "persistent_policy_runtime_evidence": persistent_evidence,
        "longest_same_policy_session_streak": longest_session_streak,
        "gate_checks": gate_checks,
        "telemetry": telemetry_result,
        "claim_boundary": (
            "The two cycles are repeated measurements over 60 independent contexts. "
            "Persistent-runtime claims require a shared policy_runtime_session_id."
        ),
    }
