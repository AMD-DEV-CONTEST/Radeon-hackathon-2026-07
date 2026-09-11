"""Small, deterministic VLA decision harness.

This is deliberately a policy-independent layer. It mirrors the useful part
of a VLA evaluation harness: stable interfaces, candidate-level telemetry and
reproducible selection rules. It does not claim to be the upstream
``vla-evaluation-harness`` implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class HarnessCandidate:
    scale: float
    target_position_m: tuple[float, float, float]
    residual_m: float
    progress_ratio: float
    score: float
    safe: bool
    reason: str


@dataclass(frozen=True)
class HarnessDecision:
    selected: HarnessCandidate
    candidates: tuple[HarnessCandidate, ...]
    fallback_to_expert: bool


def select_residual_candidate(
    *,
    current_position_m: tuple[float, float, float],
    expert_target_m: tuple[float, float, float],
    vla_target_m: tuple[float, float, float],
    residual_limit_m: float,
    min_progress_ratio: float,
    force_n: float,
    force_limit_n: float,
    recovery_active: bool = False,
    candidate_scales: tuple[float, ...] = (-0.5, 0.0, 0.5, 1.0),
) -> HarnessDecision:
    """Select a fail-closed residual using a deterministic generator-verifier loop.

    The learned residual is quarantined during the first attempt.  After the
    supervisor declares a retry, the harness may only shorten the expert move;
    it never amplifies motion toward a contact surface.  This turns retry state
    into an explicit causal gate instead of treating every VLA proposal as an
    opportunity to move farther.
    """

    if residual_limit_m < 0 or not math.isfinite(residual_limit_m):
        raise ValueError("residual_limit_m must be finite and non-negative")
    if not 0.0 < min_progress_ratio <= 1.0:
        raise ValueError("min_progress_ratio must be in (0, 1]")
    if not 0.0 < force_limit_n:
        raise ValueError("force_limit_n must be positive")
    if not candidate_scales:
        raise ValueError("candidate_scales cannot be empty")

    motion = tuple(
        target - current
        for target, current in zip(expert_target_m, current_position_m, strict=True)
    )
    motion_norm = _norm(motion)
    if motion_norm <= 1e-12:
        expert = HarnessCandidate(
            scale=0.0,
            target_position_m=expert_target_m,
            residual_m=0.0,
            progress_ratio=1.0,
            score=1.0,
            safe=force_n < force_limit_n,
            reason="zero expert motion",
        )
        return HarnessDecision(expert, (expert,), fallback_to_expert=True)
    direction = tuple(value / motion_norm for value in motion)
    raw_residual = tuple(
        proposed - nominal
        for proposed, nominal in zip(vla_target_m, expert_target_m, strict=True)
    )
    projected = sum(offset * axis for offset, axis in zip(raw_residual, direction, strict=True))
    hard_limit = min(residual_limit_m, motion_norm * (1.0 - min_progress_ratio))
    projected = max(-residual_limit_m, min(residual_limit_m, projected))
    candidates = []
    for scale in candidate_scales:
        if not math.isfinite(scale):
            raise ValueError("candidate scales must be finite")
        residual = max(-hard_limit, min(hard_limit, projected * float(scale)))
        target = tuple(
            nominal + residual * axis
            for nominal, axis in zip(expert_target_m, direction, strict=True)
        )
        progress_ratio = (motion_norm + residual) / motion_norm
        is_expert = abs(float(scale)) <= 1e-12
        first_attempt_gate = recovery_active or is_expert
        no_forward_amplification = residual <= 1e-12
        safe = (
            force_n < force_limit_n
            and progress_ratio + 1e-9 >= min_progress_ratio
            and first_attempt_gate
            and (not recovery_active or no_forward_amplification)
        )
        normalized_backoff = (
            max(0.0, -residual) / max(residual_limit_m, 1e-9)
        )
        score = (
            1.0
            + (0.06 * normalized_backoff if recovery_active else 0.0)
            - 0.02 * abs(residual) / max(residual_limit_m, 1e-9)
            - (10.0 if not safe else 0.0)
        )
        if not first_attempt_gate:
            reason = "quarantined until supervisor retry"
        elif recovery_active and not no_forward_amplification:
            reason = "forward residual blocked during recovery"
        elif force_n >= force_limit_n or progress_ratio + 1e-9 < min_progress_ratio:
            reason = "force/progress gate"
        else:
            reason = "verified recovery residual" if recovery_active else "verified expert"
        candidates.append(
            HarnessCandidate(
                scale=float(scale),
                target_position_m=target,
                residual_m=abs(residual),
                progress_ratio=progress_ratio,
                score=score,
                safe=safe,
                reason=reason,
            )
        )
    safe_candidates = [candidate for candidate in candidates if candidate.safe]
    if not safe_candidates:
        expert = next(candidate for candidate in candidates if candidate.scale == 0.0)
        return HarnessDecision(expert, tuple(candidates), fallback_to_expert=True)
    selected = max(safe_candidates, key=lambda candidate: (candidate.score, -candidate.residual_m))
    return HarnessDecision(
        selected,
        tuple(candidates),
        fallback_to_expert=selected.scale == 0.0,
    )


def _norm(values: tuple[float, ...]) -> float:
    return math.sqrt(sum(value * value for value in values))
