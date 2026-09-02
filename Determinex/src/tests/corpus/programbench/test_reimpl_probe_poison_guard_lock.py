"""Locks for the 2026-07-18 probe-poisoning anomaly guards.

Found live driving gron: propose_probes() asks a cheap model for "flags only, after
the program name" invocations, but the model echoed the program name anyway
("gron -u"). Probe.argv must exclude the program name, so the reference binary
treated 'gron' as a bogus positional filename and errored IDENTICALLY ("open gron:
no such file or directory") on every one of the 11 exploration probes. That argv-echo
bug is fixed at the source (determinex_observe.propose_probes strips leading non-flag
tokens -- see test_determinex_observe_propose_probes.py). These two locks cover the
separate, generalizable anomaly detectors added so the NEXT time something upstream
produces a poisoned probe pool (whatever the cause), it gets flagged loudly instead of
silently burning hours of escalated-model compute before a human notices by hand:

  1. _warn_if_probe_pool_poisoned -- catches it up front, before decompose spends a
     single station, by checking whether the model-proposed exploration probes'
     OBSERVED reference stderr is suspiciously identical across most of them.
  2. incremental_solve's in-loop consecutive-zero-score streak warning -- defense in
     depth inside the decompose loop itself, for any poisoning pattern the upfront
     check doesn't catch.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_ROOT / "scripts"))

import determinex_observe as OBS  # noqa: E402
import determinex_pb_reimpl as reimpl  # noqa: E402
from determinex_router import ModelEntry  # noqa: E402


def _obs(name, argv, stdout="", stderr="", rc=0):
    return OBS.Observation(OBS.Probe(name, list(argv), None, {}, {}), stdout, stderr, rc)


# ------------------------------------------------------- _warn_if_probe_pool_poisoned


def test_poisoned_pool_triggers_warning(capsys):
    proposed = [OBS.Probe(f"explore_{i}", [f"-{i}"]) for i in range(8)]
    observations = [
        _obs(f"explore_{i}", [f"-{i}"], "", "open gron: no such file or directory\n", 1)
        for i in range(8)
    ]
    triggered = reimpl._warn_if_probe_pool_poisoned(proposed, observations)
    assert triggered is True
    assert "SUSPECT PROBE POOL" in capsys.readouterr().out


def test_healthy_diverse_pool_does_not_trigger(capsys):
    proposed = [OBS.Probe(f"explore_{i}", [f"-{i}"]) for i in range(8)]
    observations = [_obs(f"explore_{i}", [f"-{i}"], f"output-{i}\n", "", 0) for i in range(8)]
    triggered = reimpl._warn_if_probe_pool_poisoned(proposed, observations)
    assert triggered is False
    assert "SUSPECT" not in capsys.readouterr().out


def test_small_pool_below_threshold_is_skipped(capsys):
    proposed = [OBS.Probe(f"explore_{i}", [f"-{i}"]) for i in range(3)]
    observations = [_obs(f"explore_{i}", [f"-{i}"], "", "same error\n", 1) for i in range(3)]
    triggered = reimpl._warn_if_probe_pool_poisoned(proposed, observations)
    assert triggered is False  # too few probes to distinguish signal from coincidence


def test_a_few_legitimately_shared_errors_do_not_trigger(capsys):
    # 3 of 10 probes hitting the same real "unknown flag" rejection is plausible and
    # should NOT be flagged as poisoning -- only a dominant majority should.
    proposed = [OBS.Probe(f"explore_{i}", [f"-{i}"]) for i in range(10)]
    observations = [_obs(f"explore_{i}", [f"-{i}"], "", "unknown flag\n", 2) for i in range(3)] + [
        _obs(f"explore_{i}", [f"-{i}"], f"ok-{i}\n", "", 0) for i in range(3, 10)
    ]
    triggered = reimpl._warn_if_probe_pool_poisoned(proposed, observations)
    assert triggered is False


# --------------------------------------------- incremental_solve consecutive-zero streak


def test_consecutive_zero_streak_warns_at_threshold(capsys, monkeypatch):
    monkeypatch.setenv("DETERMINEX_VS_HEARTBEAT", "0")
    monkeypatch.setattr(reimpl, "_LANG", "c")
    # 5 distinct behaviors, all identically unreachable by every candidate -> 5
    # consecutive unsolved, score-0.00 stations (the exact live pattern).
    obs = [
        _obs(f"p{i}", [f"-{i}"], "", "open gron: no such file or directory\n", 1) for i in range(5)
    ]

    def runner(code, probe):
        return "", "", 1  # nothing the model tries ever matches

    ladder = [ModelEntry("stuck", tier=1, cost=0.0, generate=lambda p, t: "junk")]
    reimpl.incremental_solve(
        obs, ladder=ladder, helptext="", short="t", k=1, rounds=1, runner=runner
    )
    out = capsys.readouterr().out
    assert "5 CONSECUTIVE stations scored 0.00" in out


def test_streak_resets_on_a_solved_station(capsys, monkeypatch):
    monkeypatch.setenv("DETERMINEX_VS_HEARTBEAT", "0")
    monkeypatch.setattr(reimpl, "_LANG", "c")
    # incremental_solve sorts observations by (len(stdout), name) -- keep every stdout
    # the SAME byte-length so processing order is purely alphabetical and predictable:
    # a, b, e (solved), f, g. 4 zero-score stations total, but never more than 2 in a
    # row -- if the streak counter is (incorrectly) cumulative instead of consecutive,
    # 4 would still be below the threshold of 5, so this alone wouldn't distinguish a
    # broken reset from a correct one. What it DOES prove: the solved station's own
    # printed line is reachable at all (station "e" appears, not swallowed by reorder).
    obs = [
        _obs("a", ["-a"], "", "same1\n", 1),
        _obs("b", ["-b"], "", "same2\n", 1),
        _obs("e", ["-e"], "", "GOOD1\n", 0),  # solved -> must reset the streak
        _obs("f", ["-f"], "", "same4\n", 1),
        _obs("g", ["-g"], "", "same5\n", 1),
    ]

    def runner(code, probe):
        if probe.argv[0] == "-e" and "SOLVE_E" in code:
            return "", "GOOD1\n", 0
        return "", "", 1

    ladder = [ModelEntry("mixed", tier=1, cost=0.0, generate=lambda p, t: "SOLVE_E")]
    reimpl.incremental_solve(
        obs, ladder=ladder, helptext="", short="t", k=1, rounds=1, runner=runner
    )
    out = capsys.readouterr().out
    assert "+e:" in out and "UNSOLVED" not in out.split("+e:")[1].split("\n")[0]
    assert "CONSECUTIVE" not in out  # streak never reached the threshold


def test_streak_does_not_reset_and_warns_when_nothing_ever_solves(capsys, monkeypatch):
    monkeypatch.setenv("DETERMINEX_VS_HEARTBEAT", "0")
    monkeypatch.setattr(reimpl, "_LANG", "c")
    # same shape as above but NOTHING solves -> a genuine 5-in-a-row must still warn,
    # proving the guard isn't just permanently disabled.
    obs = [_obs(n, [f"-{n}"], "", "same err\n", 1) for n in "abcde"]

    def runner(code, probe):
        return "", "", 1

    ladder = [ModelEntry("stuck", tier=1, cost=0.0, generate=lambda p, t: "junk")]
    reimpl.incremental_solve(
        obs, ladder=ladder, helptext="", short="t", k=1, rounds=1, runner=runner
    )
    out = capsys.readouterr().out
    assert "5 CONSECUTIVE stations scored 0.00" in out
