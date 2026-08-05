"""Per-rig K calibration: the objective must reproduce known hardware, and never guess.

K is the correctness knob (`P = 1 - (1 - p)^K`), so a wrong K is not a slow run -- it is a
run that accrues correctness at the wrong rate, or one that falls off a throughput cliff the
hardware already knew about. These tests pin three things:

  1. the objective picks the knee that was found BY HAND on real AMD Radeon data
  2. it detects the collapse, and does not mistake "still climbing" for a collapse
  3. an uncalibrated rig gets a conservative K *and says so*, never a silent guess
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from determinex_calibrate import (  # noqa: E402
    UNCALIBRATED_K,
    Calibration,
    KPoint,
    host_fingerprint,
    optimal_k,
    pick_optimal,
    sweep,
)

# Captured verbatim from amd_gpu_evidence/k_sweep_and_prefix_cache.json -- a real sweep on
# AMD Radeon Cloud, ROCm 7.2.1, vLLM 0.16.1, Qwen2.5-Coder-7B-Instruct.
RADEON = [(1, 8.922, 28.7), (8, 9.297, 220.3), (16, 9.906, 413.5), (24, 10.375, 592.2),
          (32, 10.75, 739.9), (48, 13.625, 849.7), (64, 29.594, 512.6)]

# Measured on a consumer box, Ollama + Qwen2.5-Coder-1.5B, warm, 2026-08-02.
CONSUMER = [(1, 2.725, 17.6), (2, 3.083, 27.6), (4, 3.978, 45.5),
            (6, 5.033, 55.0), (8, 5.706, 61.5), (12, 7.359, 69.4)]


def _points(rows):
    return [KPoint(k, w, int(t * w), t, round(k / w, 3)) for k, w, t in rows]


def test_objective_reproduces_the_radeon_knee_found_by_hand():
    """The whole design rests on this: candidates/second must find the same knee a human
    found by staring at the sweep. If it does not, the metric is wrong."""
    best, collapsed = pick_optimal(_points(RADEON))
    assert best == 48, f"expected the hand-found knee K=48, got {best}"
    assert collapsed == 64, f"expected the measured collapse at K=64, got {collapsed}"


def test_collapse_is_detected_not_inferred():
    """K=64 collapsed because it exceeded the server's declared 61.83x concurrency. The
    detector must find it from the numbers, without being told the declared limit."""
    pts = _points(RADEON)
    _, collapsed = pick_optimal(pts)
    at = next(p for p in pts if p.k == collapsed)
    peak = max(p.cand_per_s for p in pts)
    assert at.cand_per_s < peak, "a 'collapse' must be slower than the peak, or it is not one"


def test_still_climbing_is_not_reported_as_a_collapse():
    """NEGATIVE CONTROL. The consumer box never collapsed within K<=12. Reporting a phantom
    collapse would cap every rig at whatever K the sweep happened to stop at."""
    best, collapsed = pick_optimal(_points(CONSUMER))
    assert collapsed is None, f"no collapse was measured, but one was reported at K={collapsed}"
    assert best == 12, f"expected the top of the swept range, got {best}"


def test_the_two_machines_disagree_which_is_the_entire_point():
    """One constant cannot serve both. If these ever agree, the fixture is wrong."""
    radeon_k, _ = pick_optimal(_points(RADEON))
    consumer_k, _ = pick_optimal(_points(CONSUMER))
    assert radeon_k != consumer_k
    assert radeon_k > consumer_k, "the datacentre GPU should sustain more concurrency"


def test_uncalibrated_rig_is_told_it_is_uncalibrated(tmp_path, monkeypatch):
    """Never a silent guess -- the same doctrine determinex_oracle enforces for a missing
    oracle. A run at the fallback K must be distinguishable from a measured one."""
    import determinex_calibrate as dc

    monkeypatch.setattr(dc, "PROFILE_PATH", tmp_path / "none.json")
    k, provenance = optimal_k("ollama", "no-such-model")
    assert k == UNCALIBRATED_K
    assert "UNCALIBRATED" in provenance
    assert "determinex_calibrate" in provenance, "must name the command that fixes it"


def test_calibrated_rig_reports_its_provenance(tmp_path, monkeypatch):
    import determinex_calibrate as dc

    prof = tmp_path / "cal.json"
    monkeypatch.setattr(dc, "PROFILE_PATH", prof)
    cal = Calibration(
        backend="vllm", model="m", host=host_fingerprint(), optimal_k=48,
        cand_per_s=3.523, collapsed_at=64, declared_hint=61, points=[],
        measured_at="2026-08-02T00:00:00",
    )
    dc.save_calibration(cal)
    k, provenance = optimal_k("vllm", "m")
    assert k == 48
    assert provenance.startswith("calibrated")


def test_profile_carries_no_personal_data():
    """The profile can travel with an opted-in corpus share, so the machine key must not
    identify a person or a filesystem."""
    fp = host_fingerprint()
    assert "ryang" not in fp.lower()
    assert ":" not in fp and "\\" not in fp and "/" not in fp


def test_sweep_warms_before_measuring():
    """Without a warm-up the first K pays the model load and reports a number that is not
    the machine's -- that mistake produced a flatly wrong conclusion on the first attempt."""
    calls = {"n": 0}

    def gen() -> int:
        calls["n"] += 1
        return 10

    sweep(gen, ks=[1], repeats=1, warmup=2)
    assert calls["n"] == 3, f"expected 2 warm-up + 1 measured call, got {calls['n']}"


def test_env_override_beats_calibration(monkeypatch):
    """The operator always wins. Calibration is advice, not a cage."""
    # NOT `sys.path.insert(0, _SCRIPTS / "hive")`. That line was here and it poisoned every
    # test file collected after this one: with scripts/hive at sys.path[0], the module
    # `scripts/hive/models.py` SHADOWS the package `scripts/models/`, so anything importing
    # `from models.local_model_config_record import ...` -- which
    # ide/backend_command_surface.py does -- died with "'models' is not a package".
    #
    # It bit twice on 2026-08-02: tests/test_autofix_pipeline.py and
    # tests/test_oracle_cost_gate.py both failed only when run after this file. Alphabetical
    # collection puts test_calibration_k before both, so it was on course to break the full
    # suite. `hive` is a package under `scripts`, which is already on the path, so the insert
    # bought nothing.
    from hive.amplifier_bridge import env_k

    monkeypatch.setenv("DETERMINEX_AMPLIFY_K", "3")
    assert env_k(default=6, backend="vllm", model="m") == 3


@pytest.mark.parametrize("bad", ["", "abc", "-1"])
def test_bad_env_value_does_not_crash_a_build(monkeypatch, bad):
    from hive.amplifier_bridge import env_k

    monkeypatch.setenv("DETERMINEX_AMPLIFY_K", bad)
    assert env_k(default=6) >= 1


def test_vllm_hint_arithmetic_matches_the_declared_limit():
    """31504 blocks * 16 tokens / 8192 = 61, and the server's boot log said 61.83x. The hint
    is only a sweep bound, but it should agree with the hardware that produced it."""
    blocks, block_size, max_len = 31504, 16, 8192
    assert (blocks * block_size) // max_len == 61
    collapsed = pick_optimal(_points(RADEON))[1]
    assert collapsed > 61, "the measured collapse should sit just past the declared ceiling"


# ── the live-GPU findings (2026-08-02) ──────────────────────────────────────────────────
# Everything above this line was validated against a RECORDING. On 2026-08-02 the calibrator
# was run against a live AMD Radeon MI-series GPU for the first time and got two things
# wrong, both of which are now pinned here.
#
# Captured verbatim from that run (vLLM, Qwen2.5-Coder-7B-Instruct, max_model_len 32768):
# rows are (K, wall_s, agg_tok_s).
RADEON_LIVE = [
    (1, 1.617, 16.7), (4, 1.807, 59.8), (8, 2.102, 102.8), (16, 2.259, 191.3),
    (24, 2.494, 259.8), (32, 2.567, 336.5), (48, 3.26, 397.6), (64, 3.418, 505.6),
    (96, 4.439, 583.9), (128, 4.993, 692.2), (192, 6.707, 772.9), (256, 8.362, 826.6),
    (320, 9.622, 898.0), (448, 13.21, 915.6), (640, 18.732, 922.5),
]


def test_a_flattening_curve_is_a_ceiling_even_though_nothing_fell():
    """The defect: throughput never fell, so collapse detection said "more headroom" and the
    machine-optimum picked K=640 -- double the K of K=320 for 2.7% more throughput, and
    double the latency. A ceiling that saturates is still a ceiling."""
    from determinex_calibrate import detect_ceiling

    pts = _points(RADEON_LIVE)
    assert pick_optimal(pts)[1] is None, "no collapse in this curve -- that is the premise"
    kind, k = detect_ceiling(pts)
    assert kind == "saturation"
    assert k == 320, f"expected the last K that earned its concurrency, got {k}"


def test_collapse_is_not_relabelled_as_saturation():
    """Negative control. A detector that answers 'saturation' for every curve would pass the
    test above while destroying the distinction it exists to make."""
    from determinex_calibrate import detect_ceiling

    kind, k = detect_ceiling(_points(RADEON))
    assert kind == "collapse", "the captured Radeon curve genuinely falls at K=64"
    assert k == 64


def test_a_task_the_model_already_solves_needs_K_of_one():
    """The run that forced this: the probe task measured p=1.00 -- five one-shot passes out
    of five -- and the calibrator recommended K=16. Fifteen requests bought nothing. No K
    derived from the machine alone can be right, because the machine cannot see the task."""
    from determinex_calibrate import optimal_k_for

    k, _ = optimal_k_for(_points(RADEON_LIVE), p=1.0)
    assert k == 1


def test_K_rises_as_the_task_gets_harder_on_identical_hardware():
    """Same GPU, same curve, K spanning 1..128 purely because difficulty changed. This is
    the property a per-machine constant cannot express."""
    from determinex_calibrate import optimal_k_for

    pts = _points(RADEON_LIVE)
    ks = [optimal_k_for(pts, p)[0] for p in (1.0, 0.5, 0.25, 0.1, 0.02, 0.005)]
    assert ks == sorted(ks), f"K must be non-decreasing as p falls, got {ks}"
    assert ks[0] == 1 and ks[-1] >= 64, f"expected a wide span, got {ks}"


def test_the_new_rule_is_never_worse_than_the_machine_optimum():
    """It is not enough that the new rule differs -- it must dominate, at every difficulty,
    on the real curve. Minimising E[time] cannot be beaten by a fixed K by construction, so
    this is really a guard against an implementation that does not do what the docstring says."""
    from determinex_calibrate import expected_time_to_solve, optimal_k_for

    pts = _points(RADEON_LIVE)
    machine_k = pick_optimal(pts)[0]
    for p in (1.0, 0.5, 0.25, 0.1, 0.05, 0.02, 0.005):
        table = dict(expected_time_to_solve(pts, p))
        _, chosen = optimal_k_for(pts, p)
        assert chosen <= table[machine_k] + 1e-9, f"p={p}: new rule lost to fixed K={machine_k}"


def test_a_declared_hint_never_truncates_the_sweep():
    """The hint is kv_tokens // max_model_len, which assumes every request uses the model's
    FULL context. Live, vLLM took max_model_len=32768 while the probe used ~72 tokens: the
    hint said 15 and the GPU was still scaling linearly at K=640. The old `k <= hint * 1.2`
    filter would have stopped the sweep at 16 and reported a ceiling that does not exist."""
    hint = 15
    base = [1, 2, 4, 8, 16, 32, 48, 64]
    ks = sorted({*base, *(hint * m for m in (1, 2, 4, 8) if hint * m > 0)})
    assert max(ks) > hint * 4, "the sweep must reach well past the declaration"
    assert len([k for k in ks if k > hint]) >= 4, "and take several points past it"


def test_p_aware_lookup_says_so_and_task_blind_lookup_admits_it(tmp_path, monkeypatch):
    """A caller silently receiving a task-blind K is how p=1.00 came to sample 16 candidates.
    Both paths must be self-describing."""
    import determinex_calibrate as C

    prof = tmp_path / "cal.json"
    monkeypatch.setattr(C, "PROFILE_PATH", prof)
    cal = Calibration(
        backend="vllm", model="m", host=host_fingerprint(), optimal_k=640,
        cand_per_s=34.17, collapsed_at=None, declared_hint=15,
        points=[p.__dict__ for p in _points(RADEON_LIVE)],
        measured_at="2026-08-02T00:00:00", ceiling_kind="saturation", ceiling_k=320,
    )
    C.save_calibration(cal)

    # 32, not 640. This assertion originally read `== 640` (the machine optimum) and was
    # corrected once the corpus entry amplification_floor_p_must_exceed_zero was consulted:
    # a task-blind K should be the nearly-free one. See
    # test_the_task_blind_default_is_nearly_free_not_the_machine_optimum.
    k_blind, prov_blind = C.optimal_k("vllm", "m")
    assert k_blind == 32 and "task-blind" in prov_blind

    k_easy, prov_easy = C.optimal_k("vllm", "m", p=1.0)
    assert k_easy == 1, "with p supplied it must re-derive from the stored curve"
    assert "p=1" in prov_easy

    k_hard, _ = C.optimal_k("vllm", "m", p=0.005)
    assert k_hard > k_easy


def test_a_profile_without_a_curve_admits_it_cannot_use_p(tmp_path, monkeypatch):
    """Profiles written before curve storage exist on disk. Answering a p-query from one
    would be a confident number derived from nothing."""
    import determinex_calibrate as C

    monkeypatch.setattr(C, "PROFILE_PATH", tmp_path / "cal.json")
    C.save_calibration(Calibration(
        backend="ollama", model="old", host=host_fingerprint(), optimal_k=8,
        cand_per_s=1.4, collapsed_at=None, declared_hint=None, points=[],
        measured_at="2026-07-01T00:00:00",
    ))
    k, prov = C.optimal_k("ollama", "old", p=0.1)
    assert k == 8
    assert "predates curve storage" in prov and "task-blind" in prov


def test_expected_time_is_the_amplifier_equation_not_an_approximation():
    """W(K) / (1-(1-p)^K), checked against hand arithmetic. If this drifts, every K the
    system chooses drifts with it."""
    from determinex_calibrate import expected_time_to_solve

    pts = [KPoint(4, 2.0, 100, 50.0, 2.0)]
    (k, secs), = expected_time_to_solve(pts, 0.5)
    assert k == 4
    assert secs == pytest.approx(2.0 / (1 - 0.5 ** 4), rel=1e-9)


def test_impossible_task_yields_no_recommendation_rather_than_a_guess():
    """p=0 means no K helps. Returning a confident K there would be the calibrator claiming
    a solution rate it cannot produce -- the same shape as an oracle that silently passes."""
    from determinex_calibrate import expected_time_to_solve, optimal_k_for

    pts = _points(RADEON_LIVE)
    assert expected_time_to_solve(pts, 0.0) == []
    k, secs = optimal_k_for(pts, 0.0)
    assert k == UNCALIBRATED_K and secs == float("inf")


def test_one_slow_sample_does_not_invent_a_ceiling():
    """REGRESSION. The first saturation detector compared each K to the next and stopped at
    the first sub-15%-per-doubling step. Run live with --repeats 1 it reported "saturation at
    K=16" on this curve -- which then went 8.5 -> 18.8 -> 32.8 cand/s. K=32 measured 3.744s,
    SLOWER than K=64's 3.413s, which is jitter, not physics. A local gradient asks about two
    samples; a ceiling is a claim about the whole curve."""
    from determinex_calibrate import detect_ceiling

    noisy = _points([
        (1, 1.637, 16.5), (4, 1.94, 55.7), (8, 1.884, 114.6), (16, 2.12, 203.7),
        (32, 3.744, 230.8),   # <- the jitter that fooled the first version
        (64, 3.413, 506.3), (128, 5.326, 648.9), (256, 8.707, 793.8),
        (320, 9.797, 881.9), (448, 13.665, 885.2),
    ])
    kind, k = detect_ceiling(noisy)
    assert kind == "saturation"
    assert k == 320, f"the cheapest K within 90% of peak is 320, got {k}"


def test_a_sweep_that_never_flattened_reports_no_ceiling():
    """If the threshold is first met at the LARGEST K swept, the curve was still climbing
    when the sweep stopped. Calling that a ceiling would manufacture one at whatever K the
    operator happened to stop at."""
    from determinex_calibrate import detect_ceiling

    kind, k = detect_ceiling(_points(CONSUMER))
    assert (kind, k) == ("none", None)


def test_one_failed_request_does_not_discard_the_whole_sweep():
    """REGRESSION. A 12-point sweep against a remote GPU died at K=640 -- the frp tunnel
    returned HTTP 502 for part of the fan-out -- and the exception propagated out of
    ex.map, ending the run. Eleven already-measured points were discarded and the CLI
    printed nothing at all."""
    calls = {"n": 0}

    def flaky() -> int:
        calls["n"] += 1
        if calls["n"] % 3 == 0:
            raise OSError("502 Bad Gateway")
        return 20

    pts = sweep(flaky, [1, 2, 4], repeats=1, warmup=0)
    assert [p.k for p in pts] == [1, 2, 4], "every K must still be measured"
    assert sum(p.errors for p in pts) > 0, "and the failures must be recorded, not hidden"


def test_a_badly_degraded_point_is_excluded_rather_than_averaged_in():
    """Counting failures is not the same as tolerating them. A wall time that includes
    requests which never completed is not a throughput measurement, so such a point must
    not be allowed to select K -- silently using it is the same shape as an oracle that
    passes because it could not run."""
    from determinex_calibrate import detect_ceiling, optimal_k_for

    good = KPoint(8, 2.0, 200, 100.0, 4.0, errors=0)
    junk = KPoint(64, 0.4, 5, 12.5, 160.0, errors=60)  # 'fastest' only because it 502'd
    assert good.usable and not junk.usable

    best, _ = pick_optimal([good, junk])
    assert best == 8, "the degraded point must not win on a wall time it did not earn"
    assert optimal_k_for([good, junk], 0.2)[0] == 8
    assert detect_ceiling([good, junk]) == ("none", None)


def test_a_sweep_where_everything_failed_reports_nothing_rather_than_a_number():
    """If no point is usable there is no measurement, and returning the conservative
    default silently would present 'the endpoint is unreachable' as 'this rig is slow'."""
    def dead() -> int:
        raise OSError("connection refused")

    pts = sweep(dead, [1, 2], repeats=1, warmup=0)
    assert not any(p.usable for p in pts)
    assert pick_optimal(pts) == (UNCALIBRATED_K, None)


def test_a_slow_serial_oracle_costs_time_but_does_not_change_K():
    """Verified search generates K candidates concurrently and then verifies them ONE AT A
    TIME, breaking at the first pass. The intuition is that an expensive oracle should push
    K down. The arithmetic says otherwise: expected verifications to the first success is
    1/p however you batch them, so the oracle term is K-independent and shifts every K by
    the same constant.

    Pinned because the intuition is wrong and someone will eventually 'fix' this."""
    from determinex_calibrate import expected_time_to_solve, optimal_k_for

    pts = _points(RADEON_LIVE)
    for p in (0.5, 0.25, 0.1, 0.05, 0.02):
        k_free, t_free = optimal_k_for(pts, p, verify_s=0.0)
        k_slow, t_slow = optimal_k_for(pts, p, verify_s=10.0)
        assert k_slow == k_free, f"p={p}: oracle cost must not move the argmin"
        assert t_slow > t_free, "but it must show up in the estimate"
        # ...and the shift is exactly verify_s / p, at EVERY K, not just the winner.
        free = dict(expected_time_to_solve(pts, p, 0.0))
        slow = dict(expected_time_to_solve(pts, p, 10.0))
        for k in free:
            assert slow[k] - free[k] == pytest.approx(10.0 / p, rel=1e-9)


def test_the_estimate_reflects_a_real_oracle_rather_than_generation_alone():
    """A user planning a run at p=0.02 behind a 10s Docker oracle needs ~505s, not the ~5s
    that generation throughput alone implies. Reporting the latter is not a small error --
    it is two orders of magnitude, and it is the number that decides whether someone walks
    away from the machine."""
    from determinex_calibrate import optimal_k_for

    _, seconds = optimal_k_for(_points(RADEON_LIVE), 0.02, verify_s=10.0)
    assert 450 < seconds < 600, seconds


def test_the_task_blind_default_is_nearly_free_not_the_machine_optimum():
    """The corpus (amplification_floor_p_must_exceed_zero, 960 generations, 2026-07-31)
    concluded 'run large K always, it is nearly free' and independently chose K=32. This
    module's machine optimum returns K=640 on the live curve -- 11.6x the latency of K=1
    for 2.7% more throughput than K=320. Both were trying to say 'go large'; only one of
    them means it as a statement about latency."""
    from determinex_calibrate import free_k, pick_optimal

    pts = _points(RADEON_LIVE)
    assert pick_optimal(pts)[0] == 640, "machine optimum is the peak, by construction"
    assert free_k(pts) == 32, "nearly-free K reproduces the corpus's independent figure"


def test_going_large_really_is_nearly_free_on_this_curve():
    """The premise the corpus policy rests on, re-measured. If this stops holding on some
    rig, `free_k` will return a small K there and the policy self-corrects."""
    pts = {p.k: p for p in _points(RADEON_LIVE)}
    assert pts[32].wall_s / pts[1].wall_s < 2.0
    assert pts[640].wall_s / pts[1].wall_s > 10.0


def test_p_aware_tuning_is_a_modest_win_over_a_sane_default_not_an_order_of_magnitude():
    """Guards against the overclaim this module made on 2026-08-02, which measured the
    p-aware rule against K=640 -- its own defective machine optimum -- and reported up to
    11.6x. Against the nearly-free K the honest figure is 1.0-1.6x."""
    from determinex_calibrate import expected_time_to_solve, free_k, optimal_k_for

    pts = _points(RADEON_LIVE)
    baseline = free_k(pts)
    for p in (1.0, 0.5, 0.1, 0.02):
        table = dict(expected_time_to_solve(pts, p))
        _, tuned = optimal_k_for(pts, p)
        speedup = table[baseline] / tuned
        assert 1.0 <= speedup < 2.0, f"p={p}: expected a modest win, got {speedup:.2f}x"


def test_a_stored_curve_with_no_p_returns_the_nearly_free_K(tmp_path, monkeypatch):
    """End to end: the lookup callers actually use must honour the reconciliation."""
    import determinex_calibrate as C

    monkeypatch.setattr(C, "PROFILE_PATH", tmp_path / "cal.json")
    C.save_calibration(Calibration(
        backend="vllm", model="m", host=host_fingerprint(), optimal_k=640,
        cand_per_s=34.17, collapsed_at=None, declared_hint=15,
        points=[p.__dict__ for p in _points(RADEON_LIVE)],
        measured_at="2026-08-02T00:00:00", ceiling_kind="saturation", ceiling_k=320,
    ))
    k, prov = C.optimal_k("vllm", "m")
    assert k == 32, f"task-blind lookup must return the nearly-free K, got {k}"
    assert "nearly-free" in prov and "task-blind" in prov
