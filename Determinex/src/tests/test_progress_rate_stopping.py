"""The stopping rule is the RATE of error removal, not a round count.

Ryan, 2026-08-03: *"we shouldn't be limited to three runs — take the delta from the previous
run, how many errors to the next run and what that reduction is... if the number to fix is
percentage too high, it stops and we figure out what to do (download toolchains, get backup,
support), or we go until that number stops."*

A fixed cap is wrong in both directions and both were reachable: a run steadily removing
failures gets cut off mid-descent because it hit round 3, and a run removing nothing still
burns its whole allowance. Every test here pins one half of the replacement.

The distinction that carries the most weight is OUT_OF_PROPORTION vs ESCALATE. They are not
severities of the same thing:

    ESCALATE            the loop is STUCK — no reduction, or no novelty.
    OUT_OF_PROPORTION   the loop is WORKING and still will not finish.

They have different remedies (a different strategy vs. a toolchain, a bigger model, a human),
so collapsing them into "gave up" would throw away the only part a caller can act on.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from determinex_progress import Directive, ProgressTracker  # noqa: E402


def _run(series: list[int], **kw) -> tuple[Directive, ProgressTracker]:
    pt = ProgressTracker(**kw)
    d = Directive.CONTINUE
    for e in series:
        d = pt.round_errors(e)
        if d != Directive.CONTINUE:
            break
    return d, pt


# ── "we go until that number stops" ─────────────────────────────────────────────────────


def test_a_steady_descent_is_never_cut_off_by_a_round_count():
    """Seven rounds of real progress. The old cap of 2-3 stopped this at 24 failures left."""
    d, pt = _run([40, 32, 24, 16, 8, 4, 1])
    assert d == Directive.CONTINUE
    assert len(pt._round_errors) == 7, "the descent was interrupted"


def test_it_keeps_going_well_past_any_fixed_cap_while_progress_holds():
    d, pt = _run(list(range(200, 0, -10)))  # 20 rounds, -10 each
    assert d == Directive.CONTINUE
    assert len(pt._round_errors) == 20


def test_the_absolute_cap_still_bounds_a_pathological_run():
    """Unbounded means "not bounded by a guess", not "not bounded".

    The series has to keep the PROPORTION healthy or the projection fires first and this
    tests the wrong rule -- which is what the first version of it did: 10,000 failures
    falling by 1 a round is out of proportion long before any cap, and correctly so.
    """
    d, pt = _run([100 - 10 * i for i in range(9)], absolute_max_rounds=4)
    assert d == Directive.ESCALATE
    assert len(pt._round_errors) == 4


# ── "if the number to fix is percentage too high, it stops" ─────────────────────────────


def test_one_error_per_round_with_forty_to_go_stops_and_says_so():
    d, pt = _run([42, 41, 40, 39, 38])
    assert d == Directive.OUT_OF_PROPORTION
    assert "40 more rounds" in pt.reason() or "more rounds" in pt.reason()


def test_out_of_proportion_is_not_escalate():
    """Different diagnosis, different remedy. A caller that cannot tell them apart cannot act."""
    slow, _ = _run([42, 41, 40, 39, 38])
    stuck, _ = _run([15, 15, 15, 15])
    assert slow == Directive.OUT_OF_PROPORTION
    assert stuck == Directive.ESCALATE
    assert slow != stuck


def test_a_generous_but_finite_descent_is_allowed_to_continue():
    """The rule must not punish slow-and-finite, only slow-and-hopeless."""
    d, _ = _run([12, 10, 8, 6, 4, 2])
    assert d == Directive.CONTINUE


def test_the_projection_is_not_fired_before_there_is_a_trend():
    """One unlucky first round must not abort a run that was about to work."""
    pt = ProgressTracker()
    assert pt.round_errors(30) == Directive.CONTINUE
    assert pt.round_errors(30) == Directive.CONTINUE  # no reduction yet, still too early


# ── "or we go until that number stops" ──────────────────────────────────────────────────


def test_two_rounds_without_a_reduction_is_a_plateau():
    d, pt = _run([20, 12, 8, 8, 8])
    assert d == Directive.ESCALATE
    assert pt._rounds_no_reduction >= 2


def test_a_single_flat_round_is_noise_not_a_plateau():
    d, _ = _run([20, 12, 12, 6])
    assert d == Directive.CONTINUE


def test_solving_it_does_not_trip_any_stop():
    d, _ = _run([9, 4, 0])
    assert d == Directive.CONTINUE, "zero failures is the caller's business, not a stop reason"


# ── the reason has to carry numbers ─────────────────────────────────────────────────────


def test_the_reason_names_the_numbers_a_caller_needs():
    _, pt = _run([42, 41, 40, 39, 38])
    r = pt.reason()
    assert "42" in r and "40" in r, f"reason does not state the counts: {r}"
    assert "/round" in r, f"reason does not state the rate: {r}"


def test_the_reason_is_honest_when_nothing_was_removed():
    _, pt = _run([15, 15, 15, 15])
    assert "never" in pt.reason()


def test_reason_is_safe_before_any_round():
    assert ProgressTracker().reason() == "no rounds observed"


# ── the candidate-level detector is untouched ───────────────────────────────────────────


def test_round_rate_and_candidate_observe_stay_separate():
    """`observe` scores CANDIDATES, `round_errors` scores ROUNDS. Merging them would make
    "no improvement" mean two different things at two different granularities."""
    pt = ProgressTracker()
    assert pt.observe(digest="a", score=-9) == Directive.CONTINUE
    assert pt.round_errors(9) == Directive.CONTINUE
    assert pt._history and pt._round_errors
    assert len(pt._history) == 1 and len(pt._round_errors) == 1


def test_zero_failures_without_a_pass_is_no_signal_not_success():
    """`round_errors` is only reached on a round that did NOT solve.

    So zero failures here means the oracle reported nothing -- a broken verifier, an empty
    failure list -- and an earlier version treated it as "solved, stop for a better reason".
    The loop then ran its full 40-round safety cap on a run producing nothing at all, which an
    end-to-end drive caught: 40 rounds of "0 -> 0 failing checks" that should have been 3.
    """
    d, pt = _run([0, 0, 0, 0])
    assert d == Directive.ESCALATE
    assert len(pt._round_errors) == 3, "a no-signal run must stop at the plateau, not the cap"
    assert "never" in pt.reason()
