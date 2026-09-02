#!/usr/bin/env python3
"""Measure one vLLM prefix-cache state with fixed repeated-prefix requests.

Run this script once with ``--prefix-caching off`` and once with ``on`` after
restarting the service with the matching launcher setting.  It does not infer
the server setting; the value is recorded explicitly in the output.
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import time
from pathlib import Path
from typing import Any

from openai import OpenAI


def summary(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"p50_ms": None, "p95_ms": None, "mean_ms": None}
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(0.95 * len(ordered) + 0.999999) - 1))
    return {
        "p50_ms": round(statistics.median(ordered), 2),
        "p95_ms": round(ordered[index], 2),
        "mean_ms": round(statistics.mean(ordered), 2),
    }


def gpu_snapshot() -> dict[str, Any]:
    try:
        result = subprocess.run(
            ["rocm-smi", "--showuse", "--showmeminfo", "vram", "--json"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=10,
            check=False,
        )
        payload = json.loads(result.stdout)
        return next(iter(payload.values()))
    except (FileNotFoundError, subprocess.SubprocessError, json.JSONDecodeError, StopIteration):
        return {"available": False}


def one_request(client: OpenAI, model: str, prompt: str) -> dict[str, Any]:
    started = time.perf_counter()
    first_ms: float | None = None
    output_tokens = 0
    chunks = 0
    stream = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=256,
        temperature=0,
        stream=True,
        stream_options={"include_usage": True},
    )
    for chunk in stream:
        if first_ms is None and getattr(chunk, "choices", None):
            first_ms = (time.perf_counter() - started) * 1000
        chunks += 1
        usage = getattr(chunk, "usage", None)
        if usage is not None:
            output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
    elapsed_ms = (time.perf_counter() - started) * 1000
    decode_ms = max(0.0, elapsed_ms - (first_ms or elapsed_ms))
    return {
        "ok": chunks > 0,
        "ttft_ms": round(first_ms, 2) if first_ms is not None else None,
        "latency_ms": round(elapsed_ms, 2),
        "output_tokens": output_tokens,
        "decode_tokens_per_second": round(output_tokens / (decode_ms / 1000), 2) if decode_ms and output_tokens else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    parser.add_argument("--model", default="Qwen3-14B-BF16")
    parser.add_argument("--api-key", default="local-vllm", help=argparse.SUPPRESS)
    parser.add_argument("--prefix-caching", choices=("on", "off"), required=True)
    parser.add_argument("--warmup", type=int, default=3)
    parser.add_argument("--measurements", type=int, default=10)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.warmup < 0 or args.measurements <= 0:
        parser.error("warmup must be non-negative and measurements must be positive")

    client = OpenAI(base_url=args.base_url, api_key=args.api_key, timeout=180)
    rows: dict[str, Any] = {}
    for input_tokens in (4096, 16384):
        # Repetition makes the prefix deterministic while keeping the prompt
        # human-readable if a request is inspected in a local log.
        prefix = ("Repository context token block. Keep this context stable. " * 2000)[: input_tokens * 4]
        prompt = prefix + f"\n\nReturn one sentence for input-size-{input_tokens}."
        warmup = [one_request(client, args.model, prompt) for _ in range(args.warmup)]
        samples = [one_request(client, args.model, prompt) for _ in range(args.measurements)]
        rows[str(input_tokens)] = {
            "warmup": warmup,
            "samples": samples,
            "ttft": summary([float(row["ttft_ms"]) for row in samples if row.get("ttft_ms") is not None]),
            "latency": summary([float(row["latency_ms"]) for row in samples if row.get("latency_ms") is not None]),
            "decode_tokens_per_second": summary([float(row["decode_tokens_per_second"]) for row in samples if row.get("decode_tokens_per_second") is not None]),
        }
    report = {
        "prefix_caching": args.prefix_caching,
        "model": args.model,
        "base_url": args.base_url,
        "warmup": args.warmup,
        "measurements": args.measurements,
        "gpu_before": gpu_snapshot(),
        "inputs": rows,
        "gpu_after": gpu_snapshot(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"output": str(args.output), "prefix_caching": args.prefix_caching}))


if __name__ == "__main__":
    main()
