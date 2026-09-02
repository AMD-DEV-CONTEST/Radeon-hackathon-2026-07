"""Grasp-candidate generation and the first explainable Policy baseline."""

from __future__ import annotations

from itertools import product

from .models import GraspCandidate, ScoredGrasp


def generate_candidates(
    *,
    obstacle_clearance_m: float,
    previous_failures: int = 0,
) -> list[GraspCandidate]:
    offsets = (-0.015, 0.0, 0.015)
    yaws = (-20.0, 0.0, 20.0)
    heights = (0.08, 0.10)
    return [
        GraspCandidate(x, y, yaw, height, obstacle_clearance_m, previous_failures)
        for x, y, yaw, height in product(offsets, offsets, yaws, heights)
    ]


class HeuristicGraspPolicy:
    """Score actions before the learned Policy is trained.

    The interface intentionally accepts a batch so its learned replacement can
    evaluate candidates in parallel on an AMD GPU.
    """

    def score(self, candidate: GraspCandidate) -> ScoredGrasp:
        score = 1.0
        reasons: list[str] = []

        centering_penalty = 7.0 * (
            abs(candidate.offset_x_m) + abs(candidate.offset_y_m)
        )
        score -= centering_penalty
        reasons.append(f"centering -{centering_penalty:.3f}")

        yaw_penalty = abs(candidate.yaw_deg) / 200.0
        score -= yaw_penalty
        reasons.append(f"yaw -{yaw_penalty:.3f}")

        if candidate.obstacle_clearance_m < 0.08:
            score -= 0.55
            reasons.append("unsafe clearance -0.550")
        else:
            clearance_bonus = min(candidate.obstacle_clearance_m, 0.20)
            score += clearance_bonus
            reasons.append(f"clearance +{clearance_bonus:.3f}")

        if candidate.previous_failures:
            # After a miss, avoid repeatedly selecting the exact center grasp.
            if candidate.offset_x_m == 0 and candidate.offset_y_m == 0:
                score -= 0.30
                reasons.append("repeated center after failure -0.300")
            else:
                score += 0.08
                reasons.append("recovery diversity +0.080")

        return ScoredGrasp(candidate, round(score, 6), tuple(reasons))

    def rank(self, candidates: list[GraspCandidate]) -> list[ScoredGrasp]:
        return sorted(
            (self.score(candidate) for candidate in candidates),
            key=lambda item: item.score,
            reverse=True,
        )

