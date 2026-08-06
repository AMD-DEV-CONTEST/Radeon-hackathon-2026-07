"""Autotune composite scorer (tune-loop plan, Todo 3).

Pure stdlib — NO gradio / pandas / GPU imports. Computes a single 0..1 score
from observ events so the tuning cycle can decide keep-vs-rollback.

Honest-output invariants (aligned with observatory-v3 T4 discipline):
  * Never fabricate a measurement — below MIN_N events we return None (no verdict).
  * A missing gpu dimension degrades gracefully (it is NOT counted, not assumed 0).
  * The score is a normalized composite, not a causal claim; callers label
    differences "with confounders, not causal proof".
"""
from __future__ import annotations

from screwshell.ui.analysis import _mean, sample_count_ok

# Reference points for normalization (module constants, override-free).
# TTFT reference: 2000 ms is treated as "worst acceptable" (1 - ttft/REF).
REF_TTFT_MS = 2000.0
# Decode throughput reference: README §1.5 — 31 tok/s decode on base, 23.4-26
# with an active adapter. Use 31 as the "ideal" ceiling.
REF_TPS = 31.0

DEFAULT_WEIGHTS: dict[str, float] = {
    "ttft_ms": 0.4,
    "decode_tps": 0.2,
    "kv_hit_rate": 0.2,
    "ok_rate": 0.2,
}

# When gpu_samples are supplied, vram utilization is folded in with this weight,
# redistributed from the base weights proportionally so the total stays 1.0.
VRAM_WEIGHT = 0.2

MIN_N = 16  # T4 sample discipline — mirror analysis.sample_count_ok default.


def _extract(events: list[dict]) -> dict[str, float | None]:
    """Pull the four canonical metrics' means from event dicts."""
    ttft = _mean([e.get("ttft_ms") for e in events])
    tps = _mean([e.get("decode_tps") for e in events])
    kv = _mean([e.get("kv_hit_rate") for e in events])
    ok = _mean([1.0 if e.get("ok") else 0.0 for e in events])
    return {"ttft_ms": ttft, "decode_tps": tps, "kv_hit_rate": kv, "ok_rate": ok}


def _vram_util(gpu_samples: list[dict]) -> float | None:
    uses = [s.get("vram_used_gb") for s in gpu_samples]
    totals = [s.get("vram_total_gb") for s in gpu_samples]
    u = _mean([x for x in uses if isinstance(x, (int, float))])
    t = _mean([x for x in totals if isinstance(x, (int, float))])
    if u is None or t in (None, 0):
        return None
    return min(u / t, 1.0)


def score(events: list[dict],
          gpu_samples: list[dict] | None = None,
          weights: dict[str, float] | None = None) -> float | None:
    """Composite 0..1 score from events; None when sample size is insufficient.

    ``events`` must contain >= MIN_N dicts with keys ttft_ms / decode_tps /
    kv_hit_rate / ok. ``gpu_samples`` (optional) adds a vram-utilization
    dimension; when absent the score degrades to the 4 base metrics only.
    """
    if not sample_count_ok(len(events or []), MIN_N):
        return None

    m = _extract(events)
    if any(v is None for v in m.values()):
        # partial metrics still present but one dimension fully missing ->
        # we cannot fairly normalize; treat as insufficient.
        return None

    w = dict(weights or DEFAULT_WEIGHTS)

    # base normalized sub-scores
    s_ttft = 1.0 - min((m["ttft_ms"] or 0.0) / REF_TTFT_MS, 1.0)   # smaller better
    s_tps = min((m["decode_tps"] or 0.0) / REF_TPS, 1.0)           # larger better
    s_kv = min(m["kv_hit_rate"] or 0.0, 1.0)                       # larger better
    s_ok = min(m["ok_rate"] or 0.0, 1.0)                           # larger better

    if gpu_samples:
        vu = _vram_util(gpu_samples)
        if vu is None:
            # requested but unusable -> degrade, don't count vram
            gpu_samples = None
        else:
            s_vram = 1.0 - vu  # lower utilization better
    else:
        s_vram = None

    if gpu_samples is not None and s_vram is not None:
        # fold vram in: take VRAM_WEIGHT from the pool, scale base weights.
        base_total = sum(w.values())
        scale = (1.0 - VRAM_WEIGHT) / base_total
        total = (
            w["ttft_ms"] * scale * s_ttft
            + w["decode_tps"] * scale * s_tps
            + w["kv_hit_rate"] * scale * s_kv
            + w["ok_rate"] * scale * s_ok
            + VRAM_WEIGHT * s_vram
        )
    else:
        total = (
            w["ttft_ms"] * s_ttft
            + w["decode_tps"] * s_tps
            + w["kv_hit_rate"] * s_kv
            + w["ok_rate"] * s_ok
        )
    return max(0.0, min(total, 1.0))
