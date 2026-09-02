"""Multi-agent tabular Q-learning for proactive shelter admission control.

Problem this solves
--------------------
``simulator.block_scale.BlockEvacuationSimulator`` only reroutes *after* a
shelter is completely full (see its ``_rebuild_routing``): that is a reactive,
disruptive event -- everyone already queued for that shelter has to be
redirected at once, and the reroute events recorded during a run are exactly
the moments this happens. There is no mechanism to ease off a shelter that is
filling quickly *before* it hits capacity, even though the model already
tracks everything needed to see that coming.

``BlockEvacuationSimulator.shelter_cutoff`` (a per-shelter fraction of nominal
capacity that is actually usable, default 1.0 = today's exact behaviour) is
the lever this module controls. Treating each shelter as its own agent that
periodically chooses how much headroom to reserve is a genuinely multi-agent
decision problem: shelters only observe their own state, but all of them
share one team objective (evacuate as many people as possible with as few
disruptive reroutes as possible).

Design choices, and why
-----------------------
* **Tabular Q-learning, shared table across all shelter-agents** (not one
  table per shelter, not a neural network). Shelters are homogeneous in role,
  so parameter sharing across a small number of discretised states is the
  standard, data-efficient way to train many identical agents from a handful
  of episodes -- a neural policy would need far more episodes than a full
  block-scale simulation run (several seconds each) makes practical here, and
  there is no torch available on this deployment anyway.
* **Monte Carlo, not TD, credit assignment.** An episode is one full
  simulation run (a few dozen decision epochs at most). Assigning the same
  final team reward to every (state, action) pair visited that episode is a
  standard, simple, low-variance choice at this episode length; a full TD
  bootstrap buys little here and adds bootstrap bias risk for no real gain.
* **Discretised local state**: (remaining-capacity-fraction bucket,
  recent-inbound-rate bucket, time-of-day bucket). No global state (total
  city population, other shelters' fill levels, ...) is observed --
  deliberately, since a real emergency-management system could not assume a
  shelter's own governance knows the whole city's state in real time either.

History: the reroute ratchet this depends on
----------------------------------------------
An earlier version of ``BlockEvacuationSimulator`` marked a shelter "full"
the first time it rejected any arrival, as a one-way latch: the routing tree
excluded that shelter permanently, even after its cutoff was raised back
toward 1.0. Training against that version on real Naples data showed exactly
the failure that predicts -- the learned greedy policy (reward -2.495) never
beat the do-nothing baseline of cutoff=1.0 everywhere (reward -2.345),
because *any* throttling-induced rejection paid an irreversible cost. That
result is what motivated fixing the simulator: "full" is now re-evaluated
every step against current effective capacity (capacity x shelter_cutoff), so
a shelter freed by a later cutoff increase is genuinely reachable again (see
``BlockEvacuationSimulator.step``, step 6, and
``tests/test_block_scale.py::test_shelter_cutoff_full_status_is_reversible``).
Re-run ``scripts/train_shelter_agents.py`` after that fix to see whether
proactive throttling can now actually beat the baseline; if it still can't,
that is itself the honest result to report, not a reason to keep patching
the reward function until the number looks better.

It still can't. Re-running against the fixed simulator produced a *second*
negative result: reward fell further, to -4.055, because a shelter's "full"
status now flickers between true and false as occupancy oscillates near a
controller-chosen cutoff, and every flip forces an expensive network-wide
reroute -- 135 of them, versus a handful at baseline. Fixing the
irreversibility defect was necessary and correct; it exposed a second,
distinct problem (reroute thrashing) that a hysteresis margin on the
full/not-full transition addresses in part (see
``BlockEvacuationSimulator.reopen_hysteresis`` and
``BlockScaleConfig.shelter_reopen_hysteresis``, default 0.05). Adding that
margin and re-running the identical experiment a third time reduced reroute
events from 135 to 118 (-13%) and reward from -4.055 to -3.545 -- the entire
improvement is explained by the drop in reroute count (0.03 x 17 = 0.51,
matching the reward change exactly), with unserved_fraction completely
unchanged at 0.0051. Proactive shelter-admission throttling still does not
beat doing nothing (baseline -2.345 vs -3.545, a -1.2 gap that hysteresis
narrowed from -1.71 but did not close). That remains the honest result to
report: the reroute-event penalty term responds correctly to the mechanism
it was designed to catch, but nothing in the current action space
(discrete cutoff choices in ``cutoff_actions``) gives the learned policy a
way to reserve headroom without occasionally re-triggering a reroute, so
the admission-control idea itself -- not just this bug or that bug -- does
not yet pay for its own disruption cost on this scenario.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np

from simulator.block_scale import BlockEvacuationSimulator, BlockLayer, BlockScaleConfig, ShelterSite


@dataclass(slots=True)
class ShelterAgentConfig:
    epoch_minutes: float = 10.0
    #: Discrete cutoff choices; 1.0 reproduces the simulator's default
    #: (no proactive throttling) behaviour exactly.
    cutoff_actions: tuple[float, ...] = (0.6, 0.75, 0.9, 1.0)
    #: Upper edges of the "remaining capacity fraction" buckets.
    remaining_buckets: tuple[float, ...] = (0.1, 0.3, 0.6, 1.0)
    #: Upper edges of the "inbound this epoch, as a fraction of capacity" buckets.
    inbound_buckets: tuple[float, ...] = (0.02, 0.06, 1.0)
    #: Number of coarse time-of-simulation buckets (early / mid / late).
    time_buckets: int = 3
    alpha: float = 0.25
    epsilon_start: float = 0.35
    epsilon_end: float = 0.05
    #: Reward weight on the number of reactive (post-hoc) reroute events,
    #: relative to the unserved-population fraction term.
    reroute_penalty: float = 0.03
    seed: int = 7


def _bucket(value: float, edges: tuple[float, ...]) -> int:
    for i, edge in enumerate(edges):
        if value <= edge:
            return i
    return len(edges) - 1


@dataclass(slots=True)
class EpisodeResult:
    reward: float
    unserved_fraction: float
    reroute_events: int
    final_occupancy_fraction: float
    decisions: int

    def to_dict(self) -> dict:
        return {
            "reward": round(self.reward, 5),
            "unserved_fraction": round(self.unserved_fraction, 5),
            "reroute_events": self.reroute_events,
            "final_occupancy_fraction": round(self.final_occupancy_fraction, 5),
            "decisions": self.decisions,
        }


@dataclass(slots=True)
class TrainingReport:
    episodes: int
    baseline_reward: float
    mean_reward_first_10: float
    mean_reward_last_10: float
    q_states: int
    training_ms: float
    reward_history: list[float] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "episodes": self.episodes,
            "baseline_reward": round(self.baseline_reward, 5),
            "mean_reward_first_10": round(self.mean_reward_first_10, 5),
            "mean_reward_last_10": round(self.mean_reward_last_10, 5),
            "improvement": round(self.mean_reward_last_10 - self.baseline_reward, 5),
            "q_states": self.q_states,
            "training_ms": round(self.training_ms, 1),
            "reward_history": [round(r, 5) for r in self.reward_history],
        }


class SharedQLearningShelterAgents:
    """One shared Q-table, one independent decision per shelter per epoch."""

    def __init__(self, config: ShelterAgentConfig | None = None):
        self.config = config or ShelterAgentConfig()
        self.rng = np.random.default_rng(self.config.seed)
        self.q: dict[tuple, np.ndarray] = {}

    def _state(self, remaining_frac: float, inbound_frac: float, time_frac: float) -> tuple:
        cfg = self.config
        r = _bucket(remaining_frac, cfg.remaining_buckets)
        i = _bucket(inbound_frac, cfg.inbound_buckets)
        t = min(cfg.time_buckets - 1, int(time_frac * cfg.time_buckets))
        return (r, i, t)

    def _q_row(self, state: tuple) -> np.ndarray:
        row = self.q.get(state)
        if row is None:
            row = np.zeros(len(self.config.cutoff_actions))
            self.q[state] = row
        return row

    def _select_action(self, state: tuple, epsilon: float) -> int:
        if epsilon > 0 and self.rng.random() < epsilon:
            return int(self.rng.integers(len(self.config.cutoff_actions)))
        row = self._q_row(state)
        best = np.flatnonzero(row == row.max())
        return int(self.rng.choice(best))

    def run_episode(
        self,
        layer: BlockLayer,
        shelters: list[ShelterSite],
        sim_config: BlockScaleConfig,
        *,
        train: bool,
        epsilon: float = 0.0,
    ) -> EpisodeResult:
        """Run one full block-scale simulation, making a cutoff decision for
        every shelter at every ``epoch_minutes`` boundary.

        ``shelters`` is passed fresh each call (their ``occupants`` field is
        mutated by the simulator), so callers should pass freshly constructed
        ``ShelterSite`` instances or accept that occupancy is reset by
        ``BlockEvacuationSimulator`` regardless.
        """
        cfg = self.config
        sim = BlockEvacuationSimulator(layer, shelters, sim_config)
        epoch_steps = max(1, int(round(cfg.epoch_minutes * 60 / sim_config.step_seconds)))
        total_steps = int(sim_config.duration_minutes * 60 // sim_config.step_seconds)

        visited: list[tuple[tuple, int]] = []
        last_occupancy = np.zeros(len(sim.shelters))

        for step in range(total_steps):
            if step % epoch_steps == 0:
                time_frac = step / max(total_steps, 1)
                for s_idx, shelter in enumerate(sim.shelters):
                    remaining_frac = 1.0 - sim.shelter_occupancy[s_idx] / max(shelter.capacity, 1e-9)
                    inbound_frac = (sim.shelter_occupancy[s_idx] - last_occupancy[s_idx]) / max(shelter.capacity, 1e-9)
                    state = self._state(max(0.0, remaining_frac), max(0.0, inbound_frac), time_frac)
                    action_idx = self._select_action(state, epsilon if train else 0.0)
                    sim.shelter_cutoff[s_idx] = cfg.cutoff_actions[action_idx]
                    if train:
                        visited.append((state, action_idx))
                last_occupancy = sim.shelter_occupancy.copy()
            sim.step()

        unserved_fraction = float(sim.layer.population[sim.unserved_mask].sum()) / max(
            float(sim.layer.population.sum()), 1e-9)
        reroute_events = len(sim._reroute_events)
        reward = -(unserved_fraction + cfg.reroute_penalty * reroute_events)

        if train:
            for state, action_idx in visited:
                row = self._q_row(state)
                row[action_idx] += cfg.alpha * (reward - row[action_idx])

        final_occ = float(sim.shelter_occupancy.sum()) / max(sum(s.capacity for s in sim.shelters), 1e-9)
        return EpisodeResult(
            reward=reward,
            unserved_fraction=unserved_fraction,
            reroute_events=reroute_events,
            final_occupancy_fraction=final_occ,
            decisions=len(visited),
        )

    def run_baseline_episode(self, layer: BlockLayer, shelters: list[ShelterSite],
                             sim_config: BlockScaleConfig) -> EpisodeResult:
        """Run with ``shelter_cutoff`` left at its default 1.0 everywhere --
        i.e. exactly what an untouched ``BlockEvacuationSimulator`` does, no
        agent involved. This is the fixed comparison point for training
        improvement, not something drawn from the (possibly untrained,
        arbitrary-tie-breaking) Q-table.
        """
        sim = BlockEvacuationSimulator(layer, shelters, sim_config)
        sim.run()
        unserved_fraction = float(sim.layer.population[sim.unserved_mask].sum()) / max(
            float(sim.layer.population.sum()), 1e-9)
        reroute_events = len(sim._reroute_events)
        reward = -(unserved_fraction + self.config.reroute_penalty * reroute_events)
        final_occ = float(sim.shelter_occupancy.sum()) / max(sum(s.capacity for s in sim.shelters), 1e-9)
        return EpisodeResult(reward=reward, unserved_fraction=unserved_fraction,
                             reroute_events=reroute_events, final_occupancy_fraction=final_occ,
                             decisions=0)

    def train(
        self,
        layer: BlockLayer,
        make_shelters,
        sim_config: BlockScaleConfig,
        episodes: int = 30,
    ) -> TrainingReport:
        """``make_shelters`` is a zero-arg factory returning fresh
        ``ShelterSite`` instances, since the simulator mutates their
        ``occupants`` field in place each run."""
        started = perf_counter()
        cfg = self.config

        baseline = self.run_baseline_episode(layer, make_shelters(), sim_config)

        history: list[float] = []
        for episode in range(episodes):
            epsilon = cfg.epsilon_start + (cfg.epsilon_end - cfg.epsilon_start) * (episode / max(episodes - 1, 1))
            result = self.run_episode(layer, make_shelters(), sim_config, train=True, epsilon=epsilon)
            history.append(result.reward)

        head = history[:10] or [baseline.reward]
        tail = history[-10:] or [baseline.reward]
        return TrainingReport(
            episodes=episodes,
            baseline_reward=baseline.reward,
            mean_reward_first_10=sum(head) / len(head),
            mean_reward_last_10=sum(tail) / len(tail),
            q_states=len(self.q),
            training_ms=(perf_counter() - started) * 1000,
            reward_history=history,
        )

    def save(self, path: str | Path) -> None:
        import json
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        serialisable = {"|".join(map(str, k)): v.tolist() for k, v in self.q.items()}
        out.write_text(json.dumps({
            "config": {
                "epoch_minutes": self.config.epoch_minutes,
                "cutoff_actions": list(self.config.cutoff_actions),
                "remaining_buckets": list(self.config.remaining_buckets),
                "inbound_buckets": list(self.config.inbound_buckets),
                "time_buckets": self.config.time_buckets,
            },
            "q_table": serialisable,
        }, indent=2), encoding="utf-8")
