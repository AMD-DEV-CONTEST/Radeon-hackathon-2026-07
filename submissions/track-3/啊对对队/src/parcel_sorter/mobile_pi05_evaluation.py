"""Paired promotion statistics for PI0.5 mobile manipulation campaigns."""

from __future__ import annotations

import math
from typing import Any, Iterable

from .metrics import wilson_interval


def exact_mcnemar_p(improvements: int, regressions: int) -> float:
    """Two-sided exact McNemar p-value for discordant paired outcomes."""

    if min(improvements, regressions) < 0:
        raise ValueError("discordant counts cannot be negative")
    discordant = improvements + regressions
    if discordant == 0:
        return 1.0
    tail = sum(
        math.comb(discordant, index) for index in range(min(improvements, regressions) + 1)
    ) / (2**discordant)
    return min(1.0, 2.0 * tail)


def exact_binomial_greater_p(
    successes: int,
    trials: int,
    *,
    null_success_rate: float = 0.90,
) -> float:
    """One-sided exact p-value for H0: p <= null_success_rate."""

    if trials <= 0 or not 0 <= successes <= trials:
        raise ValueError("successes must be within a positive trial count")
    if not 0.0 < null_success_rate < 1.0:
        raise ValueError("null success rate must be in (0, 1)")
    return sum(
        math.comb(trials, count)
        * null_success_rate**count
        * (1.0 - null_success_rate) ** (trials - count)
        for count in range(successes, trials + 1)
    )


def required_exact_binomial_successes(
    trials: int,
    *,
    null_success_rate: float = 0.90,
    alpha: float = 0.05,
) -> int:
    """Smallest success count that rejects the one-sided binomial null."""

    if trials <= 0:
        raise ValueError("trials must be positive")
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must be in (0, 1)")
    for successes in range(trials + 1):
        if exact_binomial_greater_p(
            successes,
            trials,
            null_success_rate=null_success_rate,
        ) < alpha:
            return successes
    return trials + 1


def compare_paired_pi05_runs(
    baseline_runs: Iterable[dict[str, Any]],
    candidate_runs: Iterable[dict[str, Any]],
    *,
    target_success_rate: float = 0.90,
) -> dict[str, Any]:
    baseline = tuple(baseline_runs)
    candidate = tuple(candidate_runs)
    if not 0.0 < target_success_rate <= 1.0:
        raise ValueError("target success rate must be in (0, 1]")
    if len(baseline) != len(candidate) or not baseline:
        raise ValueError("paired campaigns must have the same positive trial count")
    baseline_ids = tuple(str(run.get("episode_id")) for run in baseline)
    candidate_ids = tuple(str(run.get("episode_id")) for run in candidate)
    if len(set(baseline_ids)) != len(baseline_ids) or baseline_ids != candidate_ids:
        raise ValueError("paired campaigns must contain the same unique episode order")

    baseline_successes = sum(bool(run.get("success")) for run in baseline)
    candidate_successes = sum(bool(run.get("success")) for run in candidate)
    improvements = sum(
        not bool(old.get("success")) and bool(new.get("success"))
        for old, new in zip(baseline, candidate, strict=True)
    )
    regressions = sum(
        bool(old.get("success")) and not bool(new.get("success"))
        for old, new in zip(baseline, candidate, strict=True)
    )
    trials = len(baseline)
    required_successes = math.ceil(target_success_rate * trials - 1e-12)
    baseline_force_violations = sum(_force_violation(run) for run in baseline)
    candidate_force_violations = sum(_force_violation(run) for run in candidate)
    candidate_vla_qualified = sum(bool(run.get("vla_qualified")) for run in candidate)
    candidate_material = sum(bool(run.get("material_pi05_residual")) for run in candidate)
    candidate_authorities = tuple(
        str(
            run.get("policy_authority")
            or (run.get("policy") or {}).get("policy_authority")
            or "unknown"
        )
        for run in candidate
    )
    candidate_expert_reference_runs = sum(
        bool(
            run.get("expert_reference_used")
            or (run.get("policy") or {}).get("expert_reference_used")
        )
        for run in candidate
    )
    candidate_pure_absolute_vla_runs = sum(
        authority == "absolute_vla_action_candidate"
        and (
            run.get("system_control_class")
            or (run.get("policy") or {}).get("system_control_class")
        )
        == "pure_vla"
        and (run.get("policy") or {}).get("absolute_full_authority") is True
        and int(
            run.get("task_action_correction_count")
            or (run.get("policy") or {}).get("task_action_correction_count")
            or 0
        )
        == 0
        and not bool(
            run.get("expert_reference_used")
            or (run.get("policy") or {}).get("expert_reference_used")
        )
        for authority, run in zip(candidate_authorities, candidate, strict=True)
    )
    candidate_hybrid_runs = sum(
        authority == "hybrid_expert_reference_plus_vla_residual"
        for authority in candidate_authorities
    )
    authority_known = all(
        authority
        in {
            "absolute_vla_action_candidate",
            "hybrid_expert_reference_plus_vla_residual",
        }
        for authority in candidate_authorities
    )
    candidate_fallbacks = sum(
        int((run.get("policy") or {}).get("expert_fallback_count") or 0)
        for run in candidate
    )
    candidate_emergency_stops = sum(
        int((run.get("policy") or {}).get("emergency_stop_count") or 0)
        for run in candidate
    )
    baseline_wilson = wilson_interval(baseline_successes, trials)
    candidate_wilson = wilson_interval(candidate_successes, trials)
    paper_claim_required_successes = required_exact_binomial_successes(
        trials, null_success_rate=target_success_rate
    )
    paper_claim_exact_p = exact_binomial_greater_p(
        candidate_successes,
        trials,
        null_success_rate=target_success_rate,
    )
    shared_safety_checks = bool(
        candidate_force_violations <= baseline_force_violations
        and candidate_vla_qualified == trials
        and candidate_fallbacks == 0
        and candidate_emergency_stops == 0
        and candidate_material == trials
        and authority_known
    )
    promotion = bool(
        candidate_successes >= required_successes
        and shared_safety_checks
    )
    paper_claim_gate = bool(
        candidate_successes >= paper_claim_required_successes
        and paper_claim_exact_p < 0.05
        and shared_safety_checks
    )
    pure_vla_promotion = bool(
        promotion
        and candidate_pure_absolute_vla_runs == trials
        and candidate_expert_reference_runs == 0
    )
    pure_vla_paper_claim_gate = bool(
        paper_claim_gate and pure_vla_promotion
    )
    if candidate_pure_absolute_vla_runs == trials:
        claim_scope = "absolute_vla_action_candidate"
    elif candidate_hybrid_runs == trials:
        claim_scope = "hybrid_expert_reference_plus_vla_residual"
    else:
        claim_scope = "mixed_policy_authority_system"
    return {
        "trials": trials,
        "target_success_rate": target_success_rate,
        "required_successes": required_successes,
        "baseline_successes": baseline_successes,
        "candidate_successes": candidate_successes,
        "baseline_success_rate": baseline_successes / trials,
        "candidate_success_rate": candidate_successes / trials,
        "success_rate_difference": (candidate_successes - baseline_successes) / trials,
        "baseline_wilson_95": list(baseline_wilson),
        "candidate_wilson_95": list(candidate_wilson),
        "discordant_improvements": improvements,
        "discordant_regressions": regressions,
        "mcnemar_exact_two_sided_p": exact_mcnemar_p(improvements, regressions),
        "baseline_force_violations": baseline_force_violations,
        "candidate_force_violations": candidate_force_violations,
        "candidate_vla_qualified_runs": candidate_vla_qualified,
        "candidate_material_residual_runs": candidate_material,
        "candidate_policy_authorities": sorted(set(candidate_authorities)),
        "candidate_expert_reference_runs": candidate_expert_reference_runs,
        "candidate_hybrid_runs": candidate_hybrid_runs,
        "candidate_pure_absolute_vla_runs": candidate_pure_absolute_vla_runs,
        "candidate_expert_fallback_count": candidate_fallbacks,
        "candidate_emergency_stop_count": candidate_emergency_stops,
        "promotion_gate_passed": promotion,
        "pure_vla_promotion_gate_passed": pure_vla_promotion,
        "paper_claim": {
            "null_hypothesis": f"p <= {target_success_rate:.2f}",
            "alternative_hypothesis": f"p > {target_success_rate:.2f}",
            "alpha": 0.05,
            "required_successes": paper_claim_required_successes,
            "exact_binomial_greater_p": paper_claim_exact_p,
            "claim_scope": claim_scope,
            "gate_passed": paper_claim_gate,
        },
        "pure_vla_paper_claim": {
            "required_pure_absolute_vla_runs": trials,
            "pure_absolute_vla_runs": candidate_pure_absolute_vla_runs,
            "expert_reference_runs": candidate_expert_reference_runs,
            "gate_passed": pure_vla_paper_claim_gate,
        },
    }


def _force_violation(run: dict[str, Any]) -> bool:
    suction = run.get("suction") or {}
    cradle = (run.get("cradle") or {}).get("physical") or {}
    return max(
        float(suction.get("max_contact_force_n") or 0.0),
        float(suction.get("max_suction_force_n") or 0.0),
        float(cradle.get("max_contact_force_n") or 0.0),
    ) >= 35.0
