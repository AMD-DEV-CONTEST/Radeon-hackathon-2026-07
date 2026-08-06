#!/usr/bin/env python3
"""
Benchmark script for the local ROCm/vLLM inference engine.

Run against a live vLLM server (see docs/ROCM_SETUP.md for the launch command):

    python benchmarks/benchmark_inference.py --concurrency 1 4 8 16 --prompt-tokens 512 --output-tokens 256

For each concurrency level, this script:
  1. Fires N concurrent chat-completion requests of a fixed prompt/output size.
  2. Records end-to-end latency and tokens/sec per request via the inference client.
  3. Samples `rocm-smi` for GPU utilization % and VRAM used (MiB) during the run,
     if rocm-smi is available on PATH (falls back to "unavailable" on non-AMD hosts,
     e.g. this development sandbox — this script's numbers must come from a real
     ROCm host to be meaningful for the hackathon benchmark report).
  4. Writes a JSON report to benchmarks/results/<timestamp>.json and prints a
     human-readable summary table.
"""
import argparse
import asyncio
import json
import shutil
import statistics
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.inference.client import InferenceClient  # noqa: E402

BENCH_SYSTEM_PROMPT = "You are a helpful assistant. Answer concisely."


@dataclass
class RequestResult:
    duration_ms: float
    prompt_tokens: int
    completion_tokens: int
    tokens_per_second: float


@dataclass
class GpuSample:
    utilization_pct: float | None
    vram_used_mib: float | None
    available: bool


def sample_gpu() -> GpuSample:
    if shutil.which("rocm-smi") is None:
        return GpuSample(utilization_pct=None, vram_used_mib=None, available=False)
    try:
        out = subprocess.check_output(
            ["rocm-smi", "--showuse", "--showmeminfo", "vram", "--json"], text=True, timeout=5
        )
        data = json.loads(out)
        card = next(iter(data.values()))
        util = float(card.get("GPU use (%)", 0))
        vram = float(card.get("GPU Memory Use (%)", 0))
        return GpuSample(utilization_pct=util, vram_used_mib=vram, available=True)
    except Exception:
        return GpuSample(utilization_pct=None, vram_used_mib=None, available=False)


async def run_single_request(client: InferenceClient, prompt: str, max_tokens: int) -> RequestResult:
    result = await client.complete(system_prompt=BENCH_SYSTEM_PROMPT, user_prompt=prompt, max_tokens=max_tokens)
    return RequestResult(
        duration_ms=result.duration_ms,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
        tokens_per_second=result.tokens_per_second,
    )


async def run_concurrency_level(client: InferenceClient, concurrency: int, prompt: str, max_tokens: int) -> dict:
    gpu_before = sample_gpu()
    start = time.perf_counter()
    tasks = [run_single_request(client, prompt, max_tokens) for _ in range(concurrency)]
    results = await asyncio.gather(*tasks)
    wall_clock_ms = (time.perf_counter() - start) * 1000
    gpu_after = sample_gpu()

    total_completion_tokens = sum(r.completion_tokens for r in results)
    aggregate_tokens_per_second = total_completion_tokens / (wall_clock_ms / 1000) if wall_clock_ms > 0 else 0.0

    return {
        "concurrency": concurrency,
        "wall_clock_ms": round(wall_clock_ms, 2),
        "per_request_latency_ms": {
            "p50": round(statistics.median(r.duration_ms for r in results), 2),
            "p95": round(sorted(r.duration_ms for r in results)[max(0, int(len(results) * 0.95) - 1)], 2),
            "max": round(max(r.duration_ms for r in results), 2),
        },
        "mean_tokens_per_second_per_request": round(statistics.mean(r.tokens_per_second for r in results), 2),
        "aggregate_tokens_per_second": round(aggregate_tokens_per_second, 2),
        "gpu_utilization_pct": gpu_after.utilization_pct,
        "gpu_vram_used_pct": gpu_after.vram_used_mib,
        "gpu_metrics_available": gpu_after.available,
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark the Aegis local ROCm/vLLM inference engine.")
    parser.add_argument("--concurrency", type=int, nargs="+", default=[1, 4, 8])
    parser.add_argument("--output-tokens", type=int, default=256)
    parser.add_argument(
        "--prompt",
        type=str,
        default="Summarize the following log excerpt and identify the most likely root cause: "
        "connection timeout errors spiking at 14:02 UTC on checkout-service, coinciding with "
        "a deploy of commit abc123.",
    )
    args = parser.parse_args()

    client = InferenceClient()
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": client._settings.INFERENCE_MODEL,
        "backend_url": client._settings.INFERENCE_BASE_URL,
        "runs": [],
    }

    for level in args.concurrency:
        print(f"Running concurrency={level} ...")
        try:
            run_result = await run_concurrency_level(client, level, args.prompt, args.output_tokens)
        except Exception as exc:  # noqa: BLE001
            print(f"  FAILED at concurrency={level}: {exc}")
            print("  (Is the vLLM/ROCm server running? See docs/ROCM_SETUP.md)")
            break
        report["runs"].append(run_result)
        print(
            f"  aggregate_tokens/sec={run_result['aggregate_tokens_per_second']} "
            f"p50_latency_ms={run_result['per_request_latency_ms']['p50']} "
            f"gpu_util%={run_result['gpu_utilization_pct']}"
        )

    await client.aclose()

    results_dir = Path(__file__).resolve().parent / "results"
    results_dir.mkdir(exist_ok=True)
    out_path = results_dir / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    out_path.write_text(json.dumps(report, indent=2))
    print(f"\nFull report written to {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
