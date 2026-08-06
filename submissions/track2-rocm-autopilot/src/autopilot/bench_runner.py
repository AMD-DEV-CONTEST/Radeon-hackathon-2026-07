"""Benchmark the live deployment with `vllm bench serve` and annotate with energy.

One entry point: run_benchmark(config, base_url) -> RunResult dict.
Every RunResult documents hardware, model variant, precision and
concurrency: required for reproducible benchmark claims.
"""

from __future__ import annotations

import os
import re
import subprocess
import time

from autopilot.power import EnergyMeter, hardware_info

MODEL = os.environ.get("BENCH_MODEL", "google/gemma-4-26B-A4B-it")
PRECISION = os.environ.get("BENCH_PRECISION", "bf16")
DATASET = os.environ.get("BENCH_DATASET", "datasets/confidential_drafting.jsonl")
NUM_PROMPTS = int(os.environ.get("BENCH_NUM_PROMPTS", "30"))

# Patterns for the `vllm bench serve` summary block. Verified against the
# live output on the box; keep permissive on whitespace/wording drift.
_PATTERNS = {
    "tokens_per_s": re.compile(r"Output token throughput \(tok/s\):\s+([\d.]+)"),
    "ttft_ms": re.compile(r"Mean TTFT \(ms\):\s+([\d.]+)"),
    "itl_ms": re.compile(r"Mean ITL \(ms\):\s+([\d.]+)"),
    "total_output_tokens": re.compile(r"Total generated tokens:\s+(\d+)"),
}


def parse_bench_output(text: str) -> dict:
    out: dict = {}
    for key, pat in _PATTERNS.items():
        m = pat.search(text)
        if m:
            out[key] = float(m.group(1))
    missing = {"tokens_per_s", "ttft_ms"} - set(out)
    if missing:
        raise ValueError(f"could not parse {missing} from bench output; tail:\n{text[-800:]}")
    out.setdefault("itl_ms", 0.0)
    return out


def run_benchmark(config: dict, base_url: str = "http://localhost:8000") -> dict:
    cmd = [
        "vllm", "bench", "serve",
        "--backend", "openai-chat",
        "--base-url", base_url,
        "--endpoint", "/v1/chat/completions",
        "--model", MODEL,
        "--dataset-name", "custom",
        "--dataset-path", DATASET,
        "--num-prompts", str(NUM_PROMPTS),
        "--max-concurrency", str(config["concurrency"]),
    ]
    with EnergyMeter() as meter:
        t0 = time.monotonic()
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        elapsed = time.monotonic() - t0
    text = proc.stdout + proc.stderr
    if proc.returncode != 0:
        return {"error": f"bench failed (rc={proc.returncode}): {text[-600:]}"}

    metrics = parse_bench_output(text)
    total_tokens = metrics.pop("total_output_tokens", 0) or metrics["tokens_per_s"] * elapsed
    joules_per_token = meter.joules / total_tokens if total_tokens else 0.0

    return {
        "config": {
            "model": MODEL,
            "precision": PRECISION,
            "max_num_seqs": config.get("max_num_seqs"),
            "enable_prefix_caching": config.get("enable_prefix_caching"),
            "power_cap_w": config.get("power_cap_w"),
            "concurrency": config["concurrency"],
        },
        "hardware": hardware_info(),
        "metrics": {
            "tokens_per_s": metrics["tokens_per_s"],
            "ttft_ms": metrics["ttft_ms"],
            "itl_ms": metrics["itl_ms"],
        },
        "energy": {
            "joules": round(meter.joules, 1),
            "joules_per_token": round(joules_per_token, 4),
            "mean_power_w": round(meter.mean_power_w, 1),
            "method": meter.method,
        },
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


if __name__ == "__main__":
    result = run_benchmark({"max_num_seqs": 256, "enable_prefix_caching": True, "concurrency": 8})
    import json
    print(json.dumps(result, indent=1))
