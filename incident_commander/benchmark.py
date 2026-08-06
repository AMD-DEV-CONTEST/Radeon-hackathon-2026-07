from __future__ import annotations

import argparse
import json
import platform
import statistics
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

from .analyzer import IncidentAnalyzer
from .models import Incident


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark the incident-analysis pipeline")
    parser.add_argument("--input", type=Path, default=Path("samples/checkout-latency.json"))
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.iterations < 1:
        parser.error("--iterations must be at least 1")

    incident = Incident.from_dict(json.loads(args.input.read_text(encoding="utf-8")))
    analyzer = IncidentAnalyzer()
    samples: list[float] = []
    for _ in range(args.iterations):
        started = perf_counter()
        analyzer.analyze(incident)
        samples.append((perf_counter() - started) * 1000)

    ordered = sorted(samples)
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "engine": "deterministic-baseline",
        "system": {"platform": platform.platform(), "python": platform.python_version()},
        "input": str(args.input),
        "iterations": args.iterations,
        "latency_ms": {
            "min": round(min(samples), 4),
            "mean": round(statistics.mean(samples), 4),
            "p50": round(statistics.median(samples), 4),
            "p95": round(ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))], 4),
            "max": round(max(samples), 4),
        },
        "gpu": {"model": None, "rocm_version": None, "measured": False},
    }
    rendered = json.dumps(payload, indent=2)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
