#!/usr/bin/env python3
"""
Warden — Direct "With vs Without Warden" Empirical Comparison Harness.

Evaluates the 210 attack/benign sample corpus under two modes:
  Mode A: WITHOUT WARDEN (Direct LLM — raw prompts hit the generative LLM on GPU)
  Mode B: WITH WARDEN (Multi-Tier Cascading Engine — early exit at T0/T0.5/T1)

BOTH power columns are measured live via rocm-smi (PowerBenchmark from
benchmarks/measure_power.py) — never modeled or hardcoded. If rocm-smi
is not available the script REFUSES to run and writes nothing.

Usage:
  # Quick: ~10 real GPU generations for the baseline, all 210 samples through Warden
  python scripts/compare_with_without_warden.py --quick

  # Full: 210 real GPU generations for the baseline (~10 min on W7900)
  python scripts/compare_with_without_warden.py --full
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "benchmarks" / "results"
MANIFEST_PATH = REPO_ROOT / "attack_samples_v2" / "manifest.jsonl"
OUT_FILE = OUT_DIR / "compare_with_without_warden.json"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarks.measure_power import PowerBenchmark


def load_samples() -> list[dict]:
    if not MANIFEST_PATH.exists():
        raise SystemExit(f"Error: Manifest file not found at {MANIFEST_PATH}")
    samples = []
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                samples.append(json.loads(line))
    return samples


def build_orchestrator():
    from warden.config import WardenConfig
    from warden.cli import create_router
    from warden.memory.audit_log import AuditLog
    from warden.guards.policy import PolicyEngine
    from warden.guards.diff_guard import DiffGuard
    from warden.camel.interpreter import CaMeLInterpreter
    from warden.orchestrator import WardenOrchestrator

    config = WardenConfig.from_env()
    router_obj = create_router(config)
    audit = AuditLog("warden_audit.db")
    audit.initialize()
    policy = PolicyEngine("policies/default.yaml")
    policy.load()
    diff_guard = DiffGuard()
    camel = CaMeLInterpreter(llm=router_obj.tier2, policy=policy)
    orchestrator = WardenOrchestrator(
        router=router_obj, camel=camel, diff_guard=diff_guard,
        policy=policy, audit=audit
    )
    return router_obj, orchestrator


def measure_baseline(router_obj, samples, quick: bool, max_tokens: int = 20):
    """Mode A: run real GPU generations under rocm-smi sampling.

    Returns (avg_latency_ms, summary) where summary is a PowerSummary.
    Raises if the LLM is not loaded — no fabricated numbers, ever.
    """
    tier2 = router_obj.tier2
    if not (tier2 and tier2.is_available()):
        raise SystemExit(
            "ERROR: Tier 2 LLM is not loaded — cannot measure the without-Warden baseline.\n"
            "  Start the app with the GGUF model configured (WARDEN_LLM_MODEL_PATH) and retry."
        )

    subset = samples[:10] if quick else samples
    print(f"\n[MODE A] WITHOUT WARDEN — running {len(subset)} real GPU generations "
          f"({'quick' if quick else 'full'})...")

    latencies = []
    bench = PowerBenchmark(str(OUT_DIR / "baseline_telemetry.csv"), interval_ms=100)
    bench.start_monitoring()
    try:
        for s in subset:
            text = s.get("prompt", "") or s.get("text", "")
            t0 = time.perf_counter()
            out = tier2.generate(text, max_tokens=max_tokens)
            ms = (time.perf_counter() - t0) * 1000
            latencies.append(ms)
            if not out.strip():
                print(f"  [WARNING] empty generation for: {text[:50]}...")
    finally:
        summary = bench.stop_monitoring()

    if not summary.rocm_available or summary.samples == 0:
        raise SystemExit(
            "ERROR: rocm-smi produced no telemetry samples during baseline — "
            "refusing to report power numbers. Check that rocm-smi works on this host."
        )

    avg_lat = sum(latencies) / len(latencies) if latencies else 0.0
    print(f"  baseline avg latency: {avg_lat:.1f} ms | measured power: "
          f"{summary.avg_watts:.1f} W (max {summary.max_watts:.1f} W, {summary.samples} samples)")
    return avg_lat, summary


def measure_with_warden(router_obj, samples):
    """Mode B: route all samples through the tier cascade under rocm-smi sampling.

    Uses router.route() directly (identical cascade to guard_input) so the
    tier distribution reflects the REAL resolving tier per sample.
    """
    from warden.config import Decision

    print(f"\n[MODE B] WITH WARDEN — routing {len(samples)} samples through the tier cascade...")
    latencies = []
    blocked = 0
    tier_counts = {"tier0": 0, "tier0_5": 0, "tier1": 0, "tier2": 0, "memory": 0, "policy": 0}

    def _tier_key(result) -> str:
        if getattr(result, "memory_hit", False):
            return "memory"
        if getattr(result, "policy_hit", False):
            return "policy"
        reached = getattr(result, "tier_reached", -1)
        if reached == 0:
            exp = (result.explanation or "").lower()
            if "normalizer" in exp or "homoglyph" in exp or "base64" in exp or "decoded" in exp:
                return "tier0_5"
            return "tier0"
        if reached == 1:
            return "tier1"
        if reached >= 2:
            return "tier2"
        return "tier0"

    bench = PowerBenchmark(str(OUT_DIR / "warden_telemetry.csv"), interval_ms=100)
    bench.start_monitoring()
    try:
        for s in samples:
            text = s.get("prompt", "") or s.get("text", "")
            expected = s.get("expected", "block")
            t0 = time.perf_counter()
            res = router_obj.route(text, source="user_input")
            latencies.append((time.perf_counter() - t0) * 1000)
            if res.decision in (Decision.BLOCK, Decision.FLAG):
                if expected == "block":
                    blocked += 1
                tier = _tier_key(res)
                tier_counts[tier] = tier_counts.get(tier, 0) + 1
    finally:
        summary = bench.stop_monitoring()

    if not summary.rocm_available or summary.samples == 0:
        raise SystemExit(
            "ERROR: rocm-smi produced no telemetry samples during Warden routing — "
            "refusing to report power numbers."
        )

    avg_lat = sum(latencies) / len(latencies) if latencies else 0.0
    print(f"  warden avg latency: {avg_lat:.2f} ms | measured power: "
          f"{summary.avg_watts:.2f} W (max {summary.max_watts:.2f} W, {summary.samples} samples)")
    print(f"  attacks stopped early: {blocked}/{len(samples)} | tier counts: {tier_counts}")
    return avg_lat, summary, blocked, tier_counts


def main() -> None:
    parser = argparse.ArgumentParser(description="With vs Without Warden comparison harness")
    parser.add_argument(
        "--quick", action="store_true",
        help="Baseline: 10 real GPU generations instead of all 210 (~1 min vs ~10 min)",
    )
    parser.add_argument("--full", action="store_true", help="Baseline: all 210 samples through the real LLM")
    parser.add_argument("--max-tokens", type=int, default=20, help="Tokens per baseline generation")
    args = parser.parse_args()
    if args.full:
        args.quick = False

    print("=" * 72)
    print("  WARDEN DIRECT 'WITH VS WITHOUT' COMPARISON HARNESS (210 SAMPLES)")
    print("  Power: LIVE rocm-smi telemetry — no modeled numbers")
    print("=" * 72)

    samples = load_samples()
    router_obj, orchestrator = build_orchestrator()

    # Mode A: without Warden — real GPU generations under rocm-smi
    noW_avg_lat, noW_summary = measure_baseline(router_obj, samples, quick=not args.full, max_tokens=args.max_tokens)

    # Mode B: with Warden — route everything under rocm-smi
    W_avg_lat, W_summary, W_blocked, W_tier_counts = measure_with_warden(router_obj, samples)

    total = len(samples)
    noW_avg_power = noW_summary.avg_watts
    W_avg_power = W_summary.avg_watts

    power_saved_pct = round((1.0 - (W_avg_power / noW_avg_power)) * 100, 1) if noW_avg_power > 0 else 0.0
    lat_saved_pct = round((1.0 - (W_avg_lat / noW_avg_lat)) * 100, 1) if noW_avg_lat > 0 else 0.0

    # Energy for 10,000 requests (kWh) from measured power × measured latency
    noW_kwh_10k = (noW_avg_power * (noW_avg_lat / 1000) / 3600 / 1000) * 10000
    W_kwh_10k = (W_avg_power * (W_avg_lat / 1000) / 3600 / 1000) * 10000

    result_data = {
        "total_samples": total,
        "measured": {
            "rocm_smi_available": noW_summary.rocm_available,
            "baseline_samples": noW_summary.samples,
            "warden_samples": W_summary.samples,
            "gpu_name": noW_summary.gpu_name or W_summary.gpu_name,
        },
        "without_warden": {
            "avg_latency_ms": round(noW_avg_lat, 2),
            "avg_power_w": round(noW_avg_power, 2),
            "max_power_w": round(noW_summary.max_watts, 2),
            "attacks_blocked_before_gpu": 0,
            "energy_kwh_per_10k_req": round(noW_kwh_10k, 4),
            "cloud_gpu_cost_per_hr": 3.50,
        },
        "with_warden": {
            "avg_latency_ms": round(W_avg_lat, 2),
            "avg_power_w": round(W_avg_power, 2),
            "max_power_w": round(W_summary.max_watts, 2),
            "attacks_blocked_before_gpu": W_blocked,
            "tier_distribution": W_tier_counts,
            "energy_kwh_per_10k_req": round(W_kwh_10k, 4),
            "cloud_gpu_cost_per_hr": 3.50,
        },
        "savings": {
            "power_saved_pct": power_saved_pct,
            "latency_reduction_pct": lat_saved_pct,
            "power_saved_watts": round(noW_avg_power - W_avg_power, 2),
            "attacks_stopped_early_pct": round((W_blocked / total) * 100, 1),
        },
    }

    print("\n" + "=" * 72)
    print("                     MEASURED COMPARISON RESULTS")
    print("=" * 72)
    print(f" Metric                      WITHOUT WARDEN         WITH WARDEN")
    print(" ------------------------   -------------------   -------------------")
    print(f" Avg Latency per Request    {noW_avg_lat:8.1f} ms           {W_avg_lat:8.2f} ms")
    print(f" Avg GPU Power Draw         {noW_avg_power:8.1f} W           {W_avg_power:8.2f} W")
    print(f" Max GPU Power Draw         {noW_summary.max_watts:8.1f} W           {W_summary.max_watts:8.2f} W")
    print(f" Energy per 10k Reqs        {noW_kwh_10k:8.4f} kWh        {W_kwh_10k:8.4f} kWh")
    print(f" Attacks Stopped Early      0 / {total}                {W_blocked} / {total} ({(W_blocked/total)*100:.1f}%)")
    print("=" * 72)
    print(f" [POWER SAVINGS]:   {power_saved_pct}% ({result_data['savings']['power_saved_watts']}W saved per request)")
    print(f" [LATENCY SAVINGS]: {lat_saved_pct}% latency reduction")
    print("=" * 72)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(result_data, indent=2), encoding="utf-8")
    print(f"\nSaved measured comparison JSON to: {OUT_FILE}")


if __name__ == "__main__":
    main()
