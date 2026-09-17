from __future__ import annotations

import argparse
import json
import statistics
import time

import httpx


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark a local ROCm-backed OpenAI-compatible endpoint.")
    parser.add_argument("--url", default="http://127.0.0.1:8080/v1")
    parser.add_argument("--model", default="qwen2.5-7b-instruct")
    parser.add_argument("--runs", type=int, default=5)
    args = parser.parse_args()

    durations: list[float] = []
    outputs: list[int] = []
    for _ in range(args.runs):
        started = time.perf_counter()
        response = httpx.post(
            f"{args.url.rstrip('/')}/chat/completions",
            json={
                "model": args.model,
                "temperature": 0,
                "max_tokens": 128,
                "messages": [{"role": "user", "content": "List three privacy risks in a public document release."}],
            },
            timeout=120,
        )
        response.raise_for_status()
        durations.append(time.perf_counter() - started)
        outputs.append(len(response.json()["choices"][0]["message"]["content"]))

    print(
        json.dumps(
            {
                "runs": args.runs,
                "latency_seconds": {
                    "mean": round(statistics.mean(durations), 4),
                    "median": round(statistics.median(durations), 4),
                    "min": round(min(durations), 4),
                    "max": round(max(durations), 4),
                },
                "output_characters_mean": round(statistics.mean(outputs), 1),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

