#!/usr/bin/env python3
"""Probe an OpenAI-compatible model endpoint before spending SWE-bench calls.

Credentials are read from ``TRACK2_API_KEY`` (or ``OPENAI_API_KEY``) and are
never written to the output.  The structured-output probe is intentionally a
real request using vLLM's current ``structured_outputs`` body; a successful
ordinary JSON response is not mislabeled as constrained decoding.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from swe_experiments.api import APIConfig, APIProbe


def _sizes(value: str) -> list[int]:
    try:
        result = [int(item.strip()) for item in value.split(",") if item.strip()]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("context sizes must be comma-separated integers") from exc
    if any(item <= 0 for item in result):
        raise argparse.ArgumentTypeError("context sizes must be positive")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base_url", default=None, help="Defaults to TRACK2_BASE_URL or OPENAI_BASE_URL")
    parser.add_argument("--api_key", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--model", default=None, help="Defaults to TRACK2_MODEL")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--no_models", action="store_true", help="Skip the /models capability probe")
    parser.add_argument(
        "--context_sizes",
        type=_sizes,
        default=[],
        help="Optional approximate context sizes, e.g. 4096,8192 (each costs one tiny request)",
    )
    args = parser.parse_args()

    config = APIConfig.from_env(
        base_url=args.base_url,
        api_key=args.api_key,
        model=args.model,
        timeout=args.timeout,
    )
    report = APIProbe(config).run(
        include_models=not args.no_models,
        context_sizes=args.context_sizes,
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
