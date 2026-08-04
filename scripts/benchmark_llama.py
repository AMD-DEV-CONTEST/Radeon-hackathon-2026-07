#!/usr/bin/env python3
"""Benchmark a self-hosted llama-server with an application-shaped streaming workload."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from xianglens.inference.llama_client import ModelRequestError, parse_json_object

DEFAULT_MODEL = "mradermacher/Qwen3.6-35B-A3B-Fable-5-Distill-i1-GGUF:Q6_K"
DEFAULT_PROMPT = (
    "Return only one compact JSON object with keys summary, risks, and recommendations. "
    "Evaluate a profile image only against the stated communication goal. Never identify a "
    "person or infer personality, health, wealth, politics, religion, protected attributes, or "
    "future outcomes. Goal: credible and approachable for international open-source collaborators."
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Measure XiangLens-shaped llama.cpp latency and structured-output reliability."
    )
    parser.add_argument("--base-url", default=os.getenv("XIANG_LLM_BASE_URL", ""))
    parser.add_argument("--api-key", default=os.getenv("XIANG_LLM_API_KEY", ""))
    parser.add_argument("--model", default=os.getenv("XIANG_LLM_MODEL", DEFAULT_MODEL))
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--image", type=Path)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--max-tokens", type=int, default=384)
    parser.add_argument("--reasoning-budget", type=int, default=2048)
    parser.add_argument("--disable-thinking", action="store_true")
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--pause-seconds", type=float, default=0.5)
    parser.add_argument("--gpu", default="AMD Radeon PRO W7900")
    parser.add_argument("--rocm-version", default="record-on-radeon-host")
    parser.add_argument("--llama-cpp-commit", default="record-on-radeon-host")
    parser.add_argument("--server-command", default="record-the-exact-launch-command")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path)
    args = parser.parse_args()
    if not args.base_url.strip():
        parser.error("--base-url or XIANG_LLM_BASE_URL is required")
    if args.runs < 1 or args.warmups < 0:
        parser.error("--runs must be positive and --warmups cannot be negative")
    if args.max_tokens < 1 or args.reasoning_budget < 0:
        parser.error("token budgets must be non-negative and max tokens must be positive")
    if args.image and not args.image.is_file():
        parser.error(f"image does not exist: {args.image}")
    return args


def safe_endpoint(value: str) -> str:
    """Remove credentials, query parameters, and fragments from a recorded endpoint."""
    parsed = urlsplit(value)
    host = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    return urlunsplit((parsed.scheme, host + port, parsed.path.rstrip("/"), "", ""))


def _image_content(image_path: Path, prompt: str) -> list[dict[str, Any]]:
    mime_by_suffix = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }
    mime = mime_by_suffix.get(image_path.suffix.lower())
    if mime is None:
        raise ValueError("benchmark image must be JPEG, PNG, or WebP")
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}},
    ]


def build_payload(args: argparse.Namespace) -> dict[str, Any]:
    user_content: str | list[dict[str, Any]] = args.prompt
    if args.image:
        user_content = _image_content(args.image, args.prompt)
    thinking = not args.disable_thinking
    return {
        "model": args.model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are the self-hosted XiangLens benchmark worker. Return only JSON. "
                    "Follow the privacy boundary in the user request."
                ),
            },
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.0,
        "max_tokens": args.max_tokens + (args.reasoning_budget if thinking else 0),
        "stream": True,
        "stream_options": {"include_usage": True},
        "chat_template_kwargs": {"enable_thinking": thinking},
        "reasoning_budget": args.reasoning_budget if thinking else 0,
    }


def _number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _parse_stream_object(line: str) -> dict[str, Any] | None:
    candidate = line.strip()
    if not candidate:
        return None
    if candidate.startswith("data:"):
        candidate = candidate[5:].strip()
    if candidate == "[DONE]":
        return None
    if not candidate.startswith("{"):
        return None
    value = json.loads(candidate)
    return value if isinstance(value, dict) else None


def run_once(
    client: httpx.Client,
    *,
    base_url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    run_index: int,
) -> dict[str, Any]:
    started = time.perf_counter()
    first_delta_ms: float | None = None
    first_content_ms: float | None = None
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    usage: dict[str, Any] = {}
    timings: dict[str, Any] = {}
    finish_reason: str | None = None

    with client.stream(
        "POST",
        f"{base_url.rstrip('/')}/chat/completions",
        headers=headers,
        json=payload,
    ) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            stream_object = _parse_stream_object(line)
            if stream_object is None:
                continue
            if isinstance(stream_object.get("usage"), dict):
                usage = stream_object["usage"]
            if isinstance(stream_object.get("timings"), dict):
                timings = stream_object["timings"]
            choices = stream_object.get("choices")
            if not isinstance(choices, list) or not choices:
                continue
            choice = choices[0] if isinstance(choices[0], dict) else {}
            if choice.get("finish_reason"):
                finish_reason = str(choice["finish_reason"])
            delta = choice.get("delta")
            if not isinstance(delta, dict):
                delta = choice.get("message") if isinstance(choice.get("message"), dict) else {}
            content = str(delta.get("content") or "")
            reasoning = str(
                delta.get("reasoning_content") or delta.get("reasoning") or ""
            )
            if (content or reasoning) and first_delta_ms is None:
                first_delta_ms = (time.perf_counter() - started) * 1000
            if content and first_content_ms is None:
                first_content_ms = (time.perf_counter() - started) * 1000
            content_parts.append(content)
            reasoning_parts.append(reasoning)

    latency_ms = (time.perf_counter() - started) * 1000
    content = "".join(content_parts).strip()
    reasoning = "".join(reasoning_parts)
    prompt_tokens = _number(usage.get("prompt_tokens")) or _number(timings.get("prompt_n"))
    completion_tokens = _number(usage.get("completion_tokens")) or _number(
        timings.get("predicted_n")
    )
    prompt_tps = _number(timings.get("prompt_per_second"))
    decode_tps = _number(timings.get("predicted_per_second"))
    if decode_tps is None and completion_tokens and first_delta_ms is not None:
        decode_seconds = max((latency_ms - first_delta_ms) / 1000, 0.001)
        decode_tps = completion_tokens / decode_seconds
    try:
        parse_json_object(content)
        valid_json = True
    except ModelRequestError:
        valid_json = False

    return {
        "run": run_index,
        "success": True,
        "finish_reason": finish_reason,
        "time_to_first_delta_ms": round(first_delta_ms, 2) if first_delta_ms else None,
        "time_to_first_content_ms": round(first_content_ms, 2) if first_content_ms else None,
        "total_latency_ms": round(latency_ms, 2),
        "prompt_tokens": int(prompt_tokens) if prompt_tokens is not None else None,
        "completion_tokens": int(completion_tokens) if completion_tokens is not None else None,
        "prompt_tokens_per_second": round(prompt_tps, 2) if prompt_tps else None,
        "decode_tokens_per_second": round(decode_tps, 2) if decode_tps else None,
        "final_content_characters": len(content),
        "reasoning_characters": len(reasoning),
        "valid_json": valid_json,
        "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
    }


def _metric_summary(successful: list[dict[str, Any]], key: str) -> dict[str, float] | None:
    values = [float(run[key]) for run in successful if run.get(key) is not None]
    if not values:
        return None
    return {
        "median": round(statistics.median(values), 2),
        "mean": round(statistics.fmean(values), 2),
        "min": round(min(values), 2),
        "max": round(max(values), 2),
    }


def summarize_runs(runs: list[dict[str, Any]]) -> dict[str, Any]:
    successful = [run for run in runs if run.get("success")]
    return {
        "attempted_runs": len(runs),
        "successful_runs": len(successful),
        "structured_json_success_rate": (
            round(sum(bool(run.get("valid_json")) for run in successful) / len(successful), 4)
            if successful
            else 0.0
        ),
        "time_to_first_delta_ms": _metric_summary(successful, "time_to_first_delta_ms"),
        "time_to_first_content_ms": _metric_summary(successful, "time_to_first_content_ms"),
        "total_latency_ms": _metric_summary(successful, "total_latency_ms"),
        "prompt_tokens_per_second": _metric_summary(
            successful, "prompt_tokens_per_second"
        ),
        "decode_tokens_per_second": _metric_summary(
            successful, "decode_tokens_per_second"
        ),
    }


def _format_metric(summary: dict[str, Any], key: str, suffix: str) -> str:
    metric = summary.get(key)
    return f"{metric['median']:.2f} {suffix}" if metric else "not reported by server"


def render_markdown(result: dict[str, Any]) -> str:
    summary = result["summary"]
    environment = result["environment"]
    workload = result["workload"]
    lines = [
        "# XiangLens Radeon Benchmark Result",
        "",
        f"- Generated: `{result['generated_at_utc']}`",
        f"- Runtime: `{environment['runtime']}`",
        f"- GPU: `{environment['gpu']}`",
        f"- ROCm: `{environment['rocm_version']}`",
        f"- llama.cpp: `{environment['llama_cpp_commit']}`",
        f"- Model: `{workload['model']}`",
        f"- Endpoint: `{result['endpoint']}`",
        f"- Workload: `{'multimodal' if workload['image'] else 'text-only'}`",
        "",
        "## Median Results",
        "",
        "| Metric | Median |",
        "|---|---:|",
        (
            "| Time to first generated delta | "
            f"{_format_metric(summary, 'time_to_first_delta_ms', 'ms')} |"
        ),
        (
            "| Time to first final-content delta | "
            f"{_format_metric(summary, 'time_to_first_content_ms', 'ms')} |"
        ),
        f"| End-to-end model latency | {_format_metric(summary, 'total_latency_ms', 'ms')} |",
        (
            "| Prompt processing | "
            f"{_format_metric(summary, 'prompt_tokens_per_second', 'tok/s')} |"
        ),
        (
            "| Token generation | "
            f"{_format_metric(summary, 'decode_tokens_per_second', 'tok/s')} |"
        ),
        (
            "| Valid structured JSON | "
            f"{summary['structured_json_success_rate'] * 100:.1f}% |"
        ),
        "",
        "## Method",
        "",
        f"- Warmups excluded: `{result['warmups']}`",
        f"- Measured runs: `{summary['attempted_runs']}`",
        f"- Temperature: `{workload['temperature']}`",
        f"- Final-content budget: `{workload['max_tokens']}` tokens",
        f"- Reasoning budget: `{workload['reasoning_budget']}` tokens",
        "- Raw model content and chain-of-thought were not written to the result file.",
        "- Peak VRAM and GPU utilization must be captured separately with ROCm tooling.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    payload = build_payload(args)
    headers = {"Content-Type": "application/json"}
    if args.api_key:
        headers["Authorization"] = f"Bearer {args.api_key}"
    timeout = httpx.Timeout(args.timeout)
    runs: list[dict[str, Any]] = []

    with httpx.Client(timeout=timeout) as client:
        for warmup_index in range(args.warmups):
            print(f"Warmup {warmup_index + 1}/{args.warmups}")
            run_once(
                client,
                base_url=args.base_url,
                headers=headers,
                payload=payload,
                run_index=0,
            )
        for run_index in range(1, args.runs + 1):
            print(f"Measured run {run_index}/{args.runs}")
            try:
                run = run_once(
                    client,
                    base_url=args.base_url,
                    headers=headers,
                    payload=payload,
                    run_index=run_index,
                )
            except (httpx.HTTPError, json.JSONDecodeError, ValueError) as exc:
                run = {"run": run_index, "success": False, "error": str(exc)[:500]}
            runs.append(run)
            if args.pause_seconds and run_index != args.runs:
                time.sleep(args.pause_seconds)

    image_metadata = None
    if args.image:
        image_metadata = {
            "name": args.image.name,
            "sha256": hashlib.sha256(args.image.read_bytes()).hexdigest(),
        }
    result = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "endpoint": safe_endpoint(args.base_url),
        "environment": {
            "runtime": "llama.cpp llama-server on AMD ROCm",
            "gpu": args.gpu,
            "rocm_version": args.rocm_version,
            "llama_cpp_commit": args.llama_cpp_commit,
            "server_command": args.server_command,
        },
        "workload": {
            "model": args.model,
            "prompt": args.prompt,
            "image": image_metadata,
            "temperature": payload["temperature"],
            "max_tokens": args.max_tokens,
            "reasoning_budget": payload["reasoning_budget"],
            "thinking_enabled": not args.disable_thinking,
        },
        "warmups": args.warmups,
        "runs": runs,
        "summary": summarize_runs(runs),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    markdown_output = args.markdown_output
    if markdown_output:
        markdown_output.parent.mkdir(parents=True, exist_ok=True)
        markdown_output.write_text(render_markdown(result))
    print(json.dumps(result["summary"], indent=2))
    print(f"Wrote {args.output}")
    if markdown_output:
        print(f"Wrote {markdown_output}")
    if result["summary"]["successful_runs"] != args.runs:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
