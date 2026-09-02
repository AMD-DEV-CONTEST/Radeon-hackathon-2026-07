#!/usr/bin/env python3
"""
determinex_amplified_solve.py -- the unified Correctness Amplifier loop
====================================================================
Composes all seven amplifier pieces into one call, so ANY model -- however small
-- solves a task correctly or surfaces an honest, proven reason it cannot:

    Ingest (lang/oracle)            determinex_ingest
      -> Decompose to leaves        determinex_decompose      (#2)
         per leaf:
           Context provision        determinex_context        (#4)
           Case retrieval           determinex_case_memory    (#3)
           Output-contract guard    determinex_contract       (#6)
           Verified search          determinex_verified_search(#1)
             with model routing     determinex_router         (#7)
             and progress/loop      determinex_progress       (#5)
      -> on miss: Adjudicate        determinex_adjudicator    (no false surrender)
      -> on solve: admit to memory  determinex_case_memory    (flywheel at inference)

Correctness is bounded by the oracle's soundness (pair with determinex_test_validator),
never by the model's strength. This is the engine behind "any LLM works anything
and is right."

This module is usable two ways:
  * `amplified_solve(...)` -- programmatic, with your own generate/verify callables.
  * as the patch generator inside the hive: wrap the builder model + compiler
    oracle (see `make_hive_solver`).
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
from determinex_contract import guard, nonempty_contract  # noqa: E402
from determinex_decompose import Capability, Leaf, decompose, recommend_capability  # noqa: E402
from determinex_router import ModelEntry, ModelRouter  # noqa: E402

# verify takes (candidate, allowed_check_ids|None) -> object with .passed/.failures
SliceVerifyFn = Callable[[str, "list[str] | None"], object]
GenerateFn = Callable[[str, float], str]


@dataclass
class LeafResult:
    unit: str
    size: int
    solved: bool
    model_used: str
    next_moves: list[str] = field(default_factory=list)


@dataclass
class AmplifiedResult:
    solved: bool  # all leaves solved
    leaves_total: int
    leaves_solved: int
    leaf_results: list[LeafResult] = field(default_factory=list)
    blocked_moves: list[str] = field(default_factory=list)  # union of unsolved leaf moves

    @property
    def summary(self) -> str:
        if self.solved:
            return f"SOLVED all {self.leaves_total} leaves (oracle-verified)."
        return (
            f"{self.leaves_solved}/{self.leaves_total} leaves solved; "
            f"remaining moves: {sorted(set(self.blocked_moves))}"
        )


def amplified_solve(
    check_ids: list[str],
    slice_verify: SliceVerifyFn,
    models: list[ModelEntry],
    leaf_prompt: Callable[[Leaf], str],
    capability: Capability | None = None,
    k: int = 8,
    rounds: int = 2,
    contract=nonempty_contract,
    case_memory=None,
) -> AmplifiedResult:
    """Solve a task given its oracle checks and one or more registered models."""
    cap = capability or recommend_capability(models[0].capability_hint or models[0].name)
    leaves = decompose(check_ids, cap)
    router = ModelRouter(models, k=k, rounds=rounds)

    leaf_results: list[LeafResult] = []
    blocked: list[str] = []
    for leaf in leaves:
        # leaf-restricted oracle: only this leaf's checks must pass
        def verify(candidate: str, _ids=leaf.check_ids):
            return slice_verify(candidate, _ids)

        prompt = leaf_prompt(leaf)
        # case retrieval -> prepend a worked verified example, raising p
        if case_memory is not None:
            cases = case_memory.retrieve(prompt, k=2)
            if cases:
                prompt += "\n\n# Verified examples of similar fixes:\n" + "\n".join(
                    f"## {c.tool}\n{c.solution[:400]}" for c in cases
                )

        # wrap every model with the output-contract guard (well-formed floor)
        guarded = [
            ModelEntry(m.name, m.tier, m.cost, guard(m.generate, contract), m.capability_hint)
            for m in models
        ]
        router.models = sorted(guarded, key=lambda m: (m.tier, m.cost))

        route = router.solve_leaf(verify, prompt, start_tier=1)
        moves = route.search.next_moves if route.search else []
        leaf_results.append(
            LeafResult(
                unit=leaf.unit,
                size=leaf.size,
                solved=route.solved,
                model_used=route.model_used,
                next_moves=moves,
            )
        )
        if route.solved and case_memory is not None and route.search and route.search.best:
            case_memory.add(signature=prompt, solution=route.search.best.text, oracle_passed=True)
        if not route.solved:
            blocked += moves

    n_solved = sum(1 for r in leaf_results if r.solved)
    # `bool(leaves) and ...` is load-bearing. With no leaves this was `0 == 0` -> solved=True,
    # reported as "SOLVED all 0 leaves (oracle-verified)" without ever calling the model or the
    # oracle. Verified by passing generate/verify functions that raise if invoked: it returned
    # solved=True. Zero leaves is reachable whenever the upstream check list is empty -- an
    # ingest that flags SYNTHESIZE, a JUnit parse that names no checks, or a filter that removes
    # them all -- and "vacuously true" is the one thing an oracle-backed claim may never be.
    return AmplifiedResult(
        solved=bool(leaves) and n_solved == len(leaves),
        leaves_total=len(leaves),
        leaves_solved=n_solved,
        leaf_results=leaf_results,
        blocked_moves=blocked,
    )


# ---------------------------------------------------------------------------
# Hive wiring: turn the builder model + compiler oracle into an amplified solver.
# ---------------------------------------------------------------------------
def make_hive_solver(
    builder_generate: GenerateFn,
    compiler_verify,
    *,
    model_hint: str = "qwen2.5-coder:1.5b",
    escalation_generate: GenerateFn | None = None,
):
    """Produce an `solve(check_ids, leaf_prompt) -> AmplifiedResult` that the hive
    can call instead of single-shot generation. `compiler_verify(candidate, ids)`
    runs the Compiler Oracle restricted to the given checks; `builder_generate` is
    the local model. An optional `escalation_generate` is a stronger model the
    router climbs to when the local model exhausts on a leaf."""
    models = [
        ModelEntry(
            "local-builder", tier=1, cost=0.0, generate=builder_generate, capability_hint=model_hint
        )
    ]
    if escalation_generate is not None:
        models.append(ModelEntry("escalation", tier=3, cost=1.0, generate=escalation_generate))

    def solve(check_ids: list[str], leaf_prompt: Callable[[Leaf], str], **kw) -> AmplifiedResult:
        return amplified_solve(check_ids, compiler_verify, models, leaf_prompt, **kw)

    return solve


def _demo() -> int:
    """A 1.5B-class model (p=0.15/check) solves a 6-check task by decomposition +
    verified search that it could never solve in one shot."""
    import random
    from dataclasses import dataclass as dc

    @dc
    class _O:
        passed: bool
        failures: list

    checks = [f"tests.mod_{i // 2}.test_case_{i}" for i in range(6)]

    # the "correct" answer for a leaf is the literal 'FIX:<unit>'
    def slice_verify(candidate, ids):
        from determinex_adjudicator import Failure
        from determinex_decompose import _unit_of

        want = {f"FIX:{_unit_of(c)}" for c in (ids or checks)}
        ok = candidate.strip() in want and len(want) == 1
        return _O(ok, [] if ok else [Failure(ids[0] if ids else "t", "leaf", "wrong leaf fix")])

    def weak(prompt, temp):
        # 15% chance to emit the right leaf fix, else noise
        unit = prompt.split("UNIT=")[-1].strip()
        return f"FIX:{unit}" if random.random() < 0.15 else "WRONG"

    def leaf_prompt(leaf):
        return f"Fix the failing checks. UNIT={leaf.unit}"

    random.seed(11)
    models = [
        ModelEntry(
            "local-1.5b", tier=1, cost=0.0, generate=weak, capability_hint="qwen2.5-coder:1.5b"
        )
    ]
    solved = 0
    for _ in range(50):
        r = amplified_solve(
            checks, slice_verify, models, leaf_prompt, capability=Capability.TINY, k=20, rounds=2
        )
        solved += r.solved
    print("1.5B-class model (p=0.15/check) on a 6-check task:")
    print(f"  one-shot success would be ~0.15^6 = {0.15**6:.6f}")
    print(f"  amplified (decompose+verified search): solved {solved}/50 = {100 * solved / 50:.0f}%")
    return 0


if __name__ == "__main__":
    sys.exit(_demo())
