#!/usr/bin/env python3
"""
determinex_progress.py -- Progress / Loop Detector (Amplifier piece #5)
====================================================================
Weak models thrash: they emit the same wrong fix, or oscillate between two wrong
fixes, or plateau (the partial score stops improving). Without a detector the
loop burns budget forever. This promotes the seed in verified_search into a
standalone primitive that watches a stream of attempts and emits a DIRECTIVE:

    CONTINUE      -- making progress (partial score improving), keep going
    WIDEN         -- stalled but still producing novelty; raise temperature / K
    RE_DECOMPOSE  -- novelty but no progress; the step is too big -> split it
    ESCALATE      -- looping (no novelty) or repeated plateau -> route up / human

It is deterministic and model-agnostic: feed it (candidate_digest, score) tuples,
where score is "closer to solved is higher" (e.g. -n_failures). It never lets the
system spin in place, and it never *quits* without a reason it can name.

    from determinex_progress import ProgressTracker, Directive
    pt = ProgressTracker()
    d = pt.observe(digest="abc123", score=-7)   # 7 failing checks
    if d == Directive.ESCALATE: ...
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Directive(str, Enum):
    CONTINUE = "CONTINUE"
    WIDEN = "WIDEN"
    RE_DECOMPOSE = "RE_DECOMPOSE"
    ESCALATE = "ESCALATE"
    #: The remaining work is disproportionate to the progress being made, so continuing is
    #: not the answer -- something outside the loop has to change (a missing toolchain, a
    #: bigger model, a human). Distinct from ESCALATE, which means "this loop is stuck":
    #: OUT_OF_PROPORTION means "this loop is working, and it is not going to be enough."
    OUT_OF_PROPORTION = "OUT_OF_PROPORTION"


@dataclass
class ProgressTracker:
    """Watch a stream of attempts and say what to do next.

    THE ROUND COUNT IS NOT THE STOPPING RULE (2026-08-03). Ryan: *"we shouldn't be limited to
    three runs — take the delta from the previous run, how many errors to the next run and what
    that reduction is... if the number to fix is percentage too high, it stops and we figure out
    what to do (download toolchains, get backup, support), or we go until that number stops."*

    A fixed cap is wrong in both directions, and both were observable: a run that is removing
    errors steadily gets cut off mid-descent because it hit round 3, and a run that fixed
    nothing at all still burns its full allowance. What matters is the RATE — how many failing
    checks each round removes, and whether that rate is heading anywhere.

    So three questions replace "have we done N rounds yet":

      1. is the error count still FALLING?           -> CONTINUE, no cap
      2. has it STOPPED falling?                     -> the existing plateau/loop directives
      3. is the remaining work out of proportion
         to the rate of removal?                     -> OUT_OF_PROPORTION, stop and say why

    (3) is the new one and it is a projection, not a threshold on the raw count: from the
    observed reduction per round, how many more rounds would clearing the remainder take? If
    that is more than `max_projected_rounds`, the loop is working and still will not finish, so
    it says so instead of grinding. That is the moment to fetch a toolchain, a bigger model, or
    a person -- and the caller is told which, because `reason()` names the numbers.
    """

    plateau_patience: int = 4  # rounds of no score improvement before acting
    loop_patience: int = 2  # rounds of zero novelty before escalating
    #: Rounds to observe before the proportionality test is allowed to fire. Below this there
    #: is not enough of a trend to project from, and a first round that happens to fix nothing
    #: would abort a run that was about to work.
    min_rounds_before_projection: int = 3
    #: If clearing the remaining failures at the observed rate would take more rounds than
    #: this, stop. Deliberately generous: the goal is to catch "1 error removed per round with
    #: 40 to go", not to punish a slow but finite descent.
    #:
    #: Was 12, which a test immediately caught as too tight: a run removing 10 failures per
    #: round with 180 left projects to 18 rounds and was being called out-of-proportion --
    #: cutting off one of the healthiest descents the rule could see, which is the exact
    #: failure a fixed round cap had. The number has to sit above any descent that would
    #: actually finish and below the ones that would not.
    max_projected_rounds: int = 25
    #: Hard safety cap so an unbounded loop is still bounded by something. Only reached when
    #: progress genuinely continues that long, which is the case the round cap got wrong.
    absolute_max_rounds: int = 40
    _best_score: float = field(default=float("-inf"))
    _rounds_since_improve: int = 0
    _seen: set = field(default_factory=set)
    _rounds_no_novelty: int = 0
    _history: list = field(default_factory=list)
    #: One entry per ROUND: the best (lowest) failing-check count that round achieved. This is
    #: the series the rate rule reads; `_history` is per-candidate and too fine for it.
    _round_errors: list[int] = field(default_factory=list)
    _rounds_no_reduction: int = 0
    _last_delta: int = 0
    _projected_rounds: float = float("inf")

    def observe(self, digest: str, score: float) -> Directive:
        self._history.append((digest, score))
        novel = digest not in self._seen
        self._seen.add(digest)

        # novelty tracking (loop detection)
        if novel:
            self._rounds_no_novelty = 0
        else:
            self._rounds_no_novelty += 1

        # progress tracking (plateau detection)
        if score > self._best_score:
            self._best_score = score
            self._rounds_since_improve = 0
            return Directive.CONTINUE
        self._rounds_since_improve += 1

        # decide
        if self._rounds_no_novelty >= self.loop_patience:
            return Directive.ESCALATE  # the model only repeats itself
        if self._rounds_since_improve >= self.plateau_patience:
            # still producing novel-but-no-better candidates -> the step is too hard
            return Directive.RE_DECOMPOSE if novel else Directive.ESCALATE
        return Directive.WIDEN  # stalled but not yet stuck

    # ── the rate, not the count ──────────────────────────────────────────────────────────

    def round_errors(self, errors: int) -> Directive:
        """Observe one ROUND's failing-check count and say whether to run another.

        `errors` is the best (lowest) failure count seen in that round. Returns CONTINUE while
        the count is still falling, OUT_OF_PROPORTION when it is falling too slowly to ever
        finish, and ESCALATE when it has stopped falling or the safety cap is hit.

        Kept separate from `observe` on purpose: `observe` scores individual CANDIDATES, this
        scores a ROUND. Merging them would make "no improvement" mean two different things at
        two different granularities.
        """
        self._round_errors.append(int(errors))
        n = len(self._round_errors)
        first, cur = self._round_errors[0], self._round_errors[-1]

        # NO SHORTCUT FOR cur == 0. It looks like "solved, let the caller stop for a better
        # reason", and it is not: `round_errors` is only reached on a round that did NOT
        # solve, because a passing candidate returns out of the loop before this. So zero
        # failures here means the oracle reported no signal at all -- a broken verifier, an
        # empty failure list -- and treating it as success made the loop run its full 40-round
        # safety cap on a run that was producing nothing. Found by driving an out-of-proportion
        # case end to end: 40 rounds of "0 -> 0 failing checks" that should have stopped at 2.
        # Falling through lets the plateau rule below see it for what it is.

        if n >= 2:
            prev = self._round_errors[-2]
            self._last_delta = prev - cur
            if self._last_delta > 0:
                self._rounds_no_reduction = 0
            else:
                self._rounds_no_reduction += 1

        if n >= self.absolute_max_rounds:
            return Directive.ESCALATE

        # Stopped falling. Two rounds of no reduction is a plateau, not noise.
        if self._rounds_no_reduction >= 2:
            return Directive.ESCALATE

        # Falling, but fast enough? Project from the AVERAGE reduction so far rather than the
        # last round alone -- one lucky round should not licence twenty more.
        if n >= self.min_rounds_before_projection:
            removed = first - cur
            if removed <= 0:
                return Directive.OUT_OF_PROPORTION
            per_round = removed / (n - 1)
            self._projected_rounds = cur / per_round if per_round > 0 else float("inf")
            if self._projected_rounds > self.max_projected_rounds:
                return Directive.OUT_OF_PROPORTION

        return Directive.CONTINUE

    def reason(self) -> str:
        """Why the loop stopped, in numbers a caller can act on."""
        if not self._round_errors:
            return "no rounds observed"
        first, cur = self._round_errors[0], self._round_errors[-1]
        n = len(self._round_errors)
        per_round = (first - cur) / (n - 1) if n > 1 else 0.0
        proj = ("never" if per_round <= 0
                else f"~{cur / per_round:.0f} more rounds")
        return (
            f"{n} rounds: {first} -> {cur} failing checks "
            f"({per_round:+.1f}/round, {proj} to clear at that rate); "
            f"last delta {self._last_delta:+d}, "
            f"{self._rounds_no_reduction} round(s) without a reduction"
        )

    @property
    def best_score(self) -> float:
        return self._best_score

    def summary(self) -> dict:
        return {
            "attempts": len(self._history),
            "best_score": self._best_score,
            "rounds_since_improve": self._rounds_since_improve,
            "rounds_no_novelty": self._rounds_no_novelty,
        }


if __name__ == "__main__":
    # demo: a model that plateaus then loops
    pt = ProgressTracker(plateau_patience=3, loop_patience=2)
    stream = [("a", -9), ("b", -7), ("c", -7), ("d", -7), ("d", -7), ("d", -7)]
    for dg, sc in stream:
        print(f"observe({dg}, {sc}) -> {pt.observe(dg, sc).value}")
    print("summary:", pt.summary())
