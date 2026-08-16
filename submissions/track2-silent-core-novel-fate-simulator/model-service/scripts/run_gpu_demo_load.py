#!/usr/bin/env python3
"""Generate a short, safe mixed LLM and image load for Radeon monitoring."""

from __future__ import annotations

import concurrent.futures
import json
import os
import time

import requests


def run_llm(index: int) -> dict:
    started = time.perf_counter()
    response = requests.post(
        "http://127.0.0.1:8001/v1/chat/completions",
        headers={"Authorization": f"Bearer {os.environ['SILENT_CORE_INTERNAL_API_KEY']}"},
        json={
            "model": "silent-core/llm",
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "Write a long, continuous English fantasy battle scene with "
                        "detailed action and dialogue. Continue until the output limit. "
                        f"This is parallel demo stream {index}."
                    ),
                }
            ],
            "temperature": 0.9,
            "max_tokens": 1536,
            "stream": False,
            "chat_template_kwargs": {"enable_thinking": False},
        },
        timeout=180,
    )
    response.raise_for_status()
    body = response.json()
    return {
        "kind": f"llm-{index}",
        "seconds": round(time.perf_counter() - started, 3),
        "completion_tokens": body.get("usage", {}).get("completion_tokens"),
    }


def run_image() -> dict:
    started = time.perf_counter()
    response = requests.post(
        "http://127.0.0.1:8002/v1/images/generations",
        json={
            "model": "silent-core/image",
            "prompt": (
                "A cinematic fantasy city above a sleeping dragon, moonlight, "
                "dramatic clouds, visual novel background, detailed lighting"
            ),
            "size": "1024x1536",
            "n": 1,
            "response_format": "url",
            "seed": 2026,
        },
        timeout=360,
    )
    response.raise_for_status()
    return {
        "kind": "image",
        "seconds": round(time.perf_counter() - started, 3),
        "result_count": len(response.json().get("data", [])),
    }


def main() -> None:
    started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(run_llm, 1), pool.submit(run_llm, 2), pool.submit(run_image)]
        results = [future.result() for future in concurrent.futures.as_completed(futures)]
    print(
        json.dumps(
            {"total_seconds": round(time.perf_counter() - started, 3), "results": results},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
