"""Full-population individual evacuation, vectorised on GPU.

Every resident is an individual with their own position, target, fatigue and
role -- but no resident is a Python object. State lives in parallel tensors so
large populations can remain device-resident alongside block fields, routing
tables, and the local model.

(An earlier version of this file claimed 27 B/agent. That covered kinematics
only and could not represent mutual help, information provenance or individual
belief -- see docs/ROADMAP_FULL_SCALE_AGENTS.md section 0b.)

The design decision that makes this tractable is that **agents interact
through the block they are standing in, not with each other**. A person can
see the crowd around them, hear a neighbour, and receive a broadcast that
covers where they are; none of that is a point-to-point link. Modelling it
as a shared per-block information field turns an O(n^2) interaction problem
into O(n + n_blocks * n_candidates), and simultaneously encodes the honest
assumption that nobody knows the queue at a shelter 20 km away.

See docs/FULL_SCALE_AGENT_METHODOLOGY.md for the full rationale and
docs/AGENT_DECISION_RULES.md for the individual rules R1-R6 this implements.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

try:
    import torch
    _HAS_TORCH = True
except ImportError:  # pragma: no cover - torch is optional for CPU fallback
    torch = None  # type: ignore
    _HAS_TORCH = False


# Agent state enum, stored as int8.
S_INDOORS, S_TO_BOUNDARY, S_QUEUED, S_TRANSIT, S_SHELTERED, S_GAVEUP = range(6)

# Role enum, stored as int8.
#
# Leadership is tiered so a deployment can represent district, subdistrict,
# community, and neighborhood roles without assuming a flat leader pool.
#
# LLM coordination is a PROPERTY OF THE TOP TIERS, not a separate role: a
# district or subdistrict commander is a leader who happens to reason with a
# language model instead of a fixed rule.
R_CIVILIAN, R_SLOW, R_HELPER, R_GRID, R_COMMUNITY, R_SUBDISTRICT, R_DISTRICT = range(7)

#: Tiers whose decisions are driven by the local LLM rather than the rule
#: policy. Everything above the community tier reasons with the model.
LLM_TIERS = (R_SUBDISTRICT, R_DISTRICT)

#: Broadcast reach and belief-writing weight by tier. A higher tier is heard
#: further and trusted more, which is what makes leadership matter: a leader
#: changes not their own path but the beliefs of thousands around them.
TIER_BROADCAST = {
    R_GRID:        (1, 1.5),
    R_COMMUNITY:   (2, 2.0),
    R_SUBDISTRICT: (4, 3.0),
    R_DISTRICT:    (8, 4.0),
}

# Event stream type codes.
E_DEPART, E_RETARGET, E_ARRIVE, E_REJECTED, E_GAVEUP, E_HELPED = range(6)


@dataclass
class SwarmConfig:
    """Behavioural and numerical parameters.

    Behavioural parameters are literature-range scenario defaults. They MUST
    be reported as assumptions and swept for sensitivity.
    """

    step_seconds: float = 10.0
    duration_minutes: int = 180

    # -- R1 departure (lognormal, matches the block-scale engine) --
    departure_median_s: float = 180.0
    departure_sigma: float = 0.8

    # -- R2 destination choice --
    #: How many nearest shelters an agent will even consider. Nobody evaluates
    #: every shelter in a city; this is both realism and the main memory
    #: lever on the belief field.
    n_candidates: int = 32
    #: Logit temperature. tau -> 0 reproduces deterministic nearest-shelter
    #: choice (i.e. today's behaviour); larger values spread a block's people
    #: across several nearby shelters. THIS is what produces splitting.
    tau: float = 0.35
    #: Weight on believed queueing relative to travel time.
    beta: float = 0.5

    # -- R3 en-route re-evaluation --
    #: Penalty for changing your mind: sunk distance, disorientation, being
    #: carried by the crowd. Without it agents oscillate between two shelters.
    lambda_switch: float = 300.0
    #: A switch must beat staying by at least this margin. Same hysteresis
    #: lesson as shelter reopen and the RL admission controller.
    theta: float = 120.0
    max_switches: int = 3

    # -- R4 information --
    #: Share of residents who know their nearest shelter when the quake hits.
    #: This is a scenario assumption to be swept, and it is the single
    #: parameter that decides whether the leader
    #: tier has anything to contribute.
    frac_knows_one: float = 0.30
    #: Share who also know the second-nearest. Subset of the above.
    frac_knows_two: float = 0.08
    #: Chance per step that someone in a block picks up what the block knows.
    word_of_mouth: float = 0.03
    #: Chance per step that block knowledge spreads to an adjacent block.
    knowledge_spread: float = 0.08
    #: Per-step decay of a block's belief toward its prior (staleness).
    belief_decay: float = 0.02
    #: Fraction of a block's belief that diffuses to neighbours each step.
    belief_diffusion: float = 0.15
    #: Per-step decay of the trail the lost follow. An instantaneous headcount
    #: leaves nothing behind, so a leader who passed thirty seconds ago is
    #: invisible -- which is why the first bellwether test measured no effect
    #: at any weight. A decaying trail accumulates instead: walk the same route
    #: for ten minutes and it becomes a visible path. 0 disables the trail and
    #: falls back to the instantaneous crowd.
    trail_decay: float = 0.03
    #: How many ordinary walkers a moving leader is worth in the field that
    #: lost people follow. This is visibility and authority, not body mass: a
    #: person in a hi-vis vest walking with purpose is noticed and followed,
    #: which is the bellwether effect. 1.0 disables it.
    bellwether_weight: float = 1.0
    #: Speed multiplier for someone with no destination. Not knowing where to
    #: go does not just add distance, it adds hesitation: stopping at corners,
    #: doubling back, waiting to see which way the crowd turns.
    search_speed_factor: float = 0.75
    #: Leader broadcast reaches this many hops.
    leader_radius_hops: int = 3
    leader_weight: float = 3.0

    # -- R6 give up --
    #: Walking seconds beyond which an agent seeks informal refuge instead.
    give_up_after_s: float = 7200.0

    # -- physics (shared with the block-scale engine) --
    free_flow_speed_mps: float = 1.34
    jam_density: float = 5.4
    specific_flow: float = 1.3

    # -- roles --
    #: Share of the population that walks slowly and tires faster (elderly,
    #: mobility-impaired, accompanying small children).
    frac_slow: float = 0.18
    #: Share able to assist a slower neighbour in the same block.
    frac_helper: float = 0.10
    #: Generic deployment defaults; replace them with the target city's
    #: documented institutional structure.
    n_district: int = 16
    n_subdistrict: int = 256
    n_community: int = 2_048
    n_grid: int = 30_000
    #: Simulated minutes between successive LLM decisions for an LLM-driven
    #: leader. Wall time decreases when the llama.cpp server batches concurrent
    #: slots; the exact throughput depends on the selected local model.
    llm_decision_interval_min: float = 10.0
    #: How many of the community-tier leaders are LLM-driven rather than
    #: rule-driven. Cost is approximately linear in this number, and the
    #: LLM tier is what dominates wall clock, so this is the main cost knob.
    n_llm_community: int = 0
    #: Share of people in a block who act on a broadcast that reaches it. A
    #: loudspeaker does not redirect everyone who hears it: some are already
    #: committed, some do not believe it, some are helping someone else.
    broadcast_reach: float = 0.35
    #: Local density (persons/m2) above which someone reconsiders on their own,
    #: without being told anything.
    rethink_density: float = 1.2
    #: Minimum seconds between two self-initiated reconsiderations, so a jammed
    #: block does not make its occupants re-plan every single step.
    rethink_cooldown_s: float = 300.0

    seed: int = 42
    device: str = "auto"          # "auto" | "cuda" | "cpu"
    #: Re-evaluate at most this fraction of eligible agents per step, so the
    #: expensive decision kernel runs on a slice rather than everyone.
    reeval_fraction: float = 0.05


class AgentSwarm:
    """Vectorised individual-agent evacuation over a BlockLayer."""

    def __init__(self, layer, shelters, routing, config: SwarmConfig | None = None,
                 populations: np.ndarray | None = None):
        self.cfg = config or SwarmConfig()
        self.layer = layer
        self.shelters = shelters
        self.routing = routing

        if self.cfg.device == "auto":
            self.device = "cuda" if (_HAS_TORCH and torch.cuda.is_available()) else "cpu"
        else:
            self.device = self.cfg.device
        self.xp = torch if (_HAS_TORCH and self.device != "cpu") else np

        pops = populations if populations is not None else np.asarray(layer.population)
        self.n_blocks = len(pops)
        self.n_shelters = len(shelters)

        rng = np.random.default_rng(self.cfg.seed)

        # ---- materialise one agent per person -------------------------------
        counts = np.maximum(0, np.rint(pops)).astype(np.int64)
        self.n_agents = int(counts.sum())
        self.block = np.repeat(np.arange(self.n_blocks, dtype=np.int32), counts)

        n = self.n_agents
        self.state = np.full(n, S_INDOORS, dtype=np.int8)
        self.target = np.full(n, -1, dtype=np.int32)
        self.hop_prog = np.zeros(n, dtype=np.float32)
        self.fatigue = np.zeros(n, dtype=np.float32)
        self.switches = np.zeros(n, dtype=np.int8)

        # R1: lognormal departure delay, drawn per agent.
        self.depart_s = rng.lognormal(
            mean=math.log(self.cfg.departure_median_s),
            sigma=self.cfg.departure_sigma, size=n).astype(np.float32)

        # Roles. Slow agents walk slower and tire faster; helpers can offset
        # that for others in the same block; leaders write belief with weight.
        self.role = np.full(n, R_CIVILIAN, dtype=np.int8)
        draw = rng.random(n)
        self.role[draw < self.cfg.frac_slow] = R_SLOW
        self.role[(draw >= self.cfg.frac_slow) &
                  (draw < self.cfg.frac_slow + self.cfg.frac_helper)] = R_HELPER

        # Leadership is drawn without replacement and overrides the vulnerability
        # roles: a subdistrict commander is a commander first. Tiers are filled
        # from the top so a shortfall (a small city) costs the lowest tier.
        tiers = [(R_DISTRICT, self.cfg.n_district),
                 (R_SUBDISTRICT, self.cfg.n_subdistrict),
                 (R_COMMUNITY, self.cfg.n_community),
                 (R_GRID, self.cfg.n_grid)]
        want = sum(c for _, c in tiers)
        picked = rng.choice(n, size=min(want, n), replace=False)
        self.leader_ids: dict[int, np.ndarray] = {}
        cur = 0
        for tier, count in tiers:
            take = picked[cur:cur + count]
            cur += count
            self.role[take] = tier
            self.leader_ids[tier] = take
        # Leaders whose decisions go through the language model.
        # Every district and subdistrict commander reasons with the model.
        parts = [self.leader_ids[t_] for t_ in LLM_TIERS
                 if len(self.leader_ids.get(t_, []))]
        # Below that, LLM support reaches only part of the community tier: it
        # is a deployment depth, not a property of the tier. Scaling here keeps
        # the administrative structure honest: model coverage depth is a
        # deployment choice and must not be disguised by inflating tier sizes.
        n_c = int(min(self.cfg.n_llm_community, len(self.leader_ids.get(R_COMMUNITY, []))))
        if n_c > 0:
            parts.append(self.leader_ids[R_COMMUNITY][:n_c])
        self.llm_ids = (np.concatenate(parts) if parts
                        else np.array([], dtype=np.int64))

        self.speed = np.where(self.role == R_SLOW,
                              self.cfg.free_flow_speed_mps * 0.6,
                              self.cfg.free_flow_speed_mps).astype(np.float32)

        # ---- per-block candidate shelter sets (the compression lever) -------
        self.cand, self.cand_dist = self._build_candidates()

        # ---- block information fields --------------------------------------
        self.crowd = np.zeros(self.n_blocks, dtype=np.float32)
        # belief[b, k] = believed queue pressure at the k-th candidate of block b
        self.belief = np.zeros((self.n_blocks, self.cfg.n_candidates), dtype=np.float32)

        self.events: list[np.ndarray] = []
        self.step_index = 0
        self._occupancy = np.zeros(self.n_shelters, dtype=np.float64)

    # -- setup ---------------------------------------------------------------

    def _build_candidates(self):
        """The K nearest shelters for each block, and their distances.

        Restricting choice to K candidates is what keeps the belief field at
        n_blocks x K instead of n_blocks x n_shelters, and it is the honest
        model of a person's option set: nobody weighs every city shelter.
        """
        K = min(self.cfg.n_candidates, self.n_shelters)
        blon = np.asarray(self.layer.lon, dtype=np.float64)
        blat = np.asarray(self.layer.lat, dtype=np.float64)
        slon = np.array([s.lon for s in self.shelters], dtype=np.float64)
        slat = np.array([s.lat for s in self.shelters], dtype=np.float64)
        kx = 111_320.0 * math.cos(math.radians(float(blat.mean())))

        cand = np.zeros((self.n_blocks, K), dtype=np.int32)
        cdist = np.zeros((self.n_blocks, K), dtype=np.float32)
        # Chunk so the n_blocks x n_shelters distance matrix never materialises
        # in full for a large city.
        chunk = max(1, int(2e7 // max(self.n_shelters, 1)))
        for start in range(0, self.n_blocks, chunk):
            end = min(start + chunk, self.n_blocks)
            dx = (blon[start:end, None] - slon[None, :]) * kx
            dy = (blat[start:end, None] - slat[None, :]) * 110_540.0
            d = np.sqrt(dx * dx + dy * dy)
            idx = np.argpartition(d, K - 1, axis=1)[:, :K]
            rows = np.arange(end - start)[:, None]
            dd = d[rows, idx]
            order = np.argsort(dd, axis=1)
            cand[start:end] = idx[rows, order]
            cdist[start:end] = dd[rows, order]
        return cand, cdist

    # -- reporting -----------------------------------------------------------

    def memory_report(self) -> dict[str, Any]:
        def mb(a):
            return a.nbytes / 1024 ** 2
        agent_mb = sum(mb(a) for a in (
            self.block, self.state, self.target, self.hop_prog, self.fatigue,
            self.switches, self.depart_s, self.role, self.speed))
        field_mb = mb(self.crowd) + mb(self.belief)
        cand_mb = mb(self.cand) + mb(self.cand_dist)
        counts = {name: int((self.role == val).sum()) for name, val in (
            ("civilian", R_CIVILIAN), ("slow", R_SLOW), ("helper", R_HELPER),
            ("grid", R_GRID), ("community", R_COMMUNITY),
            ("subdistrict", R_SUBDISTRICT), ("district", R_DISTRICT))}
        return {
            "n_agents": self.n_agents,
            "roles": counts,
            "n_llm_leaders": int(len(self.llm_ids)),
            "residents_per_llm_leader": (
                int(self.n_agents / len(self.llm_ids)) if len(self.llm_ids) else None),
            "n_blocks": self.n_blocks,
            "n_shelters": self.n_shelters,
            "device": self.device,
            "agent_state_mb": round(agent_mb, 1),
            "block_fields_mb": round(field_mb, 1),
            "candidate_sets_mb": round(cand_mb, 1),
            "total_mb": round(agent_mb + field_mb + cand_mb, 1),
            "bytes_per_agent": round((agent_mb * 1024 ** 2) / max(self.n_agents, 1), 1),
        }
