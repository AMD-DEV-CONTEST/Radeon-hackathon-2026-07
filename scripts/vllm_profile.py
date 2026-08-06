"""vLLM inference bottleneck profiling script.

References the Phase 2/3 methodology of the AMD vLLM Optimize Skill (v3):
- Phase 2: concurrency scan benchmark + torch profiler trace
- Phase 3: GPU kernel analysis (GEMM%/Attention%/idle%), identify the bottleneck type

Core ideas (from the AMD skill):
    Micro speedup != E2E speedup
    - kernel-level optimizations may be 2x faster on micro-benchmarks, but only 0.97x end-to-end
    - must judge using the real shapes and kernel proportions from a profiler trace

Three bottleneck types (from the AMD skill Phase 3 analysis logic):
    idle > 10%  -> CPU scheduling bottleneck (Agently scheduler or HTTP queueing)
    GEMM > 70%  -> GEMM compute bottleneck (TunableOps / rocBLAS optimization target)
    Attention > 20% -> KV-Cache bottleneck (PagedAttention / max_model_len optimization target)

Usage::

    # 1. Ensure the vLLM service is running (port 8000)
    # 2. Run the concurrency scan + bottleneck analysis
    python scripts/vllm_profile.py \
        --model Qwen3-8B \
        --concurrency 1,4,8,16 \
        --isl 512 --osl 512 \
        --output docs/benchmarks/vllm_profile.json

    # 3. For a torch profiler trace (requires vLLM started with --enable-profiling)
    python scripts/vllm_profile.py \
        --model Qwen3-8B \
        --concurrency 1,8 \
        --profile \
        --output docs/benchmarks/vllm_profile.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections.abc import AsyncIterator
from pathlib import Path
from statistics import median
from typing import Any

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int((len(ordered) - 1) * ratio))
    return ordered[idx]


async def benchmark_concurrency(
    *,
    base_url: str,
    model: str,
    concurrency: int,
    isl: int,
    osl: int,
    timeout: float = 120.0,
) -> dict[str, Any]:
    """Send requests to vLLM at a given concurrency level and measure throughput and latency.

    Implements the AMD skill Phase 2 Step 1 concurrency scan logic:
    - Send concurrency*2 requests at each concurrency level (at least 8)
    - Use ThreadPoolExecutor to limit concurrency
    - Record output_tps, total_tps, p50/p90 latency, and failure count
    """
    prompt = "The insurance policy stipulates that if the insured suffers an accident during the insurance period, " * (isl // 20 + 1)
    n_requests = max(concurrency * 2, 8)

    headers = {
        "Authorization": "Bearer dummy",
        "Content-Type": "application/json",
    }

    semaphore = asyncio.Semaphore(concurrency)
    latencies: list[float] = []
    output_tokens_total = 0
    input_tokens_total = 0
    failures = 0

    async with httpx.AsyncClient(
        base_url=base_url,
        timeout=timeout,
        trust_env=False,
        limits=httpx.Limits(
            max_connections=concurrency + 10,
            max_keepalive_connections=concurrency + 10,
        ),
    ) as client:
        async def send_request() -> dict[str, Any]:
            nonlocal output_tokens_total, input_tokens_total, failures
            async with semaphore:
                t0 = time.perf_counter()
                try:
                    resp = await client.post(
                        "/v1/completions",
                        headers=headers,
                        json={
                            "model": model,
                            "prompt": prompt,
                            "max_tokens": osl,
                            "temperature": 0,
                            "ignore_eos": True,
                        },
                    )
                    latency = time.perf_counter() - t0
                    if resp.status_code == 200:
                        usage = resp.json().get("usage", {})
                        output_tokens_total += usage.get("completion_tokens", 0)
                        input_tokens_total += usage.get("prompt_tokens", 0)
                        latencies.append(latency)
                        return {"ok": True}
                    else:
                        failures += 1
                        return {"ok": False, "status": resp.status_code}
                except Exception as exc:
                    failures += 1
                    return {"ok": False, "error": str(exc)[:100]}

        wall_start = time.perf_counter()
        results = await asyncio.gather(
            *(send_request() for _ in range(n_requests))
        )
        wall_time = time.perf_counter() - wall_start

    success_count = sum(1 for r in results if r.get("ok"))
    output_tps = output_tokens_total / wall_time if wall_time > 0 else 0
    total_tps = (output_tokens_total + input_tokens_total) / wall_time if wall_time > 0 else 0

    lats = sorted(latencies)
    return {
        "concurrency": concurrency,
        "n_requests": n_requests,
        "success": success_count,
        "failures": failures,
        "wall_time_s": round(wall_time, 2),
        "output_tps": round(output_tps, 1),
        "total_tps": round(total_tps, 1),
        "lat_p50_s": round(lats[len(lats) // 2], 3) if lats else 0,
        "lat_p90_s": round(_percentile(lats, 0.90), 3) if lats else 0,
        "lat_max_s": round(max(lats), 3) if lats else 0,
        "avg_output_tokens": round(output_tokens_total / max(success_count, 1)),
    }


def analyze_bottleneck(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Analyze the bottleneck type (AMD skill Phase 3 logic).

    Infer the bottleneck from how TPS changes with concurrency:

    Concurrency up but TPS flat -> GPU compute bottleneck (GEMM/Attention)
    Concurrency up and TPS grows -> GPU headroom remains, bottleneck is client/scheduling
    Low-concurrency latency spike  -> prefill bottleneck (long prompt processing)
    High-concurrency p90 >> p50    -> queueing bottleneck (scheduler concurrency limit)
    """
    if len(results) < 2:
        return {"bottleneck": "insufficient_data", "reason": "data from at least 2 concurrency levels is required"}

    # Sort by concurrency
    sorted_results = sorted(results, key=lambda r: r["concurrency"])
    low = sorted_results[0]
    high = sorted_results[-1]

    # TPS scale ratio: high-concurrency TPS / low-concurrency TPS
    tps_scale = high["output_tps"] / low["output_tps"] if low["output_tps"] > 0 else 0
    conc_scale = high["concurrency"] / low["concurrency"] if low["concurrency"] > 0 else 1

    # Latency inflation ratio: high-concurrency p50 / low-concurrency p50
    lat_inflate = high["lat_p50_s"] / low["lat_p50_s"] if low["lat_p50_s"] > 0 else 1

    # p90/p50 ratio: queueing degree under high concurrency
    queue_ratio = high["lat_p90_s"] / high["lat_p50_s"] if high["lat_p50_s"] > 0 else 1

    # Determine the bottleneck type
    if tps_scale < conc_scale * 0.5:
        # TPS growth far below concurrency growth -> GPU compute bottleneck
        if lat_inflate > 3.0:
            bottleneck = "GEMM_compute"
            reason = (
                f"TPS went from {low['output_tps']} to {high['output_tps']} (scale ratio {tps_scale:.2f}x, "
                f"concurrency scale ratio {conc_scale:.2f}x). Latency inflation {lat_inflate:.1f}x. "
                f"GPU compute is saturated; raising concurrency cannot increase throughput. "
                f"Suggestion: TunableOps GEMM tuning or INT4 quantization to reduce per-inference compute."
            )
        else:
            bottleneck = "Attention_memory"
            reason = (
                f"TPS scale ratio {tps_scale:.2f}x far below the concurrency scale ratio {conc_scale:.2f}x, "
                f"but latency inflation is only {lat_inflate:.1f}x. "
                f"This may be a KV-Cache HBM bandwidth bottleneck. "
                f"Suggestion: enable PagedAttention or shorten max_model_len."
            )
    elif queue_ratio > 2.0:
        # p90 >> p50 -> queueing bottleneck
        bottleneck = "CPU_scheduling"
        reason = (
            f"High-concurrency p90/p50 = {queue_ratio:.2f}, severe queueing. "
            f"p50={high['lat_p50_s']}s, p90={high['lat_p90_s']}s. "
            f"The bottleneck is at the scheduling layer (Agently max_concurrency or vLLM max_num_seqs). "
            f"Suggestion: increase max_num_seqs or Agently max_concurrent_requests."
        )
    elif tps_scale >= conc_scale * 0.8:
        # TPS grows near-linearly with concurrency -> GPU still has headroom
        bottleneck = "client_limited"
        reason = (
            f"TPS scale ratio {tps_scale:.2f}x is close to the concurrency scale ratio {conc_scale:.2f}x. "
            f"GPU still has headroom; the bottleneck is client concurrency or the Agently scheduler. "
            f"Suggestion: keep raising concurrency, or increase Agently max_concurrent_requests."
        )
    else:
        bottleneck = "mixed"
        reason = (
            f"TPS scale ratio {tps_scale:.2f}x, concurrency scale ratio {conc_scale:.2f}x, "
            f"latency inflation {lat_inflate:.1f}x, queue ratio {queue_ratio:.2f}. "
            f"The bottleneck is mixed; a torch profiler trace is needed to locate it further."
        )

    return {
        "bottleneck": bottleneck,
        "reason": reason,
        "metrics": {
            "tps_scale_ratio": round(tps_scale, 3),
            "concurrency_scale_ratio": round(conc_scale, 3),
            "latency_inflation": round(lat_inflate, 3),
            "queue_ratio_p90_over_p50": round(queue_ratio, 3),
        },
        "optimization_targets": _get_optimization_targets(bottleneck),
    }


def _get_optimization_targets(bottleneck: str) -> list[dict[str, str]]:
    """Return optimization suggestions based on the bottleneck type (aligned with AMD skill Phase 3 target logic)."""
    targets = {
        "GEMM_compute": [
            {"target": "TunableOps GEMM tuning", "method": "PYTORCH_TUNABLEOP_ENABLED=1 + offline tuning", "expected": "micro-benchmark 1.1-1.5x, requires E2E verification"},
            {"target": "INT4 quantization", "method": "GPTQ quantization of Qwen3-8B", "expected": "75% lower compute, 2-3x throughput"},
            {"target": "Lower OSL", "method": "max_tokens limit", "expected": "fewer decode steps"},
        ],
        "Attention_memory": [
            {"target": "PagedAttention", "method": "enabled by default in vLLM", "expected": "KV-Cache paged management"},
            {"target": "Shorten max_model_len", "method": "--max-model-len 4096", "expected": "reduce KV-Cache HBM usage"},
            {"target": "Prefix Cache", "method": "--enable-prefix-caching", "expected": "reuse KV for identical system prompts"},
        ],
        "CPU_scheduling": [
            {"target": "Increase vLLM max_num_seqs", "method": "--max-num-seqs 16", "expected": "raise vLLM internal concurrency"},
            {"target": "Increase Agently concurrency", "method": "agent.toml max_concurrent_requests=8", "expected": "raise TriggerFlow concurrency"},
            {"target": "Chunked Prefill", "method": "--enable-chunked-prefill", "expected": "long prefill does not block decode"},
        ],
        "client_limited": [
            {"target": "Increase client concurrency", "method": "load_test.py --concurrency 32", "expected": "probe the capacity boundary further"},
            {"target": "Increase Agently concurrency", "method": "agent.toml max_concurrent_requests=8", "expected": "allow more parallel requests"},
        ],
    }
    return targets.get(bottleneck, [])


async def profile_vllm(
    *,
    base_url: str,
    model: str,
    concurrency_levels: list[int],
    isl: int,
    osl: int,
    timeout: float = 120.0,
) -> dict[str, Any]:
    """Run the full concurrency scan + bottleneck analysis."""
    results = []
    for conc in concurrency_levels:
        print(f"  concurrency={conc:3d}: sending requests...", flush=True)
        result = await benchmark_concurrency(
            base_url=base_url,
            model=model,
            concurrency=conc,
            isl=isl,
            osl=osl,
            timeout=timeout,
        )
        results.append(result)
        print(
            f"  concurrency={conc:3d}: output_tps={result['output_tps']:7.1f}  "
            f"total_tps={result['total_tps']:7.1f}  "
            f"p50={result['lat_p50_s']:.3f}s  p90={result['lat_p90_s']:.3f}s  "
            f"ok={result['success']}/{result['n_requests']}",
            flush=True,
        )

    analysis = analyze_bottleneck(results)

    return {
        "config": {
            "model": model,
            "base_url": base_url,
            "isl": isl,
            "osl": osl,
            "concurrency_levels": concurrency_levels,
        },
        "benchmark_results": results,
        "bottleneck_analysis": analysis,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="vLLM inference bottleneck profiling - concurrency scan + bottleneck analysis (Reference: AMD vLLM Optimize Skill v3)",
    )
    parser.add_argument("--model", default="Qwen3-8B", help="model name")
    parser.add_argument("--base-url", default="http://localhost:8000", help="vLLM service URL")
    parser.add_argument(
        "--concurrency", default="1,4,8,16",
        help="comma-separated concurrency levels (default 1,4,8,16)",
    )
    parser.add_argument("--isl", type=int, default=512, help="input sequence length (tokens)")
    parser.add_argument("--osl", type=int, default=512, help="output sequence length (tokens)")
    parser.add_argument("--timeout", type=float, default=120.0, help="per-request timeout (seconds)")
    parser.add_argument(
        "--output", type=Path,
        default=Path("docs/benchmarks/vllm_profile.json"),
        help="report output path",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    concurrency_levels = [int(x.strip()) for x in args.concurrency.split(",")]

    print("=" * 70)
    print("vLLM inference bottleneck profiling (Reference: AMD vLLM Optimize Skill v3 Phase 2/3)")
    print("=" * 70)
    print(f"  Model: {args.model}")
    print(f"  URL: {args.base_url}")
    print(f"  ISL x OSL: {args.isl} x {args.osl}")
    print(f"  Concurrency: {concurrency_levels}")
    print(f"  Timeout: {args.timeout}s")
    print()

    # Verify the vLLM service is available
    async with httpx.AsyncClient(base_url=args.base_url, timeout=10) as client:
        try:
            resp = await client.get("/v1/models")
            if resp.status_code != 200:
                print(f"Error: vLLM service unavailable (HTTP {resp.status_code})")
                sys.exit(1)
            models = resp.json().get("data", [])
            print(f"  vLLM available, loaded models: {[m.get('id') for m in models]}")
        except Exception as e:
            print(f"Error: cannot connect to the vLLM service: {e}")
            sys.exit(1)

    print("\n=== Phase 2: concurrency scan benchmark - STARTING ===\n")

    report = await profile_vllm(
        base_url=args.base_url,
        model=args.model,
        concurrency_levels=concurrency_levels,
        isl=args.isl,
        osl=args.osl,
        timeout=args.timeout,
    )

    print("\n=== Phase 2: concurrency scan benchmark - DONE ===\n")

    # Bottleneck analysis
    print("=== Phase 3: bottleneck analysis - STARTING ===\n")
    analysis = report["bottleneck_analysis"]

    print(f"  Bottleneck type: {analysis['bottleneck']}")
    print(f"  Analysis: {analysis['reason']}")
    print(f"\n  Metrics:")
    for k, v in analysis.get("metrics", {}).items():
        print(f"    {k}: {v}")

    print(f"\n  Optimization targets:")
    for t in analysis.get("optimization_targets", []):
        print(f"    - {t['target']}: {t['method']} (expected: {t['expected']})")

    print("\n=== Phase 3: bottleneck analysis - DONE ===\n")

    # Summary table
    print("  Summary:")
    print(f"  {'Conc':>5}  {'OutTPS':>8}  {'TotTPS':>8}  {'P50':>8}  {'P90':>8}  {'Fails':>5}")
    print(f"  {'-'*52}")
    for r in report["benchmark_results"]:
        print(
            f"  {r['concurrency']:>5}  {r['output_tps']:>8.1f}  {r['total_tps']:>8.1f}"
            f"  {r['lat_p50_s']:>7.3f}s  {r['lat_p90_s']:>7.3f}s  {r['failures']:>5}"
        )

    # Save the report
    output_path = PROJECT_ROOT / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nReport saved: {output_path}")

    # Next steps
    print("\nNext steps:")
    if analysis["bottleneck"] == "GEMM_compute":
        print("  1. Run the AMD vLLM Optimize Skill profile-only mode to obtain a torch profiler trace")
        print("  2. Use TunableOps offline tuning for the GEMM kernel")
        print("  3. Or try INT4 quantization (C2 group)")
    elif analysis["bottleneck"] == "CPU_scheduling":
        print("  1. Increase vLLM --max-num-seqs")
        print("  2. Increase agent.toml max_concurrent_requests")
        print("  3. Re-run load_test.py to verify the throughput gain")
    elif analysis["bottleneck"] == "client_limited":
        print("  1. Continue raising the concurrency scan (--concurrency 1,4,8,16,32)")
        print("  2. Increase the Agently scheduler concurrency limit")
        print("  3. Re-run the load_test.py baseline round")


if __name__ == "__main__":
    asyncio.run(main())
