"""vLLM AMD ROCm performance benchmark.

Measures tokens/s, latency (mean/p95), VRAM, GPU utilization
at different batch sizes and concurrency levels.

Usage:
    python scripts/vllm_benchmark.py --vllm-url http://localhost:8000/v1 \
        --model models/qwen-trader-merged
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


SYSTEM_PROMPT = "You are an expert crypto trading strategist. Output ONLY valid YAML."

BENCHMARK_PROMPTS = [
    "Create an EMA crossover strategy for BTC/USDT with EMA 20 and 50, stop loss 3%",
    "RSI超卖策略，BTC/USDT 1小时线，RSI低于30买入，高于70卖出",
    "Bollinger Bands策略，ETH/USDT，价格触及下轨买入，上轨卖出",
    "MACD金叉策略，BTC/USDT 4小时线，止损5%",
    "放量突破策略，EMA20金叉EMA50且放量1.5倍确认",
    "做多做空双向策略，EMA金叉做多，死叉做空",
    "ATR动态止损策略，2倍ATR止损，EMA趋势跟踪",
    "ADX趋势过滤，ADX>25时EMA金叉才入场",
    "多指标共振：EMA金叉+RSI超卖+放量确认",
    "布林带收窄后突破策略，放量确认",
]


def call_vllm_single(vllm_url: str, model: str, prompt: str) -> tuple[int, float, str]:
    """Single request: returns (tokens, latency_ms, response)."""
    import httpx
    t0 = time.time()
    try:
        with httpx.Client(timeout=120.0) as client:
            resp = client.post(f"{vllm_url}/chat/completions", json={
                "model": model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.2,
                "max_tokens": 512,
            })
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            # Count output tokens (approximate: words * 1.3)
            usage = data.get("usage", {})
            tokens = usage.get("completion_tokens", len(content.split()) * 1.3)
            latency = (time.time() - t0) * 1000
            return tokens, latency, content
    except Exception as e:
        return 0, (time.time() - t0) * 1000, f"[ERROR] {e}"


def get_gpu_stats() -> dict:
    """Get GPU utilization and VRAM from rocm-smi."""
    try:
        result = subprocess.run(["rocm-smi", "--showuse", "--showmeminfo", "vram", "--json"],
                                capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            data = json.loads(result.stdout)
            if "0" in data:
                dev = data["0"]
                return {
                    "gpu_util_pct": float(dev.get("GPU use (%)", 0)),
                    "vram_used_mb": int(dev.get("VRAM Total Used Memory (B)", 0)) // (1024 * 1024),
                    "vram_total_mb": int(dev.get("VRAM Total Memory (B)", 0)) // (1024 * 1024),
                }
    except Exception:
        pass
    return {}


def run_sequential(vllm_url: str, model: str, n: int = 10) -> dict:
    """Run n requests sequentially."""
    latencies = []
    total_tokens = 0
    prompts = (BENCHMARK_PROMPTS * (n // len(BENCHMARK_PROMPTS) + 1))[:n]

    t_start = time.time()
    gpu_before = get_gpu_stats()

    for prompt in prompts:
        tokens, lat, _ = call_vllm_single(vllm_url, model, prompt)
        latencies.append(lat)
        total_tokens += tokens

    t_total = time.time() - t_start
    gpu_after = get_gpu_stats()

    lat_sorted = sorted(latencies)
    return {
        "mode": "sequential",
        "requests": n,
        "total_tokens": total_tokens,
        "total_time_s": round(t_total, 2),
        "tokens_per_second": round(total_tokens / t_total, 1) if t_total > 0 else 0,
        "avg_latency_ms": round(statistics.mean(latencies), 1),
        "p50_latency_ms": round(lat_sorted[len(lat_sorted)//2], 1),
        "p95_latency_ms": round(lat_sorted[int(len(lat_sorted)*0.95)], 1),
        "gpu_before": gpu_before,
        "gpu_after": gpu_after,
    }


def run_concurrent(vllm_url: str, model: str, batch_size: int, n: int = 10) -> dict:
    """Run n requests with batch_size concurrent workers."""
    latencies = []
    total_tokens = 0
    prompts = (BENCHMARK_PROMPTS * (n // len(BENCHMARK_PROMPTS) + 1))[:n]

    t_start = time.time()
    gpu_before = get_gpu_stats()

    with ThreadPoolExecutor(max_workers=batch_size) as executor:
        futures = {executor.submit(call_vllm_single, vllm_url, model, p): p for p in prompts}
        for future in as_completed(futures):
            tokens, lat, _ = future.result()
            latencies.append(lat)
            total_tokens += tokens

    t_total = time.time() - t_start
    gpu_after = get_gpu_stats()

    lat_sorted = sorted(latencies)
    return {
        "mode": f"concurrent_batch_{batch_size}",
        "requests": n,
        "batch_size": batch_size,
        "total_tokens": total_tokens,
        "total_time_s": round(t_total, 2),
        "tokens_per_second": round(total_tokens / t_total, 1) if t_total > 0 else 0,
        "avg_latency_ms": round(statistics.mean(latencies), 1),
        "p50_latency_ms": round(lat_sorted[len(lat_sorted)//2], 1),
        "p95_latency_ms": round(lat_sorted[int(len(lat_sorted)*0.95)], 1),
        "gpu_before": gpu_before,
        "gpu_after": gpu_after,
    }


def main():
    parser = argparse.ArgumentParser(description="vLLM AMD ROCm Performance Benchmark")
    parser.add_argument("--vllm-url", required=True)
    parser.add_argument("--model", default="models/qwen-trader-merged")
    parser.add_argument("--output", default="/workspace/persistent/vllm_benchmark.json")
    args = parser.parse_args()

    results = []

    print("=" * 70)
    print("  vLLM AMD ROCm Performance Benchmark")
    print("=" * 70)
    print()

    # GPU info
    gpu_info = get_gpu_stats()
    if gpu_info:
        print(f"  GPU VRAM: {gpu_info.get('vram_used_mb', 0)} / {gpu_info.get('vram_total_mb', 0)} MB")
    print()

    # Sequential (batch=1)
    print("  Running sequential (batch=1, 10 requests)...")
    seq_result = run_sequential(args.vllm_url, args.model, n=10)
    results.append(seq_result)
    print(f"    tokens/s: {seq_result['tokens_per_second']}, avg_lat: {seq_result['avg_latency_ms']:.0f}ms, p95: {seq_result['p95_latency_ms']:.0f}ms")
    print()

    # Concurrent batches
    for batch in [2, 4, 8, 16]:
        print(f"  Running concurrent batch={batch} (10 requests)...")
        conc_result = run_concurrent(args.vllm_url, args.model, batch_size=batch, n=10)
        results.append(conc_result)
        print(f"    tokens/s: {conc_result['tokens_per_second']}, avg_lat: {conc_result['avg_latency_ms']:.0f}ms, p95: {conc_result['p95_latency_ms']:.0f}ms")
        print()

    # Summary table
    print("=" * 70)
    print("  Performance Summary")
    print("=" * 70)
    print(f"  {'Mode':<25} {'tokens/s':>10} {'avg ms':>10} {'p95 ms':>10} {'VRAM MB':>10}")
    print("  " + "-" * 65)
    for r in results:
        vram = r.get("gpu_after", {}).get("vram_used_mb", 0)
        print(f"  {r['mode']:<25} {r['tokens_per_second']:>10.1f} {r['avg_latency_ms']:>10.0f} {r['p95_latency_ms']:>10.0f} {vram:>10}")
    print()

    # Save
    with open(args.output, "w") as f:
        json.dump(results, f, indent=2)
    print(f"  Results saved to {args.output}")


if __name__ == "__main__":
    main()
