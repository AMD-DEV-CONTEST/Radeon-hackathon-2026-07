"""Shelter site-selection: where should k *new* shelters go?

Why greedy marginal-gain search, not an RL agent
--------------------------------------------------
Choosing k new shelter locations out of a candidate pool to minimise unserved
population is a facility-location / coverage problem: the objective (people
served) is evaluated by a fixed, deterministic function of the chosen set --
the block-scale simulator -- with no sequential *dynamics* an agent needs to
react to (unlike ``rl.shelter_agents``, where shelters actually fill and
empty over simulated time and a controller reacts to that). Wrapping this in
an RL formulation would mean inventing an environment with no real state
transitions to justify it.

The right tool here is greedy marginal-gain selection: repeatedly add
whichever remaining candidate reduces unserved population the most, given
what's already been chosen. For the class of objectives this is (coverage,
monotone and submodular -- adding a shelter never hurts, and its marginal
benefit only shrinks as more shelters are already placed), greedy is
guaranteed within (1 - 1/e) ~= 63% of the true optimum for a fixed budget,
and it is what the facility-location literature actually uses. It is also
`k x |candidates|` simulator evaluations instead of an exponential search, and
every one of those evaluations is the *real* engine -- not an invented,
correlated-but-not-identical reward proxy.

Nothing here is a validated site-selection recommendation. It is a search
procedure over whatever candidate list is supplied (e.g. currently-unserved
block centroids, vacant-land parcels, an official list of proposed sites);
the result is only as good as that candidate list and the same population/
shelter assumptions the rest of ``simulator.block_scale`` already declares.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from simulator.block_scale import BlockEvacuationSimulator, BlockLayer, BlockScaleConfig, ShelterSite


@dataclass(slots=True)
class SitingStep:
    rank: int
    shelter_id: str
    lon: float
    lat: float
    unserved_population_before: float
    unserved_population_after: float
    marginal_gain: float

    def to_dict(self) -> dict:
        return {
            "rank": self.rank, "shelter_id": self.shelter_id,
            "lon": round(self.lon, 6), "lat": round(self.lat, 6),
            "unserved_population_before": round(self.unserved_population_before, 1),
            "unserved_population_after": round(self.unserved_population_after, 1),
            "marginal_gain": round(self.marginal_gain, 1),
        }


@dataclass(slots=True)
class SitingResult:
    baseline_unserved_population: float
    final_unserved_population: float
    chosen: list[ShelterSite]
    steps: list[SitingStep] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "method": "greedy marginal-gain search (submodular facility location), "
                      "not a learned policy -- see module docstring for why",
            "baseline_unserved_population": round(self.baseline_unserved_population, 1),
            "final_unserved_population": round(self.final_unserved_population, 1),
            "total_reduction": round(self.baseline_unserved_population - self.final_unserved_population, 1),
            "chosen": [{"shelter_id": s.shelter_id, "lon": round(s.lon, 6), "lat": round(s.lat, 6),
                       "capacity": s.capacity} for s in self.chosen],
            "steps": [s.to_dict() for s in self.steps],
        }


def _unserved_population(layer: BlockLayer, shelters: list[ShelterSite],
                         config: BlockScaleConfig, blocked_blocks=()) -> float:
    sim = BlockEvacuationSimulator(layer, shelters, config, blocked_blocks=blocked_blocks)
    sim.run()
    return float(sim.layer.population[sim.unserved_mask].sum())


def greedy_shelter_siting(
    layer: BlockLayer,
    base_shelters: list[ShelterSite],
    candidates: list[ShelterSite],
    config: BlockScaleConfig,
    k: int,
    *,
    blocked_blocks=(),
    progress: Callable[[int, int, str], None] | None = None,
) -> SitingResult:
    """Greedily pick up to ``k`` candidates that most reduce unserved population.

    ``config.target_population`` must be ``None`` (or every call must use a
    fresh, unmutated ``layer``): ``BlockEvacuationSimulator`` rescales
    ``layer.population`` in place the first time it sees a ``target_population``,
    and repeated rescaling of the same array would silently compound.

    Stops early if no remaining candidate improves on the current best (all
    remaining marginal gains are <= 0), rather than padding the result with
    picks that don't help.
    """
    if config.target_population is not None:
        raise ValueError("greedy_shelter_siting requires target_population=None; "
                         "rescale the layer's population once, before calling this.")

    remaining = list(candidates)
    chosen: list[ShelterSite] = []
    steps: list[SitingStep] = []

    current_unserved = _unserved_population(layer, base_shelters, config, blocked_blocks)
    baseline = current_unserved

    for step_idx in range(k):
        if not remaining:
            break
        best_candidate = None
        best_unserved = current_unserved
        for i, cand in enumerate(remaining):
            if progress:
                progress(step_idx, i, cand.shelter_id)
            trial = base_shelters + chosen + [cand]
            unserved = _unserved_population(layer, trial, config, blocked_blocks)
            if unserved < best_unserved:
                best_unserved = unserved
                best_candidate = cand

        if best_candidate is None:
            break  # no remaining candidate helps at all; stop rather than pad the result

        gain = current_unserved - best_unserved
        steps.append(SitingStep(
            rank=step_idx + 1, shelter_id=best_candidate.shelter_id,
            lon=best_candidate.lon, lat=best_candidate.lat,
            unserved_population_before=current_unserved,
            unserved_population_after=best_unserved,
            marginal_gain=gain,
        ))
        chosen.append(best_candidate)
        remaining.remove(best_candidate)
        current_unserved = best_unserved

    return SitingResult(
        baseline_unserved_population=baseline,
        final_unserved_population=current_unserved,
        chosen=chosen,
        steps=steps,
    )
