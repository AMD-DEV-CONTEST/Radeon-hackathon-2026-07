"""Auditable micro-mechanisms used by the public evacuation demonstration.

The module is deliberately city-agnostic. It exposes the four rules highlighted
in the public deck: distributed departure, finite egress flow, capacity-aware
admission, and population conservation.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import erf, exp, log, sqrt


@dataclass
class BlockState:
    population: float
    indoors: float
    internal: float = 0.0
    queued: float = 0.0
    sheltered: float = 0.0
    stay_put: float = 0.0

    def accounted(self) -> float:
        return self.indoors + self.internal + self.queued + self.sheltered + self.stay_put


@dataclass
class Shelter:
    capacity: float
    occupancy: float = 0.0
    open: bool = True

    @property
    def remaining(self) -> float:
        return max(0.0, self.capacity - self.occupancy) if self.open else 0.0


def departure_cdf(time_s: float, median_s: float = 180.0, sigma: float = 0.8) -> float:
    """Lognormal cumulative departure share at ``time_s``."""
    if time_s <= 0:
        return 0.0
    z = (log(time_s) - log(median_s)) / (sigma * sqrt(2.0))
    return min(1.0, max(0.0, 0.5 * (1.0 + erf(z))))


def egress_capacity(width_m: float, step_s: float, specific_flow: float = 1.3) -> float:
    """People that can cross a boundary during one simulation step."""
    return max(0.0, width_m) * max(0.0, specific_flow) * max(0.0, step_s)


def step_block(
    state: BlockState,
    shelter: Shelter,
    *,
    time_s: float,
    step_s: float,
    egress_width_m: float,
    participation: float,
    median_departure_s: float = 180.0,
    departure_sigma: float = 0.8,
) -> BlockState:
    """Advance one block while preserving population exactly.

    This compact public rule is designed for inspection and tests. The full
    simulator adds graph routing and inter-block congestion, but uses the same
    stock accounting and finite-capacity admission contract.
    """
    target_departed = state.population * max(0.0, min(1.0, participation)) * departure_cdf(
        time_s, median_departure_s, departure_sigma
    )
    already_departed = state.internal + state.queued + state.sheltered
    released = min(state.indoors, max(0.0, target_departed - already_departed))
    state.indoors -= released
    state.internal += released

    to_queue = min(state.internal, egress_capacity(egress_width_m, step_s))
    state.internal -= to_queue
    state.queued += to_queue

    admitted = min(state.queued, shelter.remaining)
    state.queued -= admitted
    state.sheltered += admitted
    shelter.occupancy += admitted

    error = state.population - state.accounted()
    if abs(error) > 1e-9:
        state.indoors += error
    return state
