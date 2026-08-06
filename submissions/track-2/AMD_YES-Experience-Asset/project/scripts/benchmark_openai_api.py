#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import statistics
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import httpx


@dataclass
class Sample:
    iteration: int
    status_code: int
    elapsed_s: float
    output_tokens: int | None
    total_tokens: int | None
    tokens_per_second: float | None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    parser.add_argument("--model", default="Qwen2.5-14B-Instruct")
    parser.add_argument("--api-key", default="EMPTY")
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--max-tokens", type=int, default=256)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    url = f"{args.base_url.rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {args.api_key}"}
    payload = {
        "model": args.model,
        "messages": [
            {
                "role": "user",
                "content": (
                    "Return a concise three-step plan for validating a private "
                    "data-analysis agent. Do not use external services."
                ),
            }
        ],
        "temperature": 0,
        "max_tokens": args.max_tokens,
    }

    samples: list[Sample] = []
    with httpx.Client(timeout=180) as client:
        for iteration in range(1, args.iterations + 1):
            started = time.perf_counter()
            response = client.post(url, headers=headers, json=payload)
            elapsed = time.perf_counter() - started
            response.raise_for_status()
            body = response.json()
            usage = body.get("usage") or {}
            output_tokens = usage.get("completion_tokens")
            total_tokens = usage.get("total_tokens")
            tps = output_tokens / elapsed if output_tokens else None
            samples.append(
                Sample(
                    iteration=iteration,
                    status_code=response.status_code,
                    elapsed_s=round(elapsed, 4),
                    output_tokens=output_tokens,
                    total_tokens=total_tokens,
                    tokens_per_second=round(tps, 3) if tps else None,
                )
            )

    elapsed_values = [sample.elapsed_s for sample in samples]
    report = {
        "model": args.model,
        "base_url": args.base_url,
        "iterations": args.iterations,
        "mean_elapsed_s": round(statistics.mean(elapsed_values), 4),
        "p50_elapsed_s": round(statistics.median(elapsed_values), 4),
        "samples": [asdict(sample) for sample in samples],
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
