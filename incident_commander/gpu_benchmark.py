from __future__ import annotations

import argparse
import json
import platform
import re
import statistics
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .llm import OpenAICompatibleClient, StreamingLLMResult


SYSTEM_PROMPT = "You are an SRE incident commander. Answer concisely using only supplied evidence."


def _run(command: list[str]) -> str | None:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=15, check=False)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    output = (result.stdout or result.stderr).strip()
    return output[:12000] if output else None


def _match(text: str, pattern: str) -> str | None:
    found = re.search(pattern, text, re.MULTILINE)
    return found.group(1).strip() if found else None


def collect_accelerator_info() -> dict[str, Any]:
    """Return a public-safe hardware manifest, never raw device inventory."""
    rocm_version = _run(["bash", "-lc", "cat /opt/rocm/.info/version 2>/dev/null || hipconfig --version"])
    amd_smi = _run(["amd-smi", "static", "--gpu", "0"]) or ""
    return {
        "measured": bool(rocm_version and amd_smi),
        "vendor": "AMD",
        "device": "Radeon GPU",
        "architecture": _match(amd_smi, r"TARGET_GRAPHICS_VERSION:\s*(\S+)"),
        "vram_mb": _as_int(_match(amd_smi, r"^\s*SIZE:\s*(\d+)\s*MB")),
        "compute_units": _as_int(_match(amd_smi, r"NUM_COMPUTE_UNITS:\s*(\d+)")),
        "driver_version": _match(amd_smi, r"DRIVER:\s*\n\s*NAME:[^\n]*\n\s*VERSION:\s*([^\n]+)"),
        "rocm_version": rocm_version.splitlines()[0] if rocm_version else None,
    }


def _as_int(value: str | None) -> int | None:
    return int(value) if value is not None else None


def percentile(samples: list[float], fraction: float) -> float:
    ordered = sorted(samples)
    return ordered[min(len(ordered) - 1, int(len(ordered) * fraction))]


def summarize(samples: list[float]) -> dict[str, float]:
    return {
        "min": round(min(samples), 2),
        "mean": round(statistics.mean(samples), 2),
        "p50": round(statistics.median(samples), 2),
        "p95": round(percentile(samples, 0.95), 2),
        "max": round(max(samples), 2),
    }


def benchmark(client: OpenAICompatibleClient, prompt: str, iterations: int, max_tokens: int) -> dict[str, Any]:
    results: list[StreamingLLMResult] = []
    for _ in range(iterations):
        results.append(client.stream_complete(SYSTEM_PROMPT, prompt, max_tokens=max_tokens))
    output_rates: list[float] = []
    for result in results:
        output_tokens = result.usage.get("completion_tokens")
        decode_seconds = max((result.latency_ms - result.ttft_ms) / 1000, 0.001)
        if isinstance(output_tokens, (int, float)) and output_tokens > 0:
            output_rates.append(float(output_tokens) / decode_seconds)
    return {
        "model": results[-1].model,
        "iterations": iterations,
        "max_tokens": max_tokens,
        "ttft_ms": summarize([item.ttft_ms for item in results]),
        "end_to_end_ms": summarize([item.latency_ms for item in results]),
        "output_tokens_per_second": summarize(output_rates) if output_rates else None,
        "usage": [item.usage for item in results],
        "sample_output": results[-1].content,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure an OpenAI-compatible model on Radeon/ROCm")
    parser.add_argument("--input", type=Path, default=Path("samples/checkout-latency.json"))
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--max-tokens", type=int, default=160)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.iterations < 1:
        parser.error("--iterations must be at least 1")
    incident = json.loads(args.input.read_text(encoding="utf-8"))
    prompt = json.dumps(incident, ensure_ascii=False)
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "engine": "openai-compatible-streaming",
        "system": {"platform": platform.platform(), "python": platform.python_version()},
        "gpu": collect_accelerator_info(),
        "benchmark": benchmark(OpenAICompatibleClient(), prompt, args.iterations, args.max_tokens),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(payload, indent=2, ensure_ascii=False)
    args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
