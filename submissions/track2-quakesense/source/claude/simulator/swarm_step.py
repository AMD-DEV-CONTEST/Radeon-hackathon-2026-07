"""P1 + P2 + P3 step loop for the full-population swarm, on GPU.

Implements, over one agent per resident:

* (1) departure, lognormal per agent
* (2) crowd field, weighted bincount, no host sync
* (3) belief diffusion across the real block adjacency
* (4) logit destination choice over K candidates -- what splits the flow
* (5) advance along one adjacency edge at a time
* (6) helper matching, block-level supply and demand
* (7) shelter admission by segmented prefix sum -- the one serial point
* (8) give-up on fatigue
* (9) event stream, flushed to disk by a CPU thread off the critical path

Agents now traverse intermediate blocks and feel the congestion in each one,
which is what the straight-line version of P1 could not do.

Still not implemented: the LLM leader tier (see llm_leaders.py, wired in
separately), and per-agent social groups -- group_id/helper_id are allocated
and helper matching is aggregate rather than pairwise.
"""

from __future__ import annotations

import math
import queue
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np
import torch

from .agent_swarm import (
    S_INDOORS, S_TRANSIT, S_SHELTERED, S_GAVEUP,
    R_SLOW, R_HELPER, R_GRID,
    E_DEPART, E_RETARGET, E_ARRIVE, E_REJECTED, E_GAVEUP,
)

K_BELIEF = 16
TRAJ_DEPTH = 32

#: An agent is close enough to attempt entry at this range from the shelter.
ARRIVE_RADIUS_M = 250.0

#: Cap on hops before an agent is treated as lost rather than looping.
MAX_HOPS = 400

#: Network distance at which a shelter becomes visible to someone standing
#: nearby. Without this, wandering is a dead end by construction: admission
#: tested distance to the agent's *target*, and a searcher has none, so
#: somebody could walk past an open shelter and never enter it. Measured
#: consequence: at zero prior knowledge exactly 28,428 people were sheltered
#: in all six bellwether variants -- essentially only the leaders, who had
#: targets. You should be able to find a shelter by seeing it.
SEE_RADIUS_M = 400.0


class EventWriter:
    """Flushes event shards from a background thread.

    The GPU must not wait on a disk write, and CPython's GIL is released
    during I/O, so a plain thread is enough -- no process pool, no shared
    memory, no serialisation of the array twice.
    """

    def __init__(self, out_dir: Path | None, queue_depth: int = 8):
        self.dir = Path(out_dir) if out_dir else None
        self.q: queue.Queue = queue.Queue(maxsize=queue_depth)
        self.n_written = 0
        self.n_events = 0
        self._t = None
        if self.dir:
            self.dir.mkdir(parents=True, exist_ok=True)
            self._t = threading.Thread(target=self._run, daemon=True)
            self._t.start()

    def _run(self):
        while True:
            item = self.q.get()
            if item is None:
                self.q.task_done()
                return
            arr = item
            np.save(self.dir / f"events_{self.n_written:05d}.npy", arr)
            self.n_written += 1
            self.q.task_done()

    def submit(self, arr: np.ndarray):
        self.n_events += len(arr)
        if self.dir:
            self.q.put(arr)

    def close(self):
        if self._t:
            self.q.put(None)
            self._t.join(timeout=60)


class SwarmStepper:
    """Moves an :class:`AgentSwarm`'s population on the GPU."""

    def __init__(self, swarm, device: str = "cuda",
                 with_belief: bool = True, with_traj: bool = True,
                 neigh: np.ndarray | None = None,
                 route_dist: np.ndarray | None = None,
                 route_pred: np.ndarray | None = None,
                 event_dir: str | Path | None = None,
                 event_buffer: int = 4_000_000):
        self.s = swarm
        self.cfg = swarm.cfg
        self.dev = torch.device(device)
        n = swarm.n_agents
        self.n, self.nb, self.ns = n, swarm.n_blocks, swarm.n_shelters
        self.with_belief, self.with_traj = with_belief, with_traj

        d = self.dev
        mv = lambda a: torch.as_tensor(a).to(d, non_blocking=True)

        # ---- [A] kinematics + physics, 41 B --------------------------------
        self.block = mv(swarm.block)
        self.block_l = self.block.to(torch.int64)
        self.next_block = torch.full((n,), -1, dtype=torch.int32, device=d)
        self.prev_block = torch.full((n,), -1, dtype=torch.int32, device=d)
        self.target = torch.full((n,), -1, dtype=torch.int32, device=d)
        self.state = mv(swarm.state)
        self.depart_s = mv(swarm.depart_s)
        self.hop_prog = torch.zeros(n, dtype=torch.float32, device=d)
        self.speed = mv(swarm.speed)
        self.fatigue = torch.zeros(n, dtype=torch.float32, device=d)
        self.dist_walked = torch.zeros(n, dtype=torch.float32, device=d)
        #: Seconds from the shaking to being admitted. Counting how many got in
        #: says nothing about how long it took them, and the planning question
        #: is a time -- "what share is safe within 15 minutes", not "eventually".
        self.shelter_time = torch.full((n,), float("nan"),
                                       dtype=torch.float32, device=d)
        self.n_hops = torch.zeros(n, dtype=torch.int16, device=d)
        self.role = mv(swarm.role)
        self.health = torch.zeros(n, dtype=torch.int8, device=d)

        # ---- [B] social relations, 20 B ------------------------------------
        self.group_id = torch.full((n,), -1, dtype=torch.int32, device=d)
        self.helper_id = torch.full((n,), -1, dtype=torch.int32, device=d)
        self.helping_id = torch.full((n,), -1, dtype=torch.int32, device=d)
        self.leader_id = torch.full((n,), -1, dtype=torch.int32, device=d)
        self.influenced_at = torch.zeros(n, dtype=torch.float32, device=d)

        # ---- [C] decision & information provenance, 21 B --------------------
        self.switches = torch.zeros(n, dtype=torch.int8, device=d)
        self.last_decision_s = torch.zeros(n, dtype=torch.float32, device=d)
        self.info_source = torch.full((n,), -1, dtype=torch.int32, device=d)
        self.info_time = torch.zeros(n, dtype=torch.float32, device=d)
        self.known_full = torch.zeros(n, dtype=torch.int64, device=d)
        #: Which of this block's K candidates the agent knows EXISTS. Distinct
        #: from known_full, which is what they know about occupancy.
        #:
        #: Until now every agent was handed the K nearest shelters and their
        #: exact network distances, i.e. the whole city was omniscient. Under
        #: that premise a leader has nothing to tell anyone and can only add
        #: noise -- which is exactly what three A/B designs measured (-3.09 %,
        #: -18.93 %, -0.06 %). Information asymmetry is the premise that makes
        #: a leader worth having.
        self.known = torch.zeros(n, dtype=torch.int32, device=d)
        #: Where that knowledge came from, and when. Allocated since the state
        #: re-accounting but never written until now.
        self.info_source.fill_(-1)

        # ---- [D] individual belief, K=16 x (value, age) = 128 B --------------
        if with_belief:
            self.belief = torch.zeros((n, K_BELIEF), dtype=torch.float32, device=d)
            self.belief_age = torch.zeros((n, K_BELIEF), dtype=torch.float32, device=d)
        else:
            self.belief = self.belief_age = None

        # ---- [E] trajectory ring buffer, 32 x int32 = 128 B ------------------
        self.traj = (torch.full((n, TRAJ_DEPTH), -1, dtype=torch.int32, device=d)
                     if with_traj else None)

        # ---- geometry in a local metric frame -------------------------------
        blon = np.asarray(swarm.layer.lon, dtype=np.float64)
        blat = np.asarray(swarm.layer.lat, dtype=np.float64)
        kx = 111_320.0 * math.cos(math.radians(float(blat.mean())))
        ky = 110_540.0
        self.bx = mv(((blon - blon.mean()) * kx).astype(np.float32))
        self.by = mv(((blat - blat.mean()) * ky).astype(np.float32))
        self.sx = mv(np.array([(s_.lon - blon.mean()) * kx for s_ in swarm.shelters],
                              dtype=np.float32))
        self.sy = mv(np.array([(s_.lat - blat.mean()) * ky for s_ in swarm.shelters],
                              dtype=np.float32))

        # ---- adjacency ------------------------------------------------------
        if neigh is None:
            raise ValueError("neigh is required: agents must traverse the block "
                             "graph, not fly straight lines")
        self.neigh = torch.as_tensor(neigh).to(d)                   # (nb, D)
        self.D = self.neigh.shape[1]
        nb_safe = self.neigh.clamp_min(0).to(torch.int64)
        dx = self.bx[nb_safe] - self.bx.unsqueeze(1)
        dy = self.by[nb_safe] - self.by.unsqueeze(1)
        self.neigh_dist = torch.sqrt(dx * dx + dy * dy).clamp_min(1.0)
        self.neigh_valid = (self.neigh >= 0)
        # An isolated block would trap everyone standing in it; treat it as its
        # own neighbour so those agents fail by give-up rather than by hanging.
        self.neigh_dist = torch.where(self.neigh_valid, self.neigh_dist,
                                      torch.full_like(self.neigh_dist, 1e9))

        # ---- exact routing tables -------------------------------------------
        # (n_shelters, n_blocks): the next block toward a shelter, and the
        # network distance to it. This buys O(1) exact routing
        # in place of a neighbourhood search that could not escape local minima.
        if route_pred is None or route_dist is None:
            raise ValueError("route_pred/route_dist are required: greedy "
                             "geographic routing strands agents in local minima")
        self.rpred = torch.as_tensor(route_pred).to(d)
        self.rdist = torch.as_tensor(route_dist).to(d)
        #: Gave up because no path exists at all, as opposed to running out of
        #: stamina. Conflating the two hides whether the network or the person
        #: is the binding constraint.
        self.no_path = torch.zeros(n, dtype=torch.bool, device=d)

        self.cand = torch.as_tensor(swarm.cand).to(d)
        self.cand_dist = torch.as_tensor(swarm.cand_dist).to(d)
        self.crowd = torch.zeros(self.nb, dtype=torch.float32, device=d)
        #: Crowd field as the lost perceive it, with leaders weighted up.
        self.follow = self.crowd
        #: Decaying trace of who has passed through. Persists across steps,
        #: which is what turns a leader walking a route into a followable path.
        self.trail = torch.zeros(self.nb, dtype=torch.float32, device=d)
        self.bbelief = torch.zeros((self.nb, K_BELIEF), dtype=torch.float32, device=d)
        #: What is common knowledge in this block: a bitmask over its K
        #: candidates. Leaders broadcast into it, neighbours spread it, and
        #: people standing in the block pick it up. This is the information
        #: channel; bbelief is the opinion channel.
        self.bknown = torch.zeros(self.nb, dtype=torch.int32, device=d)
        # Density divides by usable open ground, not the whole block. When a
        # footprint-derived open share is available, courtyards and gaps between
        # buildings count as usable space. Missing values retain the full block
        # area instead of borrowing a ratio from another neighbourhood.
        area = np.maximum(
            np.asarray(getattr(swarm.layer, "area_m2", np.full(self.nb, 40_000.0)),
                       dtype=np.float32), 1_000.0)
        open_share = getattr(swarm.layer, "open_share", None)
        if open_share is not None:
            os_ = np.asarray(open_share, dtype=np.float32)
            area = area * np.where(np.isfinite(os_), np.clip(os_, 0.05, 1.0), 1.0)
            self.n_area_measured = int(np.isfinite(os_).sum())
        else:
            self.n_area_measured = 0
        self.block_area = torch.as_tensor(np.maximum(area, 500.0)).to(d)

        cap = np.array([float(getattr(s_, "capacity", 0.0)) for s_ in swarm.shelters],
                       dtype=np.float64)
        self.capacity = torch.as_tensor(cap, dtype=torch.float64, device=d)
        self.occupancy = torch.zeros(self.ns, dtype=torch.float64, device=d)

        #: Metres left on the current adjacency edge.
        self.remaining = torch.zeros(n, dtype=torch.float32, device=d)
        #: Speed multiplier from being assisted, refreshed by kernel (6).
        self.assist = torch.ones(n, dtype=torch.float32, device=d)
        #: Hop count at the last rejection, so a turned-away agent must walk
        #: before queueing again.
        self.reject_hop = torch.full((n,), -1, dtype=torch.int16, device=d)

        # ---- events ---------------------------------------------------------
        self.ev_cap = event_buffer
        self.ev_buf = torch.zeros((self.ev_cap, 3), dtype=torch.int32, device=d)
        self.ev_n = torch.zeros(1, dtype=torch.int64, device=d)
        self.writer = EventWriter(event_dir)

        self.t = 0.0
        self.step_index = 0
        #: How many re-decisions kernel (4b) triggered, so the
        #: leader tier's reach can be reported rather than assumed.
        self.rethought = 0
        #: Arrivals turned away at a full gate. A leader who directs people to
        #: a shelter that fills before they get there shows up here, which is
        #: how "guidance made local crowding worse" becomes measurable rather
        #: than anecdotal.
        self.rejections = 0
        self.timings: dict[str, float] = {}
        self._gen = torch.Generator(device=d)
        self._gen.manual_seed(self.cfg.seed)

        # Who knows anything at the moment the ground shakes. The share is an
        # assumption rather than a surveyed city-specific constant,
        # so it is a config knob to be swept, not a calibrated constant. Seeded
        # after the generator exists, which is why it is down here.
        self._seed_knowledge()

    def _seed_knowledge(self):
        """Give a minority of residents a vague idea where to go.

        Knowing your nearest shelter is the common case for someone who has
        seen the sign on their own street; knowing the second one as well is
        rarer. Everyone else starts with nothing and has to be told, follow
        somebody, or search.
        """
        n = self.n
        r = torch.rand(n, device=self.dev, generator=self._gen)
        f1 = self.cfg.frac_knows_one
        # Knowing two shelters is a subset of knowing one. Without this clamp a
        # default frac_knows_two of 0.08 outranks any sweep point below it, so
        # "nobody knows anything" silently still had 8 % who knew two -- the
        # K=0.00 and K=0.05 rows came out bit-identical, which is the tell.
        f2 = min(self.cfg.frac_knows_two, f1)
        # bit 0 is the nearest candidate, bit 1 the second nearest.
        self.known = torch.where(r < f2, torch.full_like(self.known, 0b11),
                    torch.where(r < f1, torch.full_like(self.known, 0b01),
                                torch.zeros_like(self.known)))
        # Leaders know their whole candidate set -- that is what makes them
        # worth listening to, and it is an institutional fact rather than luck.
        lead = self.role >= R_GRID
        self.known[lead] = (1 << K_BELIEF) - 1

    # -- accounting ----------------------------------------------------------

    def state_bytes(self) -> dict[str, Any]:
        out = {"A_kinematics": 41, "B_social": 20, "C_decision": 21}
        if self.belief is not None:
            out["D_belief"] = K_BELIEF * 4 * 2
        if self.traj is not None:
            out["E_trajectory"] = TRAJ_DEPTH * 4
        total = sum(out.values())
        out["total_bytes_per_agent"] = total
        out["total_gb"] = round(total * self.n / 1024 ** 3, 3)
        return out

    # -- events --------------------------------------------------------------

    def _emit(self, idx, kind: int):
        """Append (step, agent, kind) rows for every agent in ``idx``.

        Written as a loop over buffer-sized chunks rather than one slice: a
        single step can produce more events than the whole buffer holds -- the
        first departure step alone can move millions of agents at once -- and
        an earlier version silently truncated the overflow. That is invisible
        until you try to replay the stream and find the state does not match,
        which is exactly what scripts/replay_verify.py is for.
        """
        m = idx.numel()
        if m == 0:
            return
        pos = 0
        while pos < m:
            start = int(self.ev_n.item())
            if start >= self.ev_cap:
                self._flush_events()
                start = 0
            room = self.ev_cap - start
            take = min(room, m - pos)
            end = start + take
            self.ev_buf[start:end, 0] = self.step_index
            self.ev_buf[start:end, 1] = idx[pos:pos + take].to(torch.int32)
            self.ev_buf[start:end, 2] = kind
            self.ev_n.fill_(end)
            pos += take
            if end >= self.ev_cap:
                self._flush_events()

    def _flush_events(self):
        k = int(self.ev_n.item())
        if k:
            self.writer.submit(self.ev_buf[:k].cpu().numpy().copy())
        self.ev_n.zero_()

    # -- the step ------------------------------------------------------------

    def _time(self, key, fn):
        torch.cuda.synchronize()
        t0 = time.perf_counter()
        r = fn()
        torch.cuda.synchronize()
        self.timings[key] = self.timings.get(key, 0.0) + (time.perf_counter() - t0)
        return r

    def step(self, dt: float | None = None, profile: bool = False) -> None:
        dt = float(dt if dt is not None else self.cfg.step_seconds)
        run = self._time if profile else (lambda k, f: f())

        run("1_depart", lambda: self._k1_depart(dt))
        run("2_crowd", self._k2_crowd)
        run("3_diffuse", self._k3_diffuse)
        run("3b_share", self._k3b_share)
        run("4_rethink", self._k4_rethink)
        run("5_advance", lambda: self._k5_advance(dt))
        run("6_helpers", self._k6_helpers)
        run("7_admit", self._k7_admit)
        run("8_giveup", lambda: self._k8_giveup(dt))

        self.t += dt
        self.step_index += 1

    # (1) departure ----------------------------------------------------------

    def _k1_depart(self, dt):
        due = (self.state == S_INDOORS) & (self.depart_s <= self.t)
        idx = due.nonzero(as_tuple=True)[0]
        if idx.numel() == 0:
            return
        self.state[idx] = S_TRANSIT
        self._k4_choose(idx, first=True)
        self._pick_next_hop(idx)
        self._emit(idx, E_DEPART)

    # (4) logit destination choice ------------------------------------------

    #: Cap on agents scored in one pass. The decision kernel holds several
    #: (m, K) float tensors at once, so an unbounded m turns a 2 M-agent
    #: departure surge into a multi-gigabyte allocation.
    CHOOSE_CHUNK = 4_000_000

    def _k4_choose(self, idx, first: bool):
        if idx.numel() > self.CHOOSE_CHUNK:
            for s in range(0, idx.numel(), self.CHOOSE_CHUNK):
                self._choose_one(idx[s:s + self.CHOOSE_CHUNK], first)
            return
        self._choose_one(idx, first)

    def _choose_one(self, idx, first: bool):
        """Softmax over the K_BELIEF nearest candidates of the current block.

        The block-scale engine gave every person in a block the same next hop,
        which is why 81 % of them walked past a closer shelter with spare
        capacity. Sampling from a distribution instead makes one block feed
        several shelters in proportion to their attractiveness.
        """
        if idx.numel() == 0:
            return
        b = self.block[idx].long()
        cand = self.cand[b, :K_BELIEF]
        # Network distance, not straight line: a shelter 400 m away across a
        # river is a 4 km walk, and only the routing table knows that. An
        # unreachable candidate carries an infinite distance and so is never
        # sampled while any reachable one remains.
        dist = self.rdist[cand.to(torch.int64), b.unsqueeze(1)]
        spd = (self.speed[idx] * self.assist[idx]).unsqueeze(1).clamp_min(0.1)
        travel = dist / spd

        queue_belief = self.bbelief[b]
        if self.belief is not None:
            queue_belief = queue_belief + self.belief[idx]
        cost = travel + self.cfg.beta * queue_belief

        arange = torch.arange(K_BELIEF, device=self.dev)
        bits = (self.known_full[idx].unsqueeze(1) >> arange) & 1
        cost = cost + bits.to(cost.dtype) * 3600.0
        # You cannot walk to a shelter you have never heard of. Unknown
        # candidates are removed from the choice set rather than merely
        # penalised, because "I do not know it exists" is not a soft preference.
        kn = (self.known[idx].unsqueeze(1) >> arange) & 1
        cost = torch.where(kn > 0, cost, torch.full_like(cost, float("inf")))

        if not first:
            cur = self.target[idx].unsqueeze(1)
            is_cur = (cand == cur)
            cost = cost + (~is_cur).to(cost.dtype) * (
                self.cfg.lambda_switch + self.cfg.theta)

        # Gumbel-max is an exact softmax sample and needs no normalisation.
        g = -torch.log(-torch.log(torch.rand(cost.shape, device=self.dev,
                                             generator=self._gen).clamp_min(1e-20)
                                  ).clamp_min(1e-20))
        rows = torch.arange(idx.numel(), device=self.dev)
        pick = torch.argmax(-cost / self.cfg.tau + g, dim=1)

        new_t = cand[rows, pick]
        # Somebody who has heard of nothing has no destination to pick. They do
        # not stand still and they do not teleport to a shelter they have never
        # heard of -- they set out and look, which is what -1 means here.
        blind = (self.known[idx] == 0)
        new_t = torch.where(blind, torch.full_like(new_t, -1), new_t)
        if not first:
            changed = new_t != self.target[idx]
            self.switches[idx] = (self.switches[idx] + changed.to(torch.int8)
                                  ).clamp_max(self.cfg.max_switches)
            self._emit(idx[changed], E_RETARGET)
        self.target[idx] = new_t
        self.last_decision_s[idx] = self.t

    # (4b) reconsider ---------------------------------------------------------

    def _k4_rethink(self):
        """Let people change their mind when new information reaches them.

        Without this the belief field is write-only after departure: a target
        is chosen once and only a rejection at the shelter door can revise it.
        Without re-evaluation, most agents retain their initial target and the
        leader tier has little effect on a population that has stopped listening.

        Two things make someone reconsider, and both are local:

        * a leader's broadcast reached their block since they last decided --
          ``influenced_at`` is stamped by the leader tier, and only a fraction
          ``broadcast_reach`` of people in earshot actually act on it;
        * the block they are standing in has become badly congested, which is
          information they get with their own eyes rather than from anyone.

        Re-deciding is chunked because the eligible set right after a broadcast
        can be most of the city, and _k4_choose allocates (m, K) tensors.
        """
        transit = self.state == S_TRANSIT
        heard = transit & (self.influenced_at > self.last_decision_s)
        dens = self.crowd[self.block_l] / self.block_area[self.block_l]
        stale = (self.t - self.last_decision_s) > self.cfg.rethink_cooldown_s
        crowded = transit & stale & (dens > self.cfg.rethink_density)
        elig = heard | crowded
        idx = elig.nonzero(as_tuple=True)[0]
        if idx.numel() == 0:
            return
        # Not everyone within earshot hears, and not everyone who hears obeys.
        take = torch.rand(idx.numel(), device=self.dev,
                          generator=self._gen) < self.cfg.broadcast_reach
        idx = idx[take]
        if idx.numel() == 0:
            return
        self.rethought += int(idx.numel())
        for chunk in torch.split(idx, 2_000_000):
            self._k4_choose(chunk, first=False)
            self._pick_next_hop(chunk)

    # next hop over the adjacency graph --------------------------------------

    def _pick_next_hop(self, idx):
        """Follow the precomputed shortest-path tree of the chosen shelter.

        One gather, no search. Congestion is not consulted here on purpose:
        rerouting around a jam is a *decision*, made in kernel (4) against the
        belief field, not something the walking step does silently. Mixing the
        two was what made the greedy version wander.
        """
        if idx.numel() == 0:
            return
        b = self.block[idx].long()
        searching = self.target[idx] < 0
        if bool(searching.any()):
            # No destination, so no routing tree to follow. People move the way
            # people actually move when they do not know where to go: towards
            # wherever others are going. Following the flow is stigmergy, and it
            # is why an uninformed population converges slowly rather than never
            # -- but it costs distance, and that cost is the thing a leader's
            # broadcast can remove.
            s_idx = idx[searching]
            sb = b[searching]
            nbr = self.neigh[sb].clamp_min(0).to(torch.int64)
            flow = self.follow[nbr]
            flow = torch.where(self.neigh_valid[sb], flow,
                               torch.full_like(flow, -1.0))
            back = nbr == self.prev_block[s_idx].unsqueeze(1).clamp_min(0).long()
            flow = flow - back.to(flow.dtype) * 1e6
            jitter = torch.rand(flow.shape, device=self.dev,
                                generator=self._gen) * flow.abs().amax().clamp_min(1.0) * 0.15
            j = torch.argmax(flow + jitter, dim=1)
            rows_s = torch.arange(s_idx.numel(), device=self.dev)
            pick_b = nbr[rows_s, j]
            dxs = self.bx[pick_b] - self.bx[sb]
            dys = self.by[pick_b] - self.by[sb]
            self.next_block[s_idx] = pick_b.to(torch.int32)
            self.remaining[s_idx] = torch.sqrt(dxs * dxs + dys * dys).clamp_min(1.0)
            keep = ~searching
            idx, b = idx[keep], b[keep]
            if idx.numel() == 0:
                return
        tgt = self.target[idx].clamp_min(0).long()
        nxt = self.rpred[tgt, b]

        stranded = nxt < 0
        if bool(stranded.any()):
            # No path to the shelter this agent picked. Every candidate with a
            # path was already preferred in (4), so this means the block is cut
            # off from all of them -- report it rather than let fatigue absorb it.
            s_idx = idx[stranded]
            self.no_path[s_idx] = True
            self.state[s_idx] = S_GAVEUP
            self._emit(s_idx, E_GAVEUP)
            keep = ~stranded
            idx, b, nxt = idx[keep], b[keep], nxt[keep]
            if idx.numel() == 0:
                return

        nl = nxt.to(torch.int64)
        dx = self.bx[nl] - self.bx[b]
        dy = self.by[nl] - self.by[b]
        self.next_block[idx] = nxt.to(torch.int32)
        self.remaining[idx] = torch.sqrt(dx * dx + dy * dy).clamp_min(1.0)

    # (2) crowd field --------------------------------------------------------

    def _k2_crowd(self):
        """Weighted bincount rather than compact-then-count: compaction needs
        ``nonzero``, whose output shape only the host knows, which is a device
        sync inside the hot loop."""
        moving = (self.state == S_TRANSIT).to(torch.float32)
        self.crowd = torch.bincount(self.block_l, weights=moving,
                                    minlength=self.nb).to(torch.float32)
        # A second field, identical except that leaders count for more. Density
        # for the physics must stay honest -- a leader does not take up more
        # pavement -- but the field that LOST people follow is about who they
        # notice, and a leader walking with purpose is noticed.
        w = self.cfg.bellwether_weight
        deposit = self.crowd
        if w != 1.0:
            extra = moving * (self.role >= R_GRID).to(torch.float32) * (w - 1.0)
            deposit = deposit + torch.bincount(
                self.block_l, weights=extra, minlength=self.nb).to(torch.float32)
        d = self.cfg.trail_decay
        if d > 0.0:
            # Stigmergy: what the lost follow is the trace of who came through,
            # not who is standing here this instant. Repulsive in the shelter
            # engine, attractive here -- people head towards where others went.
            self.trail = self.trail * (1.0 - d) + deposit
            self.follow = self.trail
        else:
            self.follow = deposit

    # (3) belief diffusion ---------------------------------------------------

    def _k3_diffuse(self):
        """Word of mouth spreads one block per step and decays with staleness.

        The belief field is stored per block and truncated to K candidates so
        neighbourhood gathers remain bounded; the equivalent individual-level
        tensor would be substantially larger.
        """
        nbr = self.neigh.clamp_min(0).to(torch.int64)
        vals = self.bbelief[nbr]                                   # (nb, D, K)
        mask = self.neigh_valid.unsqueeze(-1).to(vals.dtype)
        deg = mask.sum(dim=1).clamp_min(1.0)
        mean_nbr = (vals * mask).sum(dim=1) / deg
        a = self.cfg.belief_diffusion
        self.bbelief = ((1.0 - a) * self.bbelief + a * mean_nbr) * (
            1.0 - self.cfg.belief_decay)

    # (3b) information spreads -----------------------------------------------

    def _k3b_share(self):
        """Word of mouth, and knowledge crossing block boundaries.

        Three transfers, all local and all cheap because knowledge is a bitmask
        over the block's own K candidates rather than a per-agent list:

        * what people in a block know becomes what the block knows (OR);
        * what a block knows leaks to its neighbours;
        * people standing in a block pick up what the block knows.

        This is the channel a leader shouts into. Without it a broadcast has
        nowhere to land.
        """
        # People contribute what they know to the block they stand in. Using a
        # max-reduction as a stand-in for OR: bitmasks are small non-negative
        # ints, so max over a block is a lower bound on the union, and repeated
        # steps converge to it without needing a scatter-OR primitive.
        # Leaders are excluded here on purpose. They know their whole candidate
        # set, so letting them contribute passively means a leader merely
        # standing in a block floods it -- measured: mean shelters known went
        # from 2 to 14.2 of 16 within ten simulated minutes, which leaves a
        # broadcast nothing to add. A leader transmits by broadcasting, which
        # is an action they take, not an aura they emit.
        civ = (self.role < R_GRID).to(self.known.dtype)
        contrib = torch.zeros_like(self.bknown)
        contrib.scatter_reduce_(0, self.block_l, self.known * civ,
                                reduce="amax", include_self=True)
        self.bknown = torch.bitwise_or(self.bknown, contrib)

        if torch.rand(1, device=self.dev, generator=self._gen).item()                 < self.cfg.knowledge_spread:
            nbr = self.neigh.clamp_min(0).to(torch.int64)
            spread = self.bknown[nbr]
            spread = torch.where(self.neigh_valid, spread,
                                 torch.zeros_like(spread))
            self.bknown = torch.bitwise_or(self.bknown, spread.amax(dim=1))

        # Seeing one for yourself. Anyone in transit learns about candidates
        # of their current block that are close enough to be visible, which is
        # the one channel that needs no informant at all.
        moving_now = self.state == S_TRANSIT
        idx_m = moving_now.nonzero(as_tuple=True)[0]
        if idx_m.numel():
            for chunk in torch.split(idx_m, 4_000_000):
                b = self.block_l[chunk]
                cand = self.cand[b, :K_BELIEF].to(torch.int64)
                d = self.rdist[cand, b.unsqueeze(1)]
                vis = (d <= SEE_RADIUS_M)
                # sum() promotes int32 to int64; cast back or the masked
                # assignment into an int32 field fails on dtype.
                bits = (vis.to(torch.int32)
                        << torch.arange(K_BELIEF, device=self.dev,
                                        dtype=torch.int32)
                        ).sum(dim=1).to(torch.int32)
                self.known[chunk] = torch.bitwise_or(self.known[chunk], bits)

        # And people pick it up -- not everyone, not instantly.
        take = torch.rand(self.n, device=self.dev, generator=self._gen)                < self.cfg.word_of_mouth
        moving = self.state == S_TRANSIT
        sel = take & moving
        if bool(sel.any()):
            idx = sel.nonzero(as_tuple=True)[0]
            gained = torch.bitwise_or(self.known[idx], self.bknown[self.block_l[idx]])
            newly = gained != self.known[idx]
            self.known[idx] = gained
            hit = idx[newly]
            if hit.numel():
                self.info_time[hit] = self.t

    # (5) advance ------------------------------------------------------------

    def _k5_advance(self, dt):
        """Branchless over the whole population, then a compacted pass for the
        few agents that completed an edge this step."""
        moving = (self.state == S_TRANSIT).to(torch.float32)
        dens = (self.crowd[self.block_l] / self.block_area[self.block_l]
                ).clamp(0.0, self.cfg.jam_density)
        f = (1.0 - dens / self.cfg.jam_density).clamp_min(0.05)
        # The lost walk slower than the purposeful, which is most of what
        # "hesitant" means at this resolution.
        hes = torch.where(self.target < 0,
                          torch.full_like(self.speed, self.cfg.search_speed_factor),
                          torch.ones_like(self.speed))
        adv = self.speed * self.assist * hes * f * dt * moving
        self.remaining -= adv
        self.dist_walked += adv
        self.fatigue += dt * moving
        self.hop_prog = f

        arrived_edge = ((self.state == S_TRANSIT) & (self.remaining <= 0.0)
                        & (self.next_block >= 0))
        idx = arrived_edge.nonzero(as_tuple=True)[0]
        if idx.numel() == 0:
            return
        self.prev_block[idx] = self.block[idx]
        self.block[idx] = self.next_block[idx]
        self.block_l[idx] = self.block[idx].to(torch.int64)
        if self.traj is not None:
            slot = self.n_hops[idx].to(torch.int64) % TRAJ_DEPTH
            self.traj[idx, slot] = self.block[idx]
        self.n_hops[idx] = (self.n_hops[idx] + 1).clamp_max(MAX_HOPS)
        # Arriving somewhere new is the moment you might learn something, so a
        # searcher reconsiders here rather than waiting for a broadcast.
        blind = self.target[idx] < 0
        if bool(blind.any()):
            self._k4_choose(idx[blind], first=True)
        self._pick_next_hop(idx)

    # (6) helper matching ----------------------------------------------------

    def _k6_helpers(self):
        """Aggregate supply and demand per block rather than pairwise matching.

        Who helps whom is not identifiable from any data we have, and pairing
        22 M agents would cost more than the rest of the step combined. What is
        defensible is that a slow person in a block with many able neighbours
        moves closer to normal speed than one with none.
        """
        moving = (self.state == S_TRANSIT).to(torch.float32)
        helpers = torch.bincount(self.block_l,
                                 weights=((self.role == R_HELPER).to(torch.float32)
                                          * moving),
                                 minlength=self.nb)
        slow = torch.bincount(self.block_l,
                              weights=((self.role == R_SLOW).to(torch.float32) * moving),
                              minlength=self.nb).clamp_min(1.0)
        ratio = (helpers / slow).clamp(0.0, 1.0)
        boost = 1.0 + 0.4 * ratio[self.block_l]
        self.assist = torch.where(self.role == R_SLOW, boost,
                                  torch.ones_like(boost))

    # (7) shelter admission -- the one serial point --------------------------

    def _k7_admit(self):
        """Admit arrivals up to capacity, deterministically.

        Capacity is a shared resource: if every arriving agent independently
        checks "is there room?", the shelter overfills. Grouping by shelter and
        taking a segmented prefix sum gives each arrival a rank within its
        group, so admission is exact and reproducible -- groups still run in
        parallel, with a scan rather than a loop inside each.
        """
        tgt_all = self.target.clamp_min(0).long()
        near = self.rdist[tgt_all, self.block_l] <= ARRIVE_RADIUS_M
        # A turned-away agent has to walk somewhere before queueing again.
        # Without this they re-present at a full shelter every single step,
        # and the retarget kernel then allocates an (n, K) tensor per step.
        moved_since = self.n_hops > self.reject_hop
        arrived = ((self.state == S_TRANSIT) & near & (self.target >= 0)
                   & moved_since)
        idx = arrived.nonzero(as_tuple=True)[0]
        if idx.numel() == 0:
            return
        tgt = self.target[idx].long()
        order = torch.argsort(tgt)
        idx_s, tgt_s = idx[order], tgt[order]

        uniq, counts = torch.unique_consecutive(tgt_s, return_counts=True)
        starts = torch.cumsum(counts, 0) - counts
        rank = (torch.arange(tgt_s.numel(), device=self.dev)
                - starts.repeat_interleave(counts)).to(torch.float64)

        room = self.capacity[tgt_s] - self.occupancy[tgt_s]
        admit = rank < room

        adm_idx = idx_s[admit]
        self.state[adm_idx] = S_SHELTERED
        self.shelter_time[adm_idx] = self.t
        self.occupancy.index_add_(0, tgt_s, admit.to(torch.float64))
        self._emit(adm_idx, E_ARRIVE)

        rej_idx = idx_s[~admit]
        if rej_idx.numel():
            rb = self.block[rej_idx].long()
            slot = (self.cand[rb, :K_BELIEF] ==
                    self.target[rej_idx].unsqueeze(1)).to(torch.int64).argmax(dim=1)
            self.known_full[rej_idx] = (self.known_full[rej_idx]
                                        | (torch.ones_like(slot) << slot))
            if self.belief is not None:
                self.belief[rej_idx, slot] += 600.0
                self.belief_age[rej_idx, slot] = self.t
            # A rejection is public: everyone in that block learns it too. This
            # is the only information the model creates from experience, and it
            # is what belief diffusion then carries outward.
            self.bbelief.index_put_((rb, slot),
                                    self.bbelief[rb, slot] + 120.0, accumulate=False)
            self.info_time[rej_idx] = self.t
            self.reject_hop[rej_idx] = self.n_hops[rej_idx]
            self._emit(rej_idx, E_REJECTED)
            self.rejections += int(rej_idx.numel())
            self._k4_choose(rej_idx, first=False)
            self._pick_next_hop(rej_idx)

    # (8) give up ------------------------------------------------------------

    def _k8_giveup(self, dt):
        done = ((self.state == S_TRANSIT)
                & ((self.fatigue > self.cfg.give_up_after_s)
                   | (self.n_hops >= MAX_HOPS)))
        idx = done.nonzero(as_tuple=True)[0]
        if idx.numel():
            self.state[idx] = S_GAVEUP
            self._emit(idx, E_GAVEUP)

    # -- visualisation frames ------------------------------------------------

    def frame(self) -> dict:
        """Per-block aggregates for replay.

        The event stream records who changed state, which is what you need to
        reconstruct an individual. A map needs the opposite: how many are here
        now, and what do they believe. Belief in particular appears nowhere in
        the event stream -- it is a field, not an agent property -- so it has
        to be sampled here or it cannot be drawn at all.
        """
        transit = torch.bincount(self.block_l,
                                 weights=(self.state == S_TRANSIT).to(torch.float32),
                                 minlength=self.nb)
        sheltered = torch.bincount(self.block_l,
                                   weights=(self.state == S_SHELTERED).to(torch.float32),
                                   minlength=self.nb)
        gaveup = torch.bincount(self.block_l,
                                weights=(self.state == S_GAVEUP).to(torch.float32),
                                minlength=self.nb)
        # Peak believed wait across a block's candidates: one number that says
        # "people here think somewhere they were heading is full".
        belief = self.bbelief.max(dim=1).values
        # How many shelters the average person standing here has heard of.
        # This is the layer that shows information spreading -- the thing the
        # whole argument is about, and the one quantity a map can actually
        # animate. It appears in no other output.
        moving = (self.state == S_TRANSIT).to(torch.float32)
        kn = self._popcount(self.known).to(torch.float32)
        known_sum = torch.bincount(self.block_l, weights=kn * moving,
                                   minlength=self.nb)
        n_here = torch.bincount(self.block_l, weights=moving,
                                minlength=self.nb).clamp_min(1.0)
        return {
            "t_min": round(self.t / 60.0, 2),
            "transit": transit.to(torch.int32).cpu().numpy(),
            "sheltered": sheltered.to(torch.int32).cpu().numpy(),
            "gaveup": gaveup.to(torch.int32).cpu().numpy(),
            "belief": belief.cpu().numpy(),
            "known": (known_sum / n_here).cpu().numpy(),
        }

    # -- totals --------------------------------------------------------------

    def finish(self):
        self._flush_events()
        self.writer.close()

    def _time_quantiles(self) -> dict[str, Any]:
        """When people reached safety, not just how many did.

        Two families of number here, and they are not interchangeable:

        * ``t_p50/p90_min_of_sheltered`` are quantiles over the people who got
          in. They carry a survivorship bias by construction -- an intervention
          that turns slow arrivals into give-ups improves p90 while helping
          nobody. The name says ``_of_sheltered`` for that reason. Never quote
          them as a benefit on their own.
        * ``share_safe_by_Xmin`` divides by the whole population, so it cannot
          be gamed that way. Lead with these.

        Measured case: the LLM arm cut p90 from 52.7 to 35.8 min while
        sheltering 14 % fewer people. Almost all of that "improvement" is the
        slow tail dropping out of the sample.
        """
        st_ = self.shelter_time
        ok = ~torch.isnan(st_)
        n_ok = int(ok.sum().item())
        out: dict[str, Any] = {"n_with_time": n_ok}
        if n_ok == 0:
            return out
        v = st_[ok]
        for q in (0.5, 0.9):
            out[f"t_p{int(q*100)}_min_of_sheltered"] = round(
                float(torch.quantile(v, q).item()) / 60.0, 2)
        # Share of the whole city safe by each planning threshold.
        for mins in (15, 30, 60, 120):
            share = float((v <= mins * 60).sum().item()) / self.n
            out[f"share_safe_by_{mins}min"] = round(share, 5)
        return out

    @staticmethod
    def _gini(v):
        """Concentration of arrivals across shelters.

        If guidance herds people onto a few sites, occupancy becomes unequal
        even while total sheltered barely moves -- which is exactly the extreme
        case where leadership hurts locally.
        """
        x = torch.sort(v.to(torch.float64))[0]
        n = x.numel()
        s = x.sum()
        if n == 0 or float(s) == 0.0:
            return 0.0
        idx = torch.arange(1, n + 1, device=x.device, dtype=torch.float64)
        return float(((2 * idx - n - 1) * x).sum() / (n * s))

    @staticmethod
    def _popcount(x):
        """Bits set per element, for int32 tensors."""
        c = torch.zeros_like(x)
        for i in range(K_BELIEF):
            c = c + ((x >> i) & 1)
        return c

    def totals(self) -> dict[str, Any]:
        c = lambda v: int((self.state == v).sum().item())
        indoors, transit = c(S_INDOORS), c(S_TRANSIT)
        sheltered, gaveup = c(S_SHELTERED), c(S_GAVEUP)
        sh = self.state == S_SHELTERED
        return {
            "t_minutes": round(self.t / 60.0, 1),
            "indoors": indoors,
            "in_transit": transit,
            "sheltered": sheltered,
            "gave_up": gaveup,
            # Three different failures that the block-scale engine reported as
            # one number. Which dominates indicates whether the scenario needs
            # more shelters, better routes, or neither.
            "gave_up_no_path": int(self.no_path.sum().item()),
            "gave_up_exhausted": gaveup - int(self.no_path.sum().item()),
            "unsheltered_share": round(1.0 - sheltered / self.n, 4),
            "capacity_share_of_population": round(
                float(self.capacity.sum().item()) / self.n, 4),
            "accounted": indoors + transit + sheltered + gaveup,
            "n_agents": self.n,
            "conservation_error": indoors + transit + sheltered + gaveup - self.n,
            "shelter_occupancy": float(self.occupancy.sum().item()),
            "shelter_capacity": float(self.capacity.sum().item()),
            "shelter_utilisation": round(
                float(self.occupancy.sum().item())
                / max(float(self.capacity.sum().item()), 1.0), 4),
            "overfilled_shelters": int((self.occupancy > self.capacity).sum().item()),
            "mean_dist_walked_m": float(self.dist_walked[sh].mean().item()) if sheltered else None,
            "median_dist_walked_m": float(self.dist_walked[sh].median().item()) if sheltered else None,
            "mean_hops": float(self.n_hops[sh].to(torch.float32).mean().item()) if sheltered else None,
            "distinct_destinations": int(torch.unique(self.target[sh]).numel()) if sheltered else 0,
            "events": self.writer.n_events,
            "mean_switches": float(self.switches.to(torch.float32).mean().item()),
            "rethink_events": int(self.rethought),
            "rejections_at_full_gate": int(self.rejections),
            "shelter_occupancy_gini": round(self._gini(self.occupancy), 4),
            **self._time_quantiles(),
            "still_searching": int(((self.state == S_TRANSIT)
                                    & (self.target < 0)).sum().item()),
            "knows_nothing": int((self.known == 0).sum().item()),
            "mean_shelters_known": round(float(
                self._popcount(self.known).to(torch.float32).mean().item()), 3),
            "share_who_ever_switched": round(float(
                (self.switches > 0).to(torch.float32).mean().item()), 4),
        }
