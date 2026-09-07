"""Scalarizes multi-trial episode metrics into one fitness number.

Project brief S5: reward = task success + grasp stability + contact stress, not
success alone -- a bad gripper that succeeds by luck must not score like a good one,
and a design that is gentler at equal success rate is a real, reportable result (the
"stress/success frontier" in S7), not noise to average away.

All four terms are computed from `sim_episode.EpisodeMetrics`, averaged across a
candidate's full trial set (see evaluate.py for how that trial set is built).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# Weights: success dominates (it is ground truth -- S5.1), stability is the term that
# makes the reward *responsive to geometry* (S5.2), stress/slip penalize a design that
# only succeeds by clamping down hard rather than holding securely.
W_SUCCESS = 1.0
W_STABILITY = 0.3
W_STRESS = 0.15
W_SLIP = 0.15

# Normalization references (N, m) -- chosen from the observed force/slip scale of a
# firm, successful grasp in this task (~10-15 N, <1 cm slip); see sim_episode smoke
# tests. Not tuned per-design -- these are fixed across every candidate and the
# baseline alike, which is what keeps the comparison in S6/A4 symmetric.
STRESS_REF_N = 20.0
SLIP_REF_M = 0.05


@dataclass(frozen=True)
class TrialAggregate:
    n_trials: int
    success_rate: float
    mean_contact_uptime: float
    mean_peak_force: float
    mean_max_slip: float


def aggregate_trials(metrics: list) -> TrialAggregate:
    """`metrics`: list of `sim_episode.EpisodeMetrics`, one per trial."""
    n = len(metrics)
    if n == 0:
        return TrialAggregate(0, 0.0, 0.0, 0.0, 0.0)
    return TrialAggregate(
        n_trials=n,
        success_rate=float(np.mean([m.success for m in metrics])),
        mean_contact_uptime=float(np.mean([m.contact_uptime_frac for m in metrics])),
        mean_peak_force=float(np.mean([m.peak_contact_force for m in metrics])),
        mean_max_slip=float(np.mean([m.max_slip for m in metrics])),
    )


def fitness(agg: TrialAggregate) -> float:
    stress_penalty = float(np.clip(agg.mean_peak_force / STRESS_REF_N, 0.0, 2.0))
    slip_penalty = float(np.clip(agg.mean_max_slip / SLIP_REF_M, 0.0, 2.0))
    return (
        W_SUCCESS * agg.success_rate
        + W_STABILITY * agg.mean_contact_uptime
        - W_STRESS * stress_penalty
        - W_SLIP * slip_penalty
    )
