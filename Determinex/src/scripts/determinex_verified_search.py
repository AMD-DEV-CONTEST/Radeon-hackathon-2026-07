#!/usr/bin/env python3
"""
determinex_verified_search.py -- The Correctness Amplifier (keystone)
==================================================================
"...any LLM, regardless of how good or large or small, can access this system
and work anything, and it be right."

This is the layer that makes that literally true. The Oracle + Adjudicator +
Validator make a STRONG model honest. This makes a WEAK model CORRECT.

The mechanism is not magic, it is arithmetic. A model's per-attempt success on a
step is some probability p. If the answer can be VERIFIED deterministically (and
it can -- that is the Compiler/Universal Oracle), then sampling K diverse
candidates and keeping the one that passes gives system success:

        P(solve) = 1 - (1 - p)^K

    p=0.10, K=30  -> 0.958      p=0.20, K=15 -> 0.965      p=0.05, K=60 -> 0.954

So ANY model with p > 0 is converted toward correctness by verified search. Make
each step small enough (the Decomposer) that p is workable, sample against the
oracle, keep what passes. That is how a 1.5B model -- or a model you have never
heard of -- "works anything and is right."

THE SOUNDNESS CONTRACT (load-bearing): this only yields *correct* output if the
oracle is *sound*. A wrong test makes verified search converge confidently to a
wrong answer. Therefore every oracle passed in here SHOULD be paired with the
Test Validator -- garbage oracle in, confident garbage out. This module refuses
to claim "solved" without a passing OracleResult, and records the proof.

Model-agnostic by construction
------------------------------
The model is just a callable `generate(prompt: str, temperature: float) -> str`.
Local 1.5B, cloud frontier, cloaked, an ensemble -- all plug in identically.
The oracle is just `verify(candidate: str) -> OracleResult`. Nothing here knows
or cares which model produced the candidate. That IS the "any LLM can access
this system" interface.

    from determinex_verified_search import VerifiedSearch
    vs = VerifiedSearch(verify=my_oracle, k=8, rounds=3)
    result = vs.solve(generate=my_model, prompt=task_prompt)
    if result.solved:
        apply(result.best.text)        # carries a passing-oracle proof
"""

from __future__ import annotations

import hashlib
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
from determinex_adjudicator import Failure, Verdict, classify_failure  # noqa: E402


# ---------------------------------------------------------------------------
# Minimal oracle contract (matches determinex_oracle.OracleResult duck-style)
# ---------------------------------------------------------------------------
class OracleLike(Protocol):
    passed: bool
    failures: list


# A verify fn takes a candidate string and returns something with .passed + .failures
VerifyFn = Callable[[str], OracleLike]
# A model takes (prompt, temperature) and returns a candidate string
GenerateFn = Callable[[str, float], str]


@dataclass
class Candidate:
    text: str
    passed: bool
    n_failures: int
    temperature: float
    digest: str = ""
    score: float = 0.0  # closeness gradient (e.g. fraction of expected output reproduced)


@dataclass
class SearchResult:
    solved: bool
    best: Candidate | None
    rounds_used: int
    total_samples: int
    proof: str  # why we believe it is correct (oracle pass)
    escalated: bool = False
    next_moves: list[str] = field(default_factory=list)  # if not solved, the Adjudicator's advice
    history: list[Candidate] = field(default_factory=list)
    #: Samples where the GENERATOR raised instead of returning a candidate. Counted separately
    #: because "the model answered and was wrong" and "the model never answered" are different
    #: facts, and only the first is evidence about the model. See `generator_never_answered`.
    generation_errors: int = 0
    #: The first generator exception, verbatim, so a misconfiguration is diagnosable from the
    #: result alone rather than needing the run repeated with logging turned up.
    generation_error_sample: str = ""

    @property
    def generator_never_answered(self) -> bool:
        """Every sample failed to generate, so this result says nothing about the model.

        Load-bearing distinction. A provider that raises on every call used to produce
        `solved=False` with a proof reading "no program passed the N checks (12 samples)" --
        which is indistinguishable from a model that genuinely attempted twelve times. Measured
        2026-07-31: `--provider local --model <bare ollama tag>` raised BadRequestError on every
        call, and the run reported not-solved plus an Adjudicator next-move premised on failures
        the model never produced. A caller that treats this as a capability verdict is wrong.
        """
        return self.total_samples > 0 and self.generation_errors >= self.total_samples


# default temperature ladder: start deterministic, widen for diversity
from determinex_progress import Directive, ProgressTracker  # noqa: E402

_DEFAULT_TEMPS = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]


def _sampler_is_degenerate(generate, probes: int = 3) -> bool:
    """Does this generator actually honour `temperature`?

    Called only when a run has already produced identical candidates across several
    temperatures, to separate the two causes of that symptom:

      * the PROVIDER ignores temperature -- OpenRouter's free tier returns byte-identical
        text at t=0.0/0.5/1.0 (measured 2026-07-31), so best-of-K silently becomes K=1;
      * the MODEL is confident on a tightly-constrained prompt -- a SEARCH/REPLACE edit
        format converges hard, and 6 draws collapsing to 1 distinct answer is normal.

    The probe must be HIGH-ENTROPY or it measures nothing. Measured on a working 32B at
    t=0.1/0.55/1.0: "Name one colour" returned 1 distinct answer (the model is confident, the
    sampler is fine) while "Write one original sentence about the sea" returned 3. A
    low-entropy probe would therefore have condemned a healthy provider.

    Failure to probe returns False: never accuse a provider on the strength of a call that
    did not happen.
    """
    seen: set[str] = set()
    for i in range(probes):
        try:
            seen.add(
                _digest(generate("Write one original sentence about the sea.", 0.1 + 0.45 * i))
            )
        except Exception:
            return False
    return len(seen) <= 1


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:16]


class VerifiedSearch:
    """Convert any generator + sound oracle into a correct solver via best-of-K
    verified search with feedback rounds, diversity, loop-breaking, and an
    Adjudicator escalation that refuses to surrender without a reason."""

    def __init__(
        self,
        verify: VerifyFn,
        k: int = 8,
        rounds: int = 3,
        temps: list[float] | None = None,
        adjudicate: bool = True,
        early_escalate: bool = False,
    ):
        self.verify = verify
        self.k = k
        self.rounds = rounds
        self.temps = temps or _DEFAULT_TEMPS
        self.adjudicate = adjudicate
        # EARLY ESCALATE (2026-07-02): when a whole round of k distinct samples scores
        # exactly 0.00, this tier has no traction on the leaf and feedback rounds cannot
        # rescue it (feedback refines a partial; there is no partial). Burn no more
        # rounds -- hand the leaf up the ladder now. Set by the ROUTER for every tier
        # that HAS a next tier; the top tier keeps its full round budget (observed:
        # 7b spent ~15 min exhausting its budget at 0.00 on a station 14b then solved
        # in 2 samples).
        self.early_escalate = early_escalate

    def _temp_for(self, i: int, hot: bool = False) -> float:
        """Temperature for sample `i`, skewed hot once the cold rungs are proven useless.

        MEASURED ON THE RADEON, 2026-08-03 (Qwen2.5-Coder-7B, 10 draws per rung, expression
        evaluator with 6 sound checks):

            t=0.0  p=0.00   1 distinct / 10      <- greedy: ten draws are one draw
            t=0.2  p=0.00   2 / 10
            t=0.4  p=0.00   6 / 10
            t=0.6  p=0.00   8 / 10
            t=0.8  p=0.10   6 / 10
            t=1.0  p=0.10  10 / 10

        Every draw at t<=0.6 had p=0.00, so a NOMINAL K of 8 was an EFFECTIVE K of 4 -- half
        the batch spent on rungs that could not pass. That is why `1-(1-p)^K` over-predicted
        (0.403 against 0.167 observed): the equation was right and the K was wrong.

        The remedy is not a different equation. After a round where NOTHING scored, the cold
        rungs have demonstrated -- on this task, not in general -- that they contribute
        nothing, so the next round spends its budget where the passes actually came from.
        Cold-first is still correct for the FIRST round: on an easy task the greedy sample
        solves it outright and sampling hot would be pure waste.
        """
        if not hot:
            return self.temps[i] if i < len(self.temps) else self.temps[-1]
        hot_rungs = [t for t in self.temps if t >= 0.6] or [self.temps[-1]]
        return hot_rungs[i % len(hot_rungs)]

    def solve(self, generate: GenerateFn, prompt: str) -> SearchResult:
        history: list[Candidate] = []
        seen: set[str] = set()
        temps_used: set[float] = set()  # to tell a degenerate sampler from a looping model
        feedback = ""
        best: Candidate | None = None
        total = 0
        gen_errors = 0
        first_gen_error = ""

        import os as _os
        import time as _time
        from concurrent.futures import ThreadPoolExecutor

        # HEARTBEAT (2026-07-02): a station/leaf can legitimately take 30-60+ min on a
        # CPU-bound local model, and with zero output in that window a healthy run is
        # indistinguishable from a hang (we burned hours on exactly that ambiguity).
        # One terse line per sample; DETERMINEX_VS_HEARTBEAT=0 silences it.
        heartbeat = _os.environ.get("DETERMINEX_VS_HEARTBEAT", "1") != "0"
        # CONCURRENCY CAP (2026-07-02): k-way fan-out is right for cloud APIs, but against
        # a single local ollama (1-4 parallel slots) the excess requests just sit in the
        # server queue burning their own timeout budget -- an observed queued call waited
        # 11.7 min then died as "timed out", wasting the sample. Cap in-flight generations
        # (DETERMINEX_VS_MAX_CONCURRENCY); default keeps the historical k-way behavior.
        max_conc = max(1, int(_os.environ.get("DETERMINEX_VS_MAX_CONCURRENCY", str(self.k))))

        # ROUNDS ARE NOT THE STOPPING RULE (2026-08-03). Ryan: "we shouldn't be limited to
        # three runs -- take the delta from the previous run... if the number to fix is
        # percentage too high, it stops and we figure out what to do, or we go until that
        # number stops." A fixed cap is wrong in both directions: it cuts off a run that is
        # steadily removing failures, and it lets a run that removes none burn its full
        # allowance. `self.rounds` is now a FLOOR -- the loop runs at least that many and then
        # keeps going while the failure count is genuinely falling, bounded by the tracker's
        # own projection and absolute cap rather than by a constant chosen in advance.
        # COST CEILING. `self.rounds` became a FLOOR, so a run that keeps making progress can
        # now go well past it -- which is the point, and also a bill. The tracker's absolute cap
        # bounds it at 40 rounds x K generations worst case; that is fine against a local model
        # and expensive against a metered API, so an operator can lower it without touching
        # code. Lowering this does NOT restore the old behaviour: the rate rule still stops a
        # stalled run early, this only bounds a run that never stalls.
        _max_rounds = max(
            self.rounds, int(_os.environ.get("DETERMINEX_VS_MAX_ROUNDS", "40") or 40)
        )
        rate = ProgressTracker(absolute_max_rounds=_max_rounds)
        # True once a whole round has scored nothing: from then on the batch is drawn from the
        # hot rungs only. Cold-first stays correct for round 1 -- on an easy task the greedy
        # sample solves it outright and sampling hot would be waste.
        _all_cold_failed = False
        stop_reason = ""
        r = -1
        while True:
            r += 1
            if r >= rate.absolute_max_rounds:
                stop_reason = f"safety cap: {rate.reason()}"
                break
            round_prompt = prompt if not feedback else f"{prompt}\n\n{feedback}"
            distinct_this_round = 0
            # The K samples are INDEPENDENT (same prompt, different temperature) -> generate them
            # CONCURRENTLY (bounded by max_conc, see above). Each generate() opens its own
            # connection (thread-safe).
            # After a round in which nothing scored at all, the cold rungs have proven -- on
            # THIS task -- that they cannot pass, so stop paying for them. See `_temp_for`:
            # measured on the Radeon, every draw at t<=0.6 had p=0.00 on a task the model
            # found hard, which is precisely why a nominal K of 8 behaved like a K of 4.
            temps = [self._temp_for(i, hot=_all_cold_failed) for i in range(self.k)]
            temps_used.update(temps)

            def _gen_one(temp, _p=round_prompt):
                t0 = _time.time()
                try:
                    out = generate(_p, temp)
                except Exception as e:  # a model error is not a solve -- nor an attempt
                    return temp, None, _time.time() - t0, f"{type(e).__name__}: {e}"
                return temp, out, _time.time() - t0, ""

            with ThreadPoolExecutor(max_workers=max_conc) as ex:
                batch = list(ex.map(lambda t: _gen_one(t), temps))

            for i, (temp, text, gen_s, gen_err) in enumerate(batch):
                total += 1
                # A generator that RAISED produced no candidate. It used to be turned into the
                # string "__generation_error__: ...", which was then digested, deduped, and handed
                # to the oracle as if it were code -- so a wholly broken provider yielded
                # `solved=False` with a proof reading "no program passed the N checks", and round 2
                # diagnosed "model is looping" because every error string hashed the same. That is
                # a capability verdict on a model that was never reached. Counted, never verified.
                if gen_err:
                    gen_errors += 1
                    if not first_gen_error:
                        first_gen_error = gen_err
                    if heartbeat:
                        print(
                            f"    [vs] r{r + 1} s{i + 1}/{self.k} t={temp:.1f} "
                            f"gen {gen_s:.0f}s -> GENERATION ERROR: {gen_err[:160]}",
                            flush=True,
                        )
                    continue
                assert text is not None  # gen_err empty => generate() returned
                dg = _digest(text)
                if dg in seen:
                    if heartbeat:
                        print(
                            f"    [vs] r{r + 1} s{i + 1}/{self.k} t={temp:.1f} "
                            f"gen {gen_s:.0f}s -> duplicate, skipped",
                            flush=True,
                        )
                    continue  # loop/duplicate -> skip, preserves diversity
                seen.add(dg)
                distinct_this_round += 1
                v0 = _time.time()
                res = self.verify(text)
                passed = bool(getattr(res, "passed", False))
                nfail = len(getattr(res, "failures", []) or [])
                cand = Candidate(
                    text=text,
                    passed=passed,
                    n_failures=nfail,
                    temperature=temp,
                    digest=dg,
                    score=float(getattr(res, "score", 0.0)),
                )
                history.append(cand)
                if heartbeat:
                    print(
                        f"    [vs] r{r + 1} s{i + 1}/{self.k} t={temp:.1f} "
                        f"gen {gen_s:.0f}s verify {_time.time() - v0:.0f}s -> "
                        f"{'PASS' if passed else f'{nfail} fail'} "
                        f"(score {cand.score:.2f})",
                        flush=True,
                    )
                if best is None or _better(cand, best):
                    best = cand
                if passed:
                    # SOLVED: only claim it because a sound oracle passed.
                    return SearchResult(
                        solved=True,
                        best=cand,
                        rounds_used=r + 1,
                        total_samples=total,
                        proof=f"oracle PASSED candidate {dg} (round {r + 1}, "
                        f"temp {temp}); 0 failures.",
                        history=history,
                        generation_errors=gen_errors,
                        generation_error_sample=first_gen_error,
                    )
            # --- round did not solve: build feedback from the best partial ---
            # DEGENERATE SAMPLER (2026-07-31): a provider that ignores `temperature` returns
            # byte-identical text at every temperature, so K draws dedup to ONE candidate and
            # verified search silently becomes K=1 -- while still reporting "N samples". The
            # whole architecture rests on drawing DISTINCT candidates, so this is not a model
            # verdict at all. Measured on OpenRouter's free tier: four draws at t=0.0/0.5/1.0/1.0
            # produced one distinct output (sha identical), and a k=8 x 2-round run yielded 15
            # "duplicate, skipped" out of 16.
            #
            # This is the THIRD time this file has had to separate a provider fault from a model
            # behaviour (see the generation-error note above, and the bare-Ollama-tag note in
            # tests/test_generation_failure_is_not_a_verdict.py). Same lesson each time: "the
            # model is looping" is a diagnosis, and diagnoses must be earned.
            # CONFIRM BEFORE ACCUSING (2026-08-01): identical output across temperatures has
            # TWO causes -- a provider that ignores `temperature`, or a model that is simply
            # confident on a tightly-constrained prompt (a SEARCH/REPLACE edit format
            # converges hard; observed 6 draws -> 1 distinct on a working sampler). Blaming
            # the provider for the second is the same mistake as blaming the model for the
            # first. So probe the sampler directly with a throwaway prompt whose answer is
            # free to vary: if THAT varies, sampling works and this is about the task.
            if (
                len(seen) <= 1
                and total >= 4
                and len({round(t, 3) for t in temps_used}) >= 2
                and _sampler_is_degenerate(generate)
            ):
                return self._escalate(
                    best,
                    history,
                    total,
                    r + 1,
                    f"SAMPLER IGNORED TEMPERATURE: {total} draws across "
                    f"{len({round(t, 3) for t in temps_used})} distinct temperatures produced "
                    f"{len(seen)} distinct candidate(s). Verified search is degenerate at K=1 on "
                    f"this provider -- best-of-K cannot work until sampling varies. This is a "
                    f"provider/config fault, NOT a model capability verdict.",
                    gen_errors=gen_errors,
                    first_gen_error=first_gen_error,
                )
            if distinct_this_round == 0:
                # Distinguish "the model repeats itself" from "the model was never reached".
                # Both produced zero distinct candidates, and the old code called both looping --
                # so a BadRequestError from a misconfigured provider was diagnosed as a model
                # behaviour, which sends the reader looking in the wrong place entirely.
                if gen_errors and not history:
                    return self._escalate(
                        best,
                        history,
                        total,
                        r + 1,
                        f"the generator raised on every sample and produced no candidate "
                        f"({gen_errors}/{total}); first error: {first_gen_error[:300]}",
                        gen_errors=gen_errors,
                        first_gen_error=first_gen_error,
                    )
                return self._escalate(
                    best,
                    history,
                    total,
                    r + 1,
                    "no distinct candidates (model is looping)",
                    gen_errors=gen_errors,
                    first_gen_error=first_gen_error,
                )
            if self.early_escalate and best is not None and best.score <= 0.0:
                # zero-signal round: no candidate scored above 0.00 -> this tier can't
                # see the target at all; more rounds of the same model are waste.
                if heartbeat:
                    print(
                        f"    [vs] r{r + 1}: zero-signal round (best score 0.00) -> "
                        f"early escalate to next tier",
                        flush=True,
                    )
                return self._escalate(
                    best,
                    history,
                    total,
                    r + 1,
                    "zero-signal round at this tier (early escalate)",
                    gen_errors=gen_errors,
                    first_gen_error=first_gen_error,
                )
            if best is not None and best.score <= 0.0 and not best.passed:
                _all_cold_failed = True

            feedback = self._feedback_from(best)

            # THE RATE, measured on this round's best. `self.rounds` is a floor: below it the
            # loop always continues, because two or three rounds is not enough of a trend to
            # project from and an unlucky first round would abort a run that was about to work.
            round_errors = best.n_failures if best is not None else -1
            if round_errors >= 0:
                directive = rate.round_errors(round_errors)
                if r + 1 >= self.rounds and directive != Directive.CONTINUE:
                    stop_reason = (
                        # OUT_OF_PROPORTION is not "stuck" -- the loop is working and will not
                        # finish, which is a different message and a different remedy: fetch a
                        # toolchain, a bigger model, or a person. Naming which is the point.
                        f"the loop is making progress but not enough of it -- {rate.reason()}. "
                        f"Continuing will not close this; something outside the loop has to "
                        f"change (missing toolchain, a stronger model, or a human)."
                        if directive == Directive.OUT_OF_PROPORTION
                        else f"progress stopped -- {rate.reason()}"
                    )
                    break
        return self._escalate(
            best,
            history,
            total,
            r + 1,
            stop_reason or "rounds exhausted",
            gen_errors=gen_errors,
            first_gen_error=first_gen_error,
        )

    def _feedback_from(self, best: Candidate | None) -> str:
        if best is None:
            return "Previous attempts produced no usable candidate. Try a different approach."
        res = self.verify(best.text)
        fails = getattr(res, "failures", []) or []
        lines = [
            "The previous best attempt FAILED these checks. Fix EACH — your output must "
            "match EXPECTED exactly (bytes + exit code):"
        ]
        # Budget: carry enough of each failure (incl. the EXPECTED output) to be actionable.
        # 160 chars was sized for compiler errors; reimplementation diffs need the full
        # expected output (hundreds of bytes). Cap per-failure and total to stay sane.
        per, shown, budget = 1100, 0, 9000
        for f in fails[:10]:
            name = getattr(f, "name", "") or getattr(f, "test_id", "?")
            txt = (getattr(f, "text", "") or "")[:per]
            block = f"- {name}:\n{txt}"
            if shown + len(block) > budget:
                break
            lines.append(block)
            shown += len(block)
        return "\n".join(lines)

    def _escalate(
        self,
        best: Candidate | None,
        history: list[Candidate],
        total: int,
        rounds: int,
        reason: str,
        gen_errors: int = 0,
        first_gen_error: str = "",
    ) -> SearchResult:
        # Run the Adjudicator over the best candidate's failures: we are only
        # allowed to "give up" if the failures are genuinely IMPOSSIBLE; otherwise
        # we report the untried moves so the orchestration can re-decompose/route.
        next_moves: list[str] = []
        all_impossible = False
        if best is not None and self.adjudicate:
            res = self.verify(best.text)
            fails = getattr(res, "failures", []) or []
            verdicts = []
            for f in fails:
                ff = (
                    f
                    if isinstance(f, Failure)
                    else Failure(
                        test_id=getattr(f, "test_id", "?"),
                        name=getattr(f, "name", "?"),
                        text=getattr(f, "text", "") or "",
                    )
                )
                a = classify_failure(ff)
                verdicts.append(a.verdict)
                if a.verdict != Verdict.IMPOSSIBLE:
                    next_moves.append(a.strategy)
            all_impossible = bool(verdicts) and all(v == Verdict.IMPOSSIBLE for v in verdicts)
        # When the generator never answered, the proof must say THAT and nothing about the
        # model's ability. "REOPENABLE via ['behavioral:semantic']" is advice derived from
        # failures, and there are no failures to derive it from -- offering it invites the reader
        # to tune a prompt when the actual fix is a provider setting. Neither is it a "ceiling".
        if total > 0 and gen_errors >= total:
            return SearchResult(
                solved=False,
                best=None,
                rounds_used=rounds,
                total_samples=total,
                proof=(
                    f"NOT ATTEMPTED: the generator raised on all {total} sample(s), so no "
                    f"candidate was ever produced and this result says nothing about the "
                    f"model. First error: {first_gen_error[:400]}"
                ),
                escalated=True,
                next_moves=["fix:generator"],
                history=history,
                generation_errors=gen_errors,
                generation_error_sample=first_gen_error,
            )
        partial = (
            f" NOTE: {gen_errors}/{total} sample(s) failed to generate at all "
            f"({first_gen_error[:200]}), so the effective sample count was lower than "
            f"requested."
            if gen_errors
            else ""
        )
        return SearchResult(
            solved=False,
            best=best,
            rounds_used=rounds,
            total_samples=total,
            proof=f"not solved ({reason}); "
            + (
                "all failures IMPOSSIBLE -> genuine ceiling, human review."
                if all_impossible
                else f"REOPENABLE via {sorted(set(next_moves))} -- re-decompose, "
                f"route to a stronger model, or raise K."
            )
            + partial,
            escalated=True,
            next_moves=sorted(set(next_moves)),
            history=history,
            generation_errors=gen_errors,
            generation_error_sample=first_gen_error,
        )


def _better(a: Candidate, b: Candidate) -> bool:
    if a.passed != b.passed:
        return a.passed
    # Prefer the candidate that reproduced MORE of the expected behavior (closeness
    # gradient). Without this, byte-exact pass/fail gives no "getting warmer" signal and
    # the search can stall on a do-nothing candidate that only matches empty/error cases.
    if abs(a.score - b.score) > 1e-9:
        return a.score > b.score
    return a.n_failures < b.n_failures  # tiebreak: fewer failing checks


def expected_solve_probability(p: float, k: int) -> float:
    """The arithmetic that justifies the whole module: P(solve) = 1-(1-p)^K."""
    return 1.0 - (1.0 - p) ** k


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Verified Search -- correctness math")
    ap.add_argument("--p", type=float, default=0.1, help="model per-attempt success")
    ap.add_argument("--k", type=int, default=30, help="candidates per step")
    args = ap.parse_args()
    print(
        f"A model with per-attempt p={args.p} sampled K={args.k} against a sound "
        f"oracle:\n  P(solve) = 1-(1-{args.p})^{args.k} = "
        f"{expected_solve_probability(args.p, args.k):.4f}"
    )
    print(
        "\nThis is why ANY model with p>0 is converted toward correct by verified "
        "search.\nDecompose until p is workable; sample against the oracle; keep "
        "what passes."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
