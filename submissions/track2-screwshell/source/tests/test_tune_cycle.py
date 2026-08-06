"""Unit tests for the autotune cycle state machine (tune-loop plan, Todo 5).

No GPU / llama / relay. We inject a duck-typed lifecycle, a scriptable scorer,
a simple planner, and no-op benchmark/event callables. Fast clock + no sleeping.
"""
from __future__ import annotations

import importlib.util, sys, types, os, json, time

sys.path.insert(0, r'D:\AI\git\screwshell')

# fast clock so restart throttling doesn't sleep
class _Clock:
    def __init__(self): self.t = 0.0
    def __call__(self): self.t += 1000.0; return self.t

import screwshell.autotune.cycle as C
C.time.time = _Clock()
C.time.sleep = lambda s=0: None

from screwshell.autotune.cycle import TuneCycle, IDLE, DONE, ABORT, ROLLBACK, KEEP
from screwshell.autotune.mapper import TuneGoal


class FakeLifecycle:
    """Scriptable lifecycle. side_effects: list of (ok,) responses, consumed in order."""
    def __init__(self, side_effects=None):
        self.side_effects = list(side_effects or [True])
        self.starts = []          # argv passed to start_argv
        self.takeovers = []
        self._i = 0

    def start_argv(self, argv, takeover=False):
        self.starts.append(list(argv))
        self.takeovers.append(takeover)
        ok = self.side_effects[self._i] if self._i < len(self.side_effects) else True
        self._i += 1
        return (ok, 1.0)

    def health_ok(self):
        return True


def _planner(preset, spec, param):
    # simple deterministic: nudge n_batch up for every param (always a real goal)
    if param == "n-batch":
        return TuneGoal(param="n_batch", target=int(spec.get("n_batch", 256)) * 2,
                        reason="test")
    return TuneGoal(param="n_batch", target=512, reason="test")


def _builder(spec):
    base = ["llama-server", "--model", "/m", "--jinja", "--reasoning-budget", "4096"]
    if "n_batch" in spec:
        base += ["--batch-size", str(spec["n_batch"])]
    return base


def _make_cycle(lc, scorer, tmp_path, planner=_planner):
    state = str(tmp_path / "tune_state.json")
    return TuneCycle(lifecycle=lc, scorer=scorer, planner=planner,
                     benchmark_generator=lambda n: None,
                     event_collector=lambda: [{"ttft_ms": 500, "decode_tps": 30,
                                               "kv_hit_rate": 0.9, "ok": True}] * 20,
                     state_path=state)


def test_success_run_keeps_improved(tmp_path):
    lc = FakeLifecycle([True])
    scores = [0.5, 0.8]            # second score improves -> keep
    def scorer(events):
        return scores.pop(0) if scores else 0.9
    cyc = _make_cycle(lc, scorer, tmp_path)
    status = cyc.run("speed", {"n_batch": 256}, _builder)
    assert status == DONE
    # last_good_argv reflects the improved (kept) config
    assert "--batch-size" in cyc.last_good_argv


def test_restart_failure_rolls_back(tmp_path):
    # first start (new config) fails -> rollback to last_good (original) succeeds
    lc = FakeLifecycle([False, True])
    cyc = _make_cycle(lc, lambda e: 0.9, tmp_path)
    status = cyc.run("speed", {"n_batch": 256}, _builder)
    # rolled back; cycle continues/skips; ends DONE (keep current = last_good)
    assert status == DONE
    # rollback re-applied the original argv (takeover + original present)
    assert any("--batch-size" in a for a in lc.starts)


def test_rollback_failure_escalates_to_abort_server_down(tmp_path):
    # new fails, rollback (last_good) also fails, original also fails -> ABORT+down
    lc = FakeLifecycle([False, False, False])
    cyc = _make_cycle(lc, lambda e: 0.9, tmp_path)
    status = cyc.run("speed", {"n_batch": 256}, _builder)
    assert status == ABORT
    assert cyc.server_may_be_down is True


def test_converge_after_two_no_improve(tmp_path):
    # constant 0.8 score: after 2 consecutive no-improve rounds (|new-old|<5%)
    # the cycle declares convergence -> DONE.
    lc = FakeLifecycle([True] * 8)
    cyc = _make_cycle(lc, lambda e: 0.8, tmp_path)
    status = cyc.run("speed", {"n_batch": 256}, _builder)
    assert status == DONE


def test_stop_requested_ends_done(tmp_path):
    lc = FakeLifecycle([True])
    cyc = _make_cycle(lc, lambda e: 0.9, tmp_path)
    cyc.stop()
    status = cyc.run("speed", {"n_batch": 256}, _builder)
    assert status == DONE


def test_iron_rule_violation_aborts(tmp_path):
    def bad_builder(spec):
        return ["llama-server", "--model", "/m", "--reasoning-budget", "-1"]  # no --jinja, -1
    lc = FakeLifecycle([True])
    cyc = _make_cycle(lc, lambda e: 0.9, tmp_path)
    status = cyc.run("speed", {"n_batch": 256}, bad_builder)
    assert status == ABORT


def test_state_file_persisted(tmp_path):
    lc = FakeLifecycle([True])
    cyc = _make_cycle(lc, lambda e: 0.9, tmp_path)
    cyc.run("speed", {"n_batch": 256}, _builder)
    data = json.loads((tmp_path / "tune_state.json").read_text(encoding="utf-8"))
    assert "status" in data and "last_good_argv" in data
    assert "original_argv" in data and "history" in data
    assert "server_may_be_down" in data


def test_benchmark_generator_called_with_min_n(tmp_path):
    called = {}
    lc = FakeLifecycle([True])
    cyc = TuneCycle(lifecycle=lc, scorer=lambda e: 0.9, planner=_planner,
                    benchmark_generator=lambda n: called.setdefault("n", n),
                    event_collector=lambda: [{"ttft_ms": 500, "decode_tps": 30,
                                              "kv_hit_rate": 0.9, "ok": True}] * 20,
                    state_path=str(tmp_path / "tune_state.json"))
    cyc.run("speed", {"n_batch": 256}, _builder)
    assert called.get("n") == C.MIN_N
