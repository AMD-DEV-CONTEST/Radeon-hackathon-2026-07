#!/usr/bin/env python3
"""Verify that vLLM/Qwen emits a parseable, inert structured tool proposal."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    parser.add_argument("--model", default="Qwen2.5-14B-Instruct")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument(
        "--tool-choice",
        choices=("auto", "named"),
        default="auto",
        help="Use auto for the E1 Hermes gate; named is only a lower-level diagnostic.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    parsed_base = urllib.parse.urlparse(args.base_url)
    if parsed_base.scheme != "http" or parsed_base.hostname not in {
        "127.0.0.1",
        "localhost",
        "::1",
    }:
        print(
            "VLLM_TOOL_CALL_FAILED: E1 evidence must use a localhost HTTP endpoint",
            file=sys.stderr,
        )
        return 2
    asset_id = "fixture-chair-public-complete"
    payload = {
        "model": args.model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You propose tool calls but never execute them. Call the named tool "
                    "once with the supplied asset ID."
                ),
            },
            {
                "role": "user",
                "content": f"Inspect evidence gaps for asset_id={asset_id}.",
            },
        ],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "inspect_evidence_gaps",
                    "description": "Return missing or conflicting support in a local experience asset.",
                    "parameters": {
                        "type": "object",
                        "properties": {"asset_id": {"type": "string"}},
                        "required": ["asset_id"],
                        "additionalProperties": False,
                    },
                },
            }
        ],
        "tool_choice": "auto",
        "temperature": 0,
        "max_tokens": 128,
    }
    if args.tool_choice == "named":
        payload["tool_choice"] = {
            "type": "function",
            "function": {"name": "inspect_evidence_gaps"},
        }
    request = urllib.request.Request(
        f"{args.base_url.rstrip('/')}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer EMPTY"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=args.timeout) as response:
            result = json.load(response)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"VLLM_TOOL_CALL_FAILED: request error: {exc}", file=sys.stderr)
        return 2

    try:
        choice = result["choices"][0]
        if choice["finish_reason"] != "tool_calls":
            raise ValueError(f"unexpected finish_reason={choice['finish_reason']!r}")
        calls = choice["message"]["tool_calls"]
        if not isinstance(calls, list) or len(calls) != 1:
            raise ValueError(f"expected exactly one tool call, got {calls!r}")
        call = calls[0]
        if call.get("type") != "function":
            raise ValueError(f"unexpected tool call type={call.get('type')!r}")
        name = call["function"]["name"]
        raw_arguments = call["function"]["arguments"]
        if not isinstance(raw_arguments, str):
            raise ValueError("function arguments must be a JSON string")
        arguments = json.loads(raw_arguments)
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"VLLM_TOOL_CALL_FAILED: malformed response: {exc}", file=sys.stderr)
        return 1

    if name != "inspect_evidence_gaps" or arguments != {"asset_id": asset_id}:
        print(
            f"VLLM_TOOL_CALL_FAILED: unexpected proposal name={name!r} arguments={arguments!r}",
            file=sys.stderr,
        )
        return 1

    print(
        "VLLM_TOOL_CALL_OK "
        f"proposal_only=true choice={args.tool_choice} tool=inspect_evidence_gaps"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
