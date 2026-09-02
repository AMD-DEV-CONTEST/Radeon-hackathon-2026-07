"""The LLM-driven leader tier.

The simulator supports a configurable hierarchy of local coordinators. A
selected cohort reasons with the locally deployed language model instead of a
fixed rule, while the remaining coordinators follow the deterministic policy.

What a leader does is not move differently. A leader changes the *beliefs* of
the blocks in their jurisdiction, which is how one person redirects thousands
without any central scheduler. That matters for the argument the paper makes:
under loss of power, water and network, guidance has to be local and
distributed, not top-down.

Concurrency is central to performance. The llama.cpp server can run multiple
slots with continuous batching, and this module keeps them busy with a thread
pool. Threads are sufficient because the GIL is released across socket reads.
"""

from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np
import torch
import urllib.request

from .agent_swarm import S_TRANSIT, S_SHELTERED
from .jurisdictions import equal_population_partition, partition_report

#: The leader action meaning "hold where you are", as opposed to a shelter id.
HOLD = -1

_PROMPT = """You direct evacuation for {tier} {lid} in a city after a major earthquake.

Your area right now:
- {n_transit} people still walking, {n_sheltered} already sheltered
- crowding: {crowd_desc}
- shelters your people are heading to, with room left RIGHT NOW:
{shelter_lines}

Power, water and network are down. You cannot call anyone above you.

{decision_rule}

Reply with ONE line of JSON only:
{{"first": <shelter_id>, "second": <shelter_id or -1>, "third": <shelter_id or -1>, "why": "<a few words>"}}"""


#: Shown when at least one shelter has confirmed room. Holding must not sit
#: alongside a non-empty list as an equally reasonable answer, or the model
#: takes it: with four open shelters listed, an always-present hold instruction
#: produced hold on 100 % of 5,124 decisions.
_RULE_PICK = (
    "Every shelter listed above has been confirmed to have room.\n"
    "Rank up to three of them, best first. Naming only one sends your whole\n"
    "area to a single gate: you command roughly 54,000 people and the median\n"
    "shelter holds 2,000, so a single name oversubscribes it about 27 times.\n"
    "Use -1 for second or third only if there is genuinely nothing else."
)

#: Shown only when nothing reachable can admit anyone.
_RULE_HOLD = (
    "Nothing within reach can admit anyone right now, so answer send_to -1:\n"
    "tell people to hold where they are. Moving them when no shelter can take\n"
    "them only tires them out."
)


def _grammar(options):
    """A GBNF that can only emit one well-formed decision naming a real shelter.

    Left free, the model answers with a ```json fence around a schema it made
    up: 54.7 % of 3,940 replies were unusable and 119 named a shelter that was
    never on offer. Constraining the decoder makes both failure modes
    unrepresentable rather than merely unlikely -- the ids in the grammar ARE
    this leader's candidate set.

    ``why`` is deliberately loose and its minimum is one word: forcing a longer
    string makes the model pad with noise once it has said what it meant.
    """
    # "-1" is holding position, a real decision rather than a null one: when
    # every reachable shelter is full, redirecting people only moves them
    # between closed gates. Without this the leader's only verb is "go", and a
    # measured 63 % of briefs had nowhere worth going.
    ids = " | ".join(f'"{int(o)}"' for o in options) if options else '"-1"'
    if options:
        ids = ids + ' | "-1"'
    rules = [
        r'root ::= "{\"first\": " sid ", \"second\": " alt ", \"third\": " alt '
        r'", \"why\": \"" why "\"}"',
        f"sid ::= {ids}",
        f'alt ::= "-1" | {ids}',
        'why ::= word (" " word){0,7}',
        "word ::= [a-z]{2,12}",
    ]
    return "\n".join(rules) + "\n"


class LeaderTier:
    """Assigns jurisdictions, queries the model, and writes broadcasts."""

    def __init__(self, stepper, swarm, endpoint="http://127.0.0.1:8080/completion",
                 n_slots=32, interval_min=10.0, n_predict=64, leader_comm=0.5,
                 log_dir: str | Path | None = None, timeout=120.0):
        self.st = stepper
        self.swarm = swarm
        self.endpoint = endpoint
        self.n_slots = n_slots
        self.interval_s = interval_min * 60.0
        self.n_predict = n_predict
        #: Share of peer leaders reached per round. 0 = every leader knows only
        #: their own jurisdiction; 1 = the tier shares everything.
        self.leader_comm = leader_comm
        self.timeout = timeout
        self.log_dir = Path(log_dir) if log_dir else None
        if self.log_dir:
            self.log_dir.mkdir(parents=True, exist_ok=True)

        self.ids = np.asarray(swarm.llm_ids, dtype=np.int64)
        self.n_leaders = len(self.ids)
        self.tier_of = {int(a): ("district" if a in set(
            swarm.leader_ids.get(6, np.array([], dtype=np.int64)).tolist())
            else "subdistrict") for a in self.ids.tolist()}

        # Jurisdiction: an equal-population, spatially compact partition, not
        # a Voronoi diagram around randomly scattered leaders. The Voronoi
        # version left 53 of 1,000 jurisdictions empty while one held 109,237
        # people; see simulator/jurisdictions.py for the measurements.
        owner, seed = equal_population_partition(
            stepper.bx.cpu().numpy(), stepper.by.cpu().numpy(),
            np.asarray(swarm.layer.population, dtype=np.float64), self.n_leaders)
        self.jurisdiction = torch.as_tensor(owner).to(stepper.dev)
        self.partition = partition_report(
            owner, swarm.layer.population, self.n_leaders)
        #: One representative block per jurisdiction, used to measure network
        #: distance to shelters outside the four its people happen to be
        #: walking towards.
        self.seed_blocks = torch.as_tensor(seed.astype(np.int64)).to(stepper.dev)
        # Move each leader into the area they command. Agents are generated
        # block by block, so the block array is sorted and the first agent of a
        # block is one searchsorted away.
        first = np.searchsorted(swarm.block, np.arange(stepper.nb), side="left")
        self.ids = np.asarray(
            [first[s] if first[s] < swarm.n_agents else self.ids[j]
             for j, s in enumerate(seed)], dtype=np.int64)
        # What each leader BELIEVES about every shelter's occupancy, and how
        # stale that belief is. Reading st.occupancy directly made every leader
        # omniscient about all shelters, which is both unrealistic and
        # self-defeating: if everyone already knows, there is nothing for
        # leaders to tell each other and communication efficiency cannot matter.
        #
        # A leader observes the shelters inside their own jurisdiction -- they
        # can see the queue at the gate -- and learns about the rest only from
        # colleagues.
        ns = stepper.ns
        self.occ_belief = torch.full((self.n_leaders, ns), float("nan"),
                                     device=stepper.dev)
        self.occ_age = torch.full((self.n_leaders, ns), float("inf"),
                                  device=stepper.dev)
        #: Which leader can see which shelter directly.
        self.owns_shelter = self._shelter_owner(stepper)
        #: Peer leaders each leader can reach. Adjacency of jurisdictions is
        #: approximated by nearest seeds, which is what "the next subdistrict
        #: over" means in practice.
        self.peers = self._leader_peers(stepper, k=6)
        self.exchanges = 0
        self.next_call_t = 0.0
        self.rounds = 0
        self.calls = 0
        self.failures = 0
        self.unparseable = 0
        self.hallucinated = 0
        self.applied = 0
        self.sent_to_full = 0
        self.grammar_sent = 0
        self.rounds_with_no_room = 0
        self.held = 0
        self.ranked_named = 0
        self.llm_seconds = 0.0
        self.context_bytes = 0
        self._pool = ThreadPoolExecutor(max_workers=n_slots)

    # -- setup ---------------------------------------------------------------

    def _assign_blocks(self) -> torch.Tensor:
        st = self.st
        lb = st.block[torch.as_tensor(self.ids, device=st.dev)].long()
        lx, ly = st.bx[lb], st.by[lb]
        out = torch.empty(st.nb, dtype=torch.int32, device=st.dev)
        chunk = max(1, int(4e7 // max(self.n_leaders, 1)))
        for s in range(0, st.nb, chunk):
            e = min(s + chunk, st.nb)
            dx = st.bx[s:e].unsqueeze(1) - lx.unsqueeze(0)
            dy = st.by[s:e].unsqueeze(1) - ly.unsqueeze(0)
            out[s:e] = torch.argmin(dx * dx + dy * dy, dim=1).to(torch.int32)
        return out

    def _shelter_owner(self, st):
        """Which jurisdiction each shelter sits in."""
        # A shelter's home block is the block whose network distance to it is
        # zero; rdist already encodes that, so read it off rather than redoing
        # a spatial join.
        home = st.rdist.argmin(dim=1)                     # (n_shelters,)
        return self.jurisdiction[home].long()             # -> leader index

    def _leader_peers(self, st, k=6):
        """The k nearest other leaders, as a stand-in for adjacent jurisdictions."""
        sx = st.bx[self.seed_blocks]
        sy = st.by[self.seed_blocks]
        d = (sx.unsqueeze(1) - sx.unsqueeze(0)) ** 2 +             (sy.unsqueeze(1) - sy.unsqueeze(0)) ** 2
        d.fill_diagonal_(float("inf"))
        return torch.topk(d, k=min(k, self.n_leaders - 1),
                          largest=False).indices          # (n_leaders, k)

    def observe_and_exchange(self, comm: float):
        """Direct observation, then word between colleagues.

        ``comm`` is the share of a leader's peers they actually manage to reach
        this round -- the communication efficiency the experiment varies. At 0
        every leader knows only their own patch; at 1 the tier is effectively
        one informed body.
        """
        st = self.st
        now = st.t
        # 1. See your own shelters.
        mine = self.owns_shelter                                  # (n_shelters,)
        rows = mine
        cols = torch.arange(st.ns, device=st.dev)
        self.occ_belief[rows, cols] = st.occupancy.to(torch.float32)
        self.occ_age[rows, cols] = now

        if comm <= 0.0:
            return
        # 2. Adopt whatever a peer knows more recently than you do.
        k = self.peers.shape[1]
        take = torch.rand((self.n_leaders, k), device=st.dev) < comm
        for c in range(k):
            src = self.peers[:, c]
            sel = take[:, c]
            if not bool(sel.any()):
                continue
            cand_age = self.occ_age[src]
            fresher = cand_age < self.occ_age
            upd = fresher & sel.unsqueeze(1)
            self.occ_belief = torch.where(upd, self.occ_belief[src], self.occ_belief)
            self.occ_age = torch.where(upd, cand_age, self.occ_age)
            self.exchanges += int(upd.sum().item())

    # -- one round -----------------------------------------------------------

    def due(self) -> bool:
        return self.st.t >= self.next_call_t

    def run_round(self) -> dict[str, Any]:
        """Query all leaders concurrently and apply their broadcasts."""
        st = self.st
        self.next_call_t = st.t + self.interval_s
        # What a leader can act on is what they have observed or been told.
        self.observe_and_exchange(self.leader_comm)
        briefs = self._briefs()
        if not briefs:
            return {"round": self.rounds, "calls": 0}

        t0 = time.perf_counter()
        results = list(self._pool.map(self._ask, briefs))
        elapsed = time.perf_counter() - t0
        self.llm_seconds += elapsed
        self.calls += len(briefs)

        self._apply(briefs, results)
        if self.log_dir:
            # L3: the full context of every LLM decision, kept verbatim. This
            # is the audit trail that makes a leader's reasoning inspectable.
            rec = [{"t_min": round(st.t / 60, 1), "leader": b["lid"],
                    "tier": b["tier"], "prompt": b["prompt"], "reply": r}
                   for b, r in zip(briefs, results)]
            blob = json.dumps(rec, ensure_ascii=False)
            self.context_bytes += len(blob.encode())
            (self.log_dir / f"round_{self.rounds:03d}.json").write_text(
                blob, encoding="utf-8")
        self.rounds += 1
        return {"round": self.rounds, "calls": len(briefs),
                "seconds": round(elapsed, 2),
                "per_call_s": round(elapsed / max(len(briefs), 1), 3)}

    def _briefs(self) -> list[dict]:
        """Aggregate each jurisdiction to a few numbers, on the GPU."""
        st = self.st
        j = self.jurisdiction.long()
        moving = (st.state == S_TRANSIT)
        agent_j = j[st.block_l]

        n_tr = torch.bincount(agent_j, weights=moving.to(torch.float32),
                              minlength=self.n_leaders)
        shel = (st.state == S_SHELTERED).to(torch.float32)
        n_sh = torch.bincount(agent_j, weights=shel, minlength=self.n_leaders)
        dens = (st.crowd / st.block_area)
        mean_dens = (torch.bincount(j, weights=dens, minlength=self.n_leaders)
                     / torch.bincount(j, minlength=self.n_leaders).clamp_min(1))

        # Which shelters this jurisdiction is actually sending people to.
        tgt = st.target
        # Belief, not truth. A leader who has heard nothing about a distant
        # shelter has to fall back on its nominal capacity, which is exactly
        # the kind of stale assumption that sends people to a full gate.
        bel = self.occ_belief.clone()
        bel = torch.where(torch.isnan(bel), torch.zeros_like(bel), bel)
        occ_all = bel.cpu().numpy()
        cap = st.capacity.cpu().numpy()
        known_occ = (~torch.isnan(self.occ_belief)).cpu().numpy()

        n_tr_c = n_tr.cpu().numpy()
        n_sh_c = n_sh.cpu().numpy()
        md_c = mean_dens.cpu().numpy()

        # Top shelters per leader, computed once on host from a sampled slice:
        # a full n x n_leaders crosstab is not worth its cost for a prompt.
        samp = torch.randint(0, st.n, (min(2_000_000, st.n),), device=st.dev)
        s_j = agent_j[samp].cpu().numpy()
        s_t = tgt[samp].cpu().numpy()
        s_mv = moving[samp].cpu().numpy()

        briefs = []
        for k in range(self.n_leaders):
            if n_tr_c[k] < 500:          # nothing left to direct
                continue
            sel = s_t[(s_j == k) & s_mv]
            if sel.size == 0:
                continue
            occ = occ_all[k]
            # A commander's agenda comes from what THEY know, not from what the
            # public is already doing. Deriving the brief from current targets
            # made the leader tier mute exactly when it mattered most: with no
            # prior knowledge nobody is heading anywhere, so there was nothing
            # to talk about and 100 % of 5,124 decisions came out "hold".
            free_k = np.where(known_occ[k], np.maximum(cap - occ, 0.0), 0.0)
            top = np.asarray(self._nearest_with_room(k, free_k, 4), dtype=np.int64)
            # Where people are already heading is context, not the agenda: it
            # tells the leader which shelter is about to be overrun.
            # -1 means "has no destination yet". Printing it as a shelter id
            # made the brief read "heading to: 0", which the model read as
            # "zero shelters" and answered hold to -- with four open shelters
            # listed directly above it.
            real = sel[sel >= 0]
            if real.size:
                ids, cnt = np.unique(real, return_counts=True)
                heading = ids[np.argsort(-cnt)[:2]]
            else:
                heading = np.empty(0, dtype=np.int64)
            free_of = {int(s): float(free_k[s]) for s in top}
            # Only shelters that can still take someone. With every candidate
            # on the table, 46.1 % of decisions named one with zero places left
            # -- a walk that ends at a closed gate. Grammar can guarantee the id
            # is real; it cannot make the judgement correct, so the wrong
            # answers are removed from the choice set instead.
            openable = [int(s) for s in top if free_of[int(s)] > 0]
            lines = []
            for sid in openable:
                lines.append(f"  shelter {sid}: capacity {int(cap[sid]):,}, "
                             f"{int(free_of[sid]):,} places free")
            if not openable:
                # Nothing within reach can admit anyone. Redirecting here only
                # churns people between closed gates, so the honest option is
                # to hold -- which is why -1 exists in the action space.
                lines.append("  (none -- every shelter within reach is full)")
                self.rounds_with_no_room += 1
            aid = int(self.ids[k])
            if len(heading):
                busy = ", ".join(str(int(s)) for s in heading)
                lines.append(f"  (most of your people are already walking "
                             f"towards: {busy})")
            crowd_desc = ("severe" if md_c[k] > 2.0 else
                          "moderate" if md_c[k] > 0.8 else "light")
            prompt = _PROMPT.format(
                tier=self.tier_of.get(aid, "subdistrict"), lid=k,
                n_transit=f"{int(n_tr_c[k]):,}", n_sheltered=f"{int(n_sh_c[k]):,}",
                crowd_desc=crowd_desc, shelter_lines="\n".join(lines),
                decision_rule=_RULE_PICK if openable else _RULE_HOLD)
            opts = openable
            briefs.append({"k": k, "lid": k, "aid": aid,
                           "tier": self.tier_of.get(aid, "subdistrict"),
                           "prompt": prompt, "options": opts,
                           "free": {int(s): float(max(0.0, cap[s] - occ[s]))
                                    for s in top},
                           "grammar": _grammar(opts)})
        return briefs

    def _nearest_with_room(self, k: int, free_np, n: int):
        """The n shelters with space that are closest to jurisdiction k.

        Distance is network distance along the routing tree, not straight line:
        a shelter 400 m across a river is a 4 km walk, and only the routing
        table knows that.
        """
        room = np.flatnonzero(free_np > 0)
        if room.size == 0:
            return []
        st = self.st
        b = int(self.seed_blocks[k].item())
        d = st.rdist[torch.as_tensor(room, device=st.dev), b].cpu().numpy()
        ok = np.isfinite(d) & (d < 3.0e38)
        if not ok.any():
            return []
        room, d = room[ok], d[ok]
        return room[np.argsort(d)[:n]].tolist()

    def _ask(self, brief: dict) -> str:
        payload = {
            "prompt": brief["prompt"], "n_predict": self.n_predict,
            "temperature": 0.3, "top_p": 0.9, "stop": ["\n\n"], "cache_prompt": True,
        }
        # Constrained decoding, when the brief has a candidate set to constrain
        # to. A brief with no options cannot produce a valid grammar (an empty
        # alternation is a parse error server-side), so those go out free and
        # are counted as unparseable if the model rambles.
        if brief.get("grammar"):
            payload["grammar"] = brief["grammar"]
            self.grammar_sent += 1
        body = json.dumps(payload).encode()
        req = urllib.request.Request(
            self.endpoint, data=body, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read())["content"]
        except Exception as exc:                      # noqa: BLE001
            self.failures += 1
            return f"__error__ {type(exc).__name__}"

    # -- apply ---------------------------------------------------------------

    def _apply(self, briefs, results):
        """Turn replies into belief writes over the leader's blocks.

        A leader does not teleport anyone. Lowering the believed queue at the
        recommended shelter and raising it at the one to avoid is exactly what
        a loudspeaker announcement does to the choice model: it shifts the
        logit, and people still decide for themselves.
        """
        st = self.st
        send, free_of, blocks_for = [], [], []
        for b, txt in zip(briefs, results):
            if txt.startswith("__error__"):
                continue
            m = re.search(r'"first"\s*:\s*(-?\d+)', txt)
            ranked = [int(g.group(1)) for g in
                      (re.search(rf'"{k}"\s*:\s*(-?\d+)', txt)
                       for k in ("first", "second", "third")) if g]
            if not m:
                # A 200 response is not a usable decision. Counting only HTTP
                # errors once let a misconfigured server report "0 failures"
                # for 4,601 calls whose every reply was the same junk token.
                self.unparseable += 1
                continue
            sid = int(m.group(1))
            # -1 is holding position, a legal action rather than an id. It is
            # never in the option list, so checking membership first counted
            # 4,539 of 4,555 holds as hallucinations and threw the whole
            # leader tier away -- the run came out identical to LLM-off.
            if sid != HOLD and sid not in b["options"]:
                self.hallucinated += 1        # a shelter id that is not on offer
                continue
            if sid >= 0 and b.get("free", {}).get(sid, 1.0) <= 0.0:
                # Grammar cannot stop this: the id is real and on offer, the
                # judgement is just wrong. Worth measuring rather than hiding,
                # because it is the model's reasoning quality, not its syntax.
                self.sent_to_full += 1
            # Keep the ranking, filtered to ids actually on offer. The order is
            # the leader's preference; how much weight each one gets is decided
            # at broadcast time from free capacity, not by the model.
            keep = [s for s in ranked if s >= 0 and s in b["options"]]
            send.append(keep or [sid])
            free_of.append(b.get("free", {}))
            blocks_for.append(b["k"])
        self.applied += len(send)

        if not send:
            return
        j = self.jurisdiction.long()
        weight = 4.0                          # district/subdistrict trust weight
        held = [k for k, r in zip(blocks_for, send) if not r or r[0] < 0]
        self.held += len(held)
        K = st.bbelief.shape[1]
        for k, ranked, free in zip(blocks_for, send, free_of):
            if not ranked or ranked[0] < 0:
                # Holding position writes nothing and, crucially, does not stamp
                # influenced_at below -- so it does not trigger a wave of
                # re-decisions. Suppressing churn IS the action.
                continue
            mask = (j == k)
            cand = st.cand[mask, :K]

            # Weight the ranked shelters by the room each actually has, not by
            # rank alone. One leader commands ~54,000 people and the median
            # shelter holds 2,000, so a single recommendation oversubscribes by
            # about 27x by construction -- the herding was in the action space,
            # not in the model's judgement. Splitting the broadcast across the
            # ranking in proportion to free capacity is what lets the crowd's
            # own logit choice spread the flow instead of collapsing it.
            room = [max(float(free.get(s, 0.0)), 1.0) for s in ranked]
            tot = sum(room)
            shares = [r / tot for r in room]
            self.ranked_named += len(ranked)

            bb = st.bbelief[mask]
            known_bits = torch.zeros(int(mask.sum()), dtype=torch.int32,
                                     device=st.dev)
            for s, share in zip(ranked, shares):
                slot = (cand == s)
                if not bool(slot.any()):
                    continue
                # Announcing a shelter tells people it EXISTS, which for most
                # of them is new. That is the leader's real contribution: an
                # opinion about a shelter nobody has heard of changes nothing.
                bit = slot.to(torch.int32).argmax(dim=1)
                known_bits = torch.bitwise_or(
                    known_bits,
                    torch.where(slot.any(dim=1), (1 << bit).to(torch.int32),
                                torch.zeros_like(bit, dtype=torch.int32)))
                bb = torch.where(slot, bb - 60.0 * weight * share, bb)
            st.bknown[mask] = torch.bitwise_or(st.bknown[mask], known_bits)
            st.bbelief[mask] = bb.clamp_min(-600.0)

        # Attribute influence in one pass. Doing it inside the loop would gather
        # over all agents once per leader instead of using one lookup through
        # the block's jurisdiction.
        moved = [k for k, r in zip(blocks_for, send) if r and r[0] >= 0]
        decided = torch.zeros(self.n_leaders, dtype=torch.bool, device=st.dev)
        if moved:
            decided[torch.as_tensor(moved, device=st.dev)] = True
        agent_j = j[st.block_l]
        touched = decided[agent_j]
        st.influenced_at[touched] = st.t
        st.leader_id[touched] = torch.as_tensor(
            self.ids, device=st.dev, dtype=torch.int32)[agent_j[touched]]

    def report(self) -> dict[str, Any]:
        return {
            "n_llm_leaders": self.n_leaders,
            "rounds": self.rounds,
            "calls": self.calls,
            "failures": self.failures,
            "unparseable_replies": self.unparseable,
            "hallucinated_shelter": self.hallucinated,
            "applied_decisions": self.applied,
            "applied_share": round(self.applied / max(self.calls, 1), 4),
            "partition": self.partition,
            "briefs_with_no_free_shelter": self.rounds_with_no_room,
            "hold_decisions": self.held,
            "shelters_named_total": self.ranked_named,
            "mean_shelters_per_broadcast": round(
                self.ranked_named / max(self.applied - self.held, 1), 2),
            "hold_share": round(self.held / max(self.applied, 1), 4),
            "leader_comm": self.leader_comm,
            "peer_updates": self.exchanges,
            "grammar_constrained_calls": self.grammar_sent,
            "grammar_share": round(self.grammar_sent / max(self.calls, 1), 4),
            "sent_to_full_shelter": self.sent_to_full,
            "sent_to_full_share": round(self.sent_to_full / max(self.applied, 1), 4),
            "llm_wall_seconds": round(self.llm_seconds, 1),
            "llm_wall_minutes": round(self.llm_seconds / 60, 2),
            "mean_call_s": round(self.llm_seconds / max(self.calls, 1), 3),
            "slots": self.n_slots,
            "l3_context_bytes": self.context_bytes,
            "l3_context_mb": round(self.context_bytes / 1024 ** 2, 2),
        }
