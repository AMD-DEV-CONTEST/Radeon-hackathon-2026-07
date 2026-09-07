#!/usr/bin/env python3
"""Measure streaming TTFT and decode throughput for an OpenAI chat endpoint."""

from __future__ import annotations

import argparse
import json
import os
import statistics
import time

import requests


def run_trial(base_url: str, api_key: str, model: str, max_tokens: int) -> dict:
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": (
                    "Write a continuous English fantasy scene about a city built above "
                    "a sleeping dragon. Use vivid but concise prose and do not use headings."
                ),
            }
        ],
        "temperature": 0.8,
        "top_p": 0.95,
        "max_tokens": max_tokens,
        "stream": True,
        "stream_options": {"include_usage": True},
        "chat_template_kwargs": {"enable_thinking": False},
    }
    started = time.perf_counter()
    first_token_at = None
    completion_tokens = 0
    content = []
    with requests.post(
        f"{base_url.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json=payload,
        stream=True,
        timeout=(10, 180),
    ) as response:
        response.raise_for_status()
        for raw_line in response.iter_lines():
            if not raw_line.startswith(b"data: "):
                continue
            encoded = raw_line[6:]
            if encoded == b"[DONE]":
                break
            event = json.loads(encoded)
            if usage := event.get("usage"):
                completion_tokens = usage.get("completion_tokens", completion_tokens)
            for choice in event.get("choices", []):
                delta = choice.get("delta", {})
                text = delta.get("content") or ""
                if text:
                    if first_token_at is None:
                        first_token_at = time.perf_counter()
                    content.append(text)
    finished = time.perf_counter()
    if first_token_at is None:
        raise RuntimeError("No content token received")
    ttft = first_token_at - started
    decode_seconds = max(finished - first_token_at, 1e-9)
    return {
        "ttft_seconds": round(ttft, 4),
        "total_seconds": round(finished - started, 4),
        "completion_tokens": completion_tokens,
        "decode_tokens_per_second": round(completion_tokens / decode_seconds, 2),
        "characters": len("".join(content)),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8001/v1")
    parser.add_argument("--api-key", default=os.getenv("SILENT_CORE_INTERNAL_API_KEY", ""))
    parser.add_argument("--model", default="silent-core/llm")
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--max-tokens", type=int, default=256)
    parser.add_argument("--output")
    args = parser.parse_args()
    if not args.api_key:
        raise SystemExit("Set SILENT_CORE_INTERNAL_API_KEY or pass --api-key")

    trials = [
        run_trial(args.base_url, args.api_key, args.model, args.max_tokens)
        for _ in range(args.trials)
    ]
    result = {
        "base_url": args.base_url,
        "model": args.model,
        "trials": trials,
        "median_ttft_seconds": round(statistics.median(t["ttft_seconds"] for t in trials), 4),
        "median_decode_tokens_per_second": round(
            statistics.median(t["decode_tokens_per_second"] for t in trials), 2
        ),
    }
    rendered = json.dumps(result, indent=2)
    print(rendered)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(rendered + "\n")


if __name__ == "__main__":
    main()
