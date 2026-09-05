#!/usr/bin/env python3
"""Bounded text worker for AMD's OpenAI-compatible DeepSeek endpoint.

This intentionally has no file, shell, Git, or network tools beyond the single
configured model request. It is the compatibility fallback when Codex CLI tool
calling is unavailable or unreliable with the provider.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


DEFAULT_BASE_URL = "https://developer.amd.com.cn/radeon/api/v1"
DEFAULT_MODEL = "DeepSeek-V4-Flash"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("task", nargs="?", help="Small, self-contained task")
    parser.add_argument("--task-file", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--base-url", default=os.getenv("AMD_MODEL_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--model", default=os.getenv("AMD_MODEL_NAME", DEFAULT_MODEL))
    parser.add_argument("--max-tokens", type=int, default=1200)
    parser.add_argument("--temperature", type=float, default=0.1)
    return parser.parse_args()


def load_task(args: argparse.Namespace) -> str:
    if bool(args.task) == bool(args.task_file):
        raise SystemExit("Provide exactly one of TASK or --task-file.")
    if args.task_file:
        return args.task_file.read_text(encoding="utf-8").strip()
    return args.task.strip()


def main() -> int:
    args = parse_args()
    api_key = os.getenv("AMD_MODEL_API_KEY")
    if not api_key:
        print("ERROR: AMD_MODEL_API_KEY is not set in this shell.", file=sys.stderr)
        return 2

    task = load_task(args)
    system = (
        "You are a bounded development worker. Complete only the explicit task. "
        "Do not claim to run commands, edit files, commit, push, or access secrets. "
        "Return a concise result that a primary coding agent can verify. If code "
        "changes are requested, return a minimal unified diff or exact edit plan."
    )
    payload = {
        "model": args.model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": task},
        ],
        "temperature": args.temperature,
        "max_tokens": args.max_tokens,
    }
    request = urllib.request.Request(
        f"{args.base_url.rstrip('/')}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            body = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1000]
        print(f"ERROR: model API returned HTTP {exc.code}: {detail}", file=sys.stderr)
        return 1
    except (urllib.error.URLError, TimeoutError) as exc:
        print(f"ERROR: model API request failed: {exc}", file=sys.stderr)
        return 1

    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        print("ERROR: unexpected model response shape.", file=sys.stderr)
        return 1

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content.rstrip() + "\n", encoding="utf-8")
        print(f"Worker result written to {args.output}")
    else:
        print(content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
