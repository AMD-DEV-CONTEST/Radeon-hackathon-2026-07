#!/usr/bin/env python3
"""
determinex_router.py -- Model-Agnostic Router (Amplifier piece #7)
===============================================================
"...any LLM, regardless of how good or large or small, can access this system."

This is the registry + routing that makes that concrete. Any model -- a local
1.5B, a cloud frontier model, a cloaked endpoint, an ensemble -- registers as a
`ModelEntry` exposing the universal contract `generate(prompt, temperature)->str`.
The router sends each leaf to the CHEAPEST model whose capability tier covers it,
and ESCALATES to the next tier when verified search on a leaf exhausts without a
pass. Cost goes down (small models do the easy leaves), correctness stays bounded
by the oracle (verified search guarantees it), and a leaf that no model can clear
surfaces honestly via the Adjudicator -- never a silent wrong answer.

    from determinex_router import ModelRouter, ModelEntry
    router = ModelRouter([
        ModelEntry("local-1.5b", tier=1, cost=0.0, generate=local_fn),
        ModelEntry("deepseek",   tier=3, cost=1.0, generate=cloud_fn),
        ModelEntry("opus",       tier=4, cost=5.0, generate=opus_fn),
    ])
    result = router.solve_leaf(verify=oracle_slice, prompt=leaf_prompt, start_tier=1)
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
from determinex_verified_search import SearchResult, VerifiedSearch  # noqa: E402

GenerateFn = Callable[[str, float], str]


@dataclass
class ModelEntry:
    name: str
    tier: int  # 1=tiny/cheap ... 4=frontier/expensive
    cost: float  # relative cost per call (for telemetry)
    generate: GenerateFn
    capability_hint: str = ""  # e.g. "qwen2.5-coder:1.5b" -> leaf sizing


@dataclass
class RouteResult:
    solved: bool
    model_used: str
    tier_used: int
    escalations: int
    total_cost: float
    search: SearchResult | None = field(default=None)


class ModelRouter:
    def __init__(self, models: list[ModelEntry], k: int = 8, rounds: int = 2):
        self.models = sorted(models, key=lambda m: (m.tier, m.cost))
        self.k = k
        self.rounds = rounds

    def _ladder(self, start_tier: int) -> list[ModelEntry]:
        return [m for m in self.models if m.tier >= start_tier]

    def solve_leaf(self, verify, prompt: str, start_tier: int = 1) -> RouteResult:
        """Route a single leaf up the capability ladder: cheapest first, escalate
        on a verified-search miss. Correctness is guaranteed by `verify` (the
        oracle), not by trusting any model."""
        escalations = 0
        cost = 0.0
        last: SearchResult | None = None
        ladder = self._ladder(start_tier)
        for i, entry in enumerate(ladder):
            # every tier BELOW the top hands a zero-signal leaf up immediately instead
            # of burning its full round budget; the top tier has nowhere to go, so it
            # keeps every round (see VerifiedSearch.early_escalate).
            vs = VerifiedSearch(
                verify=verify, k=self.k, rounds=self.rounds, early_escalate=(i < len(ladder) - 1)
            )
            res = vs.solve(entry.generate, prompt)
            cost += entry.cost * res.total_samples
            last = res
            if res.solved:
                return RouteResult(
                    solved=True,
                    model_used=entry.name,
                    tier_used=entry.tier,
                    escalations=escalations,
                    total_cost=cost,
                    search=res,
                )
            # if the Adjudicator says the failures are genuinely IMPOSSIBLE,
            # escalating to a bigger model cannot help -> stop honestly.
            if res.next_moves == [] and res.escalated and last is not None:
                # no reopenable moves found -> genuine ceiling, do not waste tiers
                break
            escalations += 1
        return RouteResult(
            solved=False,
            model_used=last and "exhausted-ladder" or "none",
            tier_used=start_tier,
            escalations=escalations,
            total_cost=cost,
            search=last,
        )


def main() -> int:
    # demo: a tiny model (p=0.1) escalating to a strong model (p=0.9)
    import random
    from dataclasses import dataclass as dc

    @dc
    class _O:
        passed: bool
        failures: list

    TARGET = "RIGHT"

    def verify(t):
        from determinex_adjudicator import Failure

        return _O(t.strip() == TARGET, [] if t.strip() == TARGET else [Failure("t", "eq", "wrong")])

    def weak(p):
        return lambda prompt, temp: TARGET if random.random() < p else "WRONG"

    random.seed(3)
    router = ModelRouter(
        [
            ModelEntry("local-1.5b", tier=1, cost=0.0, generate=weak(0.10)),
            ModelEntry("frontier", tier=4, cost=5.0, generate=weak(0.90)),
        ],
        k=6,
        rounds=1,
    )
    solved = sum(router.solve_leaf(verify, "x").solved for _ in range(100))
    print(f"router (tiny->frontier escalation): solved {solved}/100")
    return 0


if __name__ == "__main__":
    sys.exit(main())
