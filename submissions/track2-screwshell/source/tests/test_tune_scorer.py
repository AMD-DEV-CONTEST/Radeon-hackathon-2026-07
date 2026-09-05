"""Unit tests for the autotune composite scorer (tune-loop plan, Todo 3)."""
from __future__ import annotations

from screwshell.autotune.scorer import score, DEFAULT_WEIGHTS, MIN_N, REF_TTFT_MS, REF_TPS


def _ev(ttft=500.0, tps=30.0, kv=0.9, ok=True):
    return {"ttft_ms": ttft, "decode_tps": tps, "kv_hit_rate": kv, "ok": ok}


def _many(n, **kw):
    return [_ev(**kw) for _ in range(n)]


def test_empty_returns_none():
    assert score([]) is None


def test_below_min_n_returns_none():
    assert score(_many(MIN_N - 1)) is None


def test_exactly_min_n_scores():
    assert isinstance(score(_many(MIN_N)), float)


def test_score_in_unit_interval():
    s = score(_many(32, ttft=400.0, tps=31.0, kv=1.0, ok=True))
    assert 0.0 <= s <= 1.0


def test_score_matches_hand_computed():
    # 32 identical events -> normalized sub-scores:
    ttft, tps, kv, ok = 1000.0, 31.0, 1.0, True
    s_ttft = 1.0 - min(ttft / REF_TTFT_MS, 1.0)
    s_tps = min(tps / REF_TPS, 1.0)
    s_kv = min(kv, 1.0)
    s_ok = 1.0
    expected = (DEFAULT_WEIGHTS["ttft_ms"] * s_ttft
                + DEFAULT_WEIGHTS["decode_tps"] * s_tps
                + DEFAULT_WEIGHTS["kv_hit_rate"] * s_kv
                + DEFAULT_WEIGHTS["ok_rate"] * s_ok)
    got = score(_many(32, ttft=ttft, tps=tps, kv=kv, ok=ok))
    assert abs(got - expected) < 1e-9


def test_gpu_dimension_folded_in():
    evs = _many(32, ttft=500.0, tps=25.0, kv=0.8, ok=True)
    gpu = [{"vram_used_gb": 20.0, "vram_total_gb": 48.0} for _ in range(32)]
    s_with = score(evs, gpu_samples=gpu)
    s_without = score(evs, gpu_samples=None)
    assert isinstance(s_with, float)
    assert s_with != s_without          # vram dimension changed the score


def test_gpu_missing_degrades_gracefully():
    evs = _many(32, ttft=500.0, tps=25.0, kv=0.8, ok=True)
    # gpu_samples present but unusable (no total) -> must not raise, degrade
    gpu = [{"vram_used_gb": 20.0} for _ in range(32)]
    s = score(evs, gpu_samples=gpu)
    assert isinstance(s, float)         # no exception, vram not counted
