from __future__ import annotations

import argparse
import json
import statistics
import time

from openalpha_sentinel.service import OpenAlphaService


QUESTIONS = [
    "What strategies are available and where do they come from?",
    "Compare the disclosed transaction costs for mean reversion and trend following.",
    "Which sources have an explicit open-source license?",
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rounds", type=int, default=3)
    args = parser.parse_args()
    service = OpenAlphaService()
    service.seed_demo()
    latencies = []
    backends = set()
    for round_index in range(args.rounds):
        for question in QUESTIONS:
            started = time.perf_counter()
            response = service.ask(question, f"benchmark-{round_index}")
            latencies.append(time.perf_counter() - started)
            backends.add(response.backend)
    payload = {
        "rounds": args.rounds,
        "requests": len(latencies),
        "backends": sorted(backends),
        "latency_seconds": {
            "mean": statistics.mean(latencies),
            "median": statistics.median(latencies),
            "min": min(latencies),
            "max": max(latencies),
        },
    }
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()

