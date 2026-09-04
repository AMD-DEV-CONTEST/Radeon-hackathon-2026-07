#!/usr/bin/env python3
"""Measure streaming TTFT, latency, throughput, and request success."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.policy.local_only import (  # noqa: E402
    local_api_url,
    require_local_vllm_base_url,
)


def get_model() -> str:
    request = urllib.request.Request(local_api_url("/models"), method="GET")
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    models = payload.get("data") or []
    if not models:
        raise RuntimeError("/v1/models returned no models")
    return str(models[0]["id"])


def one_request(index: int, model: str, max_tokens: int, timeout: int) -> dict[str, Any]:
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是本地交通事故证据分析助手。只依据输入事实，不猜测。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"请求编号 {index}：列出机动车与两轮车辆事故分析时"
                    "必须区分的三个结论层级，每项一句话。"
                ),
            },
        ],
        "temperature": 0,
        "max_tokens": max_tokens,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    request = urllib.request.Request(
        local_api_url("/chat/completions"),
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )

    started = time.perf_counter()
    first_token_at: float | None = None
    output_parts: list[str] = []
    usage: dict[str, Any] = {}
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                chunk = json.loads(data)
                if chunk.get("usage"):
                    usage = chunk["usage"]
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                content = choices[0].get("delta", {}).get("content")
                if content:
                    if first_token_at is None:
                        first_token_at = time.perf_counter()
                    output_parts.append(content)
        finished = time.perf_counter()
    except Exception as exc:  # noqa: BLE001 - benchmark must record failures
        return {
            "index": index,
            "status": "failed",
            "error": repr(exc),
            "e2e_seconds": time.perf_counter() - started,
        }

    text = "".join(output_parts)
    completion_tokens = usage.get("completion_tokens")
    decode_seconds = (
        finished - first_token_at if first_token_at is not None else None
    )
    tokens_per_second = (
        completion_tokens / decode_seconds
        if completion_tokens and decode_seconds and decode_seconds > 0
        else None
    )
    return {
        "index": index,
        "status": "passed",
        "ttft_seconds": (
            first_token_at - started if first_token_at is not None else None
        ),
        "e2e_seconds": finished - started,
        "decode_seconds": decode_seconds,
        "completion_tokens": completion_tokens,
        "prompt_tokens": usage.get("prompt_tokens"),
        "tokens_per_second": tokens_per_second,
        "output_characters": len(text),
        "output_preview": text[:240],
    }


def percentile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(0, math.ceil(probability * len(ordered)) - 1)
    return ordered[rank]


def metric_summary(results: list[dict[str, Any]], key: str) -> dict[str, float | None]:
    values = [
        float(result[key])
        for result in results
        if result.get("status") == "passed" and result.get(key) is not None
    ]
    return {
        "count": len(values),
        "mean": sum(values) / len(values) if values else None,
        "p50": percentile(values, 0.50),
        "p95": percentile(values, 0.95),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--requests", type=int, default=20)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--max-tokens", type=int, default=192)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--skip-warmup", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=Path("benchmarks/reports"))
    args = parser.parse_args()
    if args.requests < 1 or args.concurrency < 1:
        parser.error("--requests and --concurrency must be positive")

    endpoint = require_local_vllm_base_url()
    model = get_model()
    if not args.skip_warmup:
        warmup = one_request(-1, model, min(args.max_tokens, 64), args.timeout)
        if warmup["status"] != "passed":
            raise SystemExit(f"Warmup failed: {warmup}")

    benchmark_started = datetime.now(timezone.utc)
    wall_started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=args.concurrency
    ) as executor:
        futures = [
            executor.submit(one_request, index, model, args.max_tokens, args.timeout)
            for index in range(args.requests)
        ]
        results = [future.result() for future in futures]
    wall_seconds = time.perf_counter() - wall_started

    passed = sum(result["status"] == "passed" for result in results)
    report = {
        "schema_version": 1,
        "kind": "baseline",
        "started_at_utc": benchmark_started.isoformat(),
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "endpoint": endpoint,
        "model": model,
        "configuration": {
            "requests": args.requests,
            "concurrency": args.concurrency,
            "max_tokens": args.max_tokens,
            "temperature": 0,
            "stream": True,
            "warmup": not args.skip_warmup,
        },
        "summary": {
            "passed": passed,
            "failed": args.requests - passed,
            "success_rate": passed / args.requests,
            "wall_seconds": wall_seconds,
            "requests_per_second": passed / wall_seconds if wall_seconds else None,
            "ttft_seconds": metric_summary(results, "ttft_seconds"),
            "e2e_seconds": metric_summary(results, "e2e_seconds"),
            "tokens_per_second": metric_summary(results, "tokens_per_second"),
        },
        "requests": results,
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = args.output_dir / (
        f"baseline-{benchmark_started.strftime('%Y%m%dT%H%M%SZ')}"
        f"-c{args.concurrency}.json"
    )
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"Saved benchmark: {output.resolve()}")
    return 0 if passed == args.requests else 1


if __name__ == "__main__":
    raise SystemExit(main())
