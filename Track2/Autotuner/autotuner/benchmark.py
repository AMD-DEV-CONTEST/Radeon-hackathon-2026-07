from __future__ import annotations

import json
import math
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Tuple

from autotuner.config import TuneConfig
from autotuner.hardware import TelemetrySampler
from autotuner.models import BenchmarkResult, Candidate


def _percentile(values: List[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = (len(ordered) - 1) * percentile
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[lower]
    fraction = rank - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _request(
    endpoint: str,
    model: str,
    prompt: str,
    max_tokens: int,
) -> Tuple[float, int, str, str]:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0,
        "stream": False,
    }
    request = urllib.request.Request(
        endpoint + "/chat/completions",
        data=json.dumps(payload).encode("utf8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            body = json.loads(response.read().decode("utf8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as error:
        return (time.perf_counter() - started) * 1000, 0, "", str(error)
    latency_ms = (time.perf_counter() - started) * 1000
    try:
        text = str(body["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError):
        text = ""
    usage = body.get("usage", {})
    tokens = int(usage.get("completion_tokens", 0))
    if tokens == 0 and text:
        tokens = max(1, len(text.split()))
    return latency_ms, tokens, text, ""


def run_benchmark(
    config: TuneConfig,
    candidate: Candidate,
    trial_directory: Path,
) -> BenchmarkResult:
    for index in range(config.warmup_requests):
        prompt = config.prompts[index % len(config.prompts)]
        _request(
            config.endpoint,
            candidate.model,
            prompt,
            config.max_tokens,
        )
    sampler = TelemetrySampler()
    sampler.start()
    started = time.perf_counter()
    futures = []
    results: List[Tuple[float, int, str, str]] = []
    with ThreadPoolExecutor(max_workers=config.concurrency) as executor:
        for index in range(config.benchmark_requests):
            prompt = config.prompts[index % len(config.prompts)]
            futures.append(
                executor.submit(
                    _request,
                    config.endpoint,
                    candidate.model,
                    prompt,
                    config.max_tokens,
                )
            )
        for future in as_completed(futures):
            results.append(future.result())
    duration = max(time.perf_counter() - started, 0.000001)
    sampler.stop()
    sampler.write(trial_directory / "telemetry.json")
    latencies = [item[0] for item in results if not item[3]]
    output_tokens = sum(item[1] for item in results)
    responses = [item[2] for item in results if item[2]]
    errors = sum(1 for item in results if item[3])
    quality_hits = 0
    for text in responses:
        lowered = text.lower()
        if text.strip() and all(
            term in lowered for term in config.required_terms
        ):
            quality_hits += 1
    quality_score = quality_hits / max(len(results), 1)
    return BenchmarkResult(
        output_tokens=output_tokens,
        duration_seconds=duration,
        tokens_per_second=output_tokens / duration,
        latency_p50_ms=_percentile(latencies, 0.5),
        latency_p95_ms=_percentile(latencies, 0.95),
        error_rate=errors / max(len(results), 1),
        quality_score=quality_score,
        peak_vram_mb=sampler.peak_vram_mb(),
        responses=responses[:3],
    )
