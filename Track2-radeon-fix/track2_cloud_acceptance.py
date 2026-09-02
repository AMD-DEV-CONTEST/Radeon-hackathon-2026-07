#!/usr/bin/env python3
"""Run the bounded AMD-local-vLLM service acceptance gate.

This is intentionally separate from SWE-bench.  A service must pass all three
gates before an agent run is allowed to consume benchmark tasks:

* 10 semantic tool calls;
* 20 xgrammar/structured-output action envelopes;
* 30 sequential ordinary requests.

The report contains timing and usage counters but never the API key or full
model responses.  A structured-output response is only accepted when it also
passes the local action-envelope validator; prompt-only JSON is not counted.
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import time
from pathlib import Path
from typing import Any

from swe_experiments.actions import ActionEnvelope, ActionParseError, ACTION_SCHEMA, parse_json_object
from swe_experiments.api import APIConfig, APIProbe, extract_usage, redact_secret, redact_base_url


def _get(value: Any, name: str, default: Any = None) -> Any:
    if value is None:
        return default
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _message(response: Any) -> Any:
    choices = _get(response, "choices", []) or []
    return _get(choices[0], "message", {}) if choices else {}


def _latency_summary(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"p50_ms": None, "p95_ms": None, "mean_ms": None}
    ordered = sorted(values)
    # nearest-rank percentile is deterministic and avoids a dependency on a
    # particular statistics.quantiles implementation.
    p95_index = min(len(ordered) - 1, max(0, int(0.95 * len(ordered) + 0.999999) - 1))
    return {
        "p50_ms": round(statistics.median(ordered), 2),
        "p95_ms": round(ordered[p95_index], 2),
        "mean_ms": round(statistics.mean(ordered), 2),
    }


def _tool_case(probe: APIProbe, index: int) -> tuple[dict[str, Any], float]:
    tool = {
        "type": "function",
        "function": {
            "name": "track2_acceptance",
            "description": "Return the supplied acceptance marker.",
            "parameters": {
                "type": "object",
                "properties": {"marker": {"type": "string"}},
                "required": ["marker"],
                "additionalProperties": False,
            },
        },
    }
    response, elapsed = probe._chat(
        messages=[
            {"role": "system", "content": "Use the requested tool exactly once."},
            {"role": "user", "content": f"Call track2_acceptance with marker=case-{index}. /no_think"},
        ],
        tools=[tool],
        tool_choice={"type": "function", "function": {"name": "track2_acceptance"}},
        max_tokens=64,
        temperature=0,
    )
    message = _message(response)
    calls = _get(message, "tool_calls", []) or []
    valid = False
    if calls:
        function = _get(calls[0], "function", {})
        name = _get(function, "name", "")
        raw_args = _get(function, "arguments", "")
        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            valid = name == "track2_acceptance" and args.get("marker") == f"case-{index}"
        except (TypeError, ValueError):
            valid = False
    return {
        "ok": valid,
        "tool_call_count": len(calls),
        "usage": extract_usage(response),
        "latency_ms": round(elapsed, 2),
    }, elapsed


def _structured_case(probe: APIProbe, index: int) -> tuple[dict[str, Any], float]:
    response, elapsed = probe._chat(
        messages=[
            {
                "role": "user",
                "content": (
                    "Return a finish action envelope for acceptance case "
                    f"{index}; use null for path, query, command, and patch; "
                    "use a short reason; do not add prose. /no_think"
                ),
            }
        ],
        # The envelope itself is short, but Qwen3 may emit a brief reasoning
        # marker before the constrained payload; leave enough room to avoid a
        # false truncation at the acceptance boundary.
        max_tokens=1024,
        temperature=0,
        extra_body={"structured_outputs": {"json": ACTION_SCHEMA}},
    )
    content = str(_get(_message(response), "content", "") or "")
    valid = False
    error = None
    try:
        action = ActionEnvelope.from_mapping(parse_json_object(content))
        valid = action.action == "finish"
    except (ActionParseError, TypeError, ValueError) as exc:
        error = str(exc)
    result: dict[str, Any] = {
        "ok": valid,
        "usage": extract_usage(response),
        "latency_ms": round(elapsed, 2),
    }
    if error:
        result["error"] = error[:300]
    return result, elapsed


def _ordinary_case(probe: APIProbe, index: int) -> tuple[dict[str, Any], float]:
    response, elapsed = probe._chat(
        messages=[{"role": "user", "content": f"Reply with OK-{index} only. /no_think"}],
        max_tokens=8,
        temperature=0,
    )
    content = str(_get(_message(response), "content", "") or "").strip()
    return {
        "ok": bool(content),
        "usage": extract_usage(response),
        "latency_ms": round(elapsed, 2),
    }, elapsed


def _add_usage(total: dict[str, int], usage: dict[str, int]) -> None:
    for key in ("input_tokens", "output_tokens", "total_tokens"):
        total[key] = total.get(key, 0) + int(usage.get(key, 0))


def _gpu_snapshot() -> dict[str, Any]:
    """Capture a leakage-safe point-in-time Radeon telemetry snapshot."""
    try:
        result = subprocess.run(
            ["rocm-smi", "--showproductname", "--showuse", "--showmeminfo", "vram", "--json"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=10,
            check=False,
        )
        payload = json.loads(result.stdout)
        device = next(iter(payload.values())) if isinstance(payload, dict) else {}
        return {
            "gpu_model": device.get("Card series", device.get("Card model")),
            "gpu_utilization_percent": device.get("GPU use (%)"),
            "vram_total_bytes": device.get("VRAM Total Memory (B)"),
            "vram_used_bytes": device.get("VRAM Total Used Memory (B)"),
        }
    except (FileNotFoundError, subprocess.SubprocessError, json.JSONDecodeError, StopIteration):
        return {"available": False}


def _stream_latency_case(probe: APIProbe, index: int) -> dict[str, Any]:
    """Measure TTFT and decode throughput using a real streaming request."""
    started = time.perf_counter()
    first_token_ms: float | None = None
    chunks = 0
    usage: dict[str, int] = {}
    stream = probe.client.chat.completions.create(
        model=probe.config.model,
        messages=[{"role": "user", "content": f"Return a short explanation of case-{index}."}],
        max_tokens=256,
        temperature=0,
        stream=True,
        stream_options={"include_usage": True},
        timeout=probe.config.timeout,
    )
    for chunk in stream:
        if first_token_ms is None and _get(chunk, "choices", []):
            first_token_ms = (time.perf_counter() - started) * 1000
        chunks += 1
        chunk_usage = extract_usage(chunk)
        if chunk_usage["total_tokens"]:
            usage = chunk_usage
    elapsed_ms = (time.perf_counter() - started) * 1000
    output_tokens = usage.get("output_tokens", 0)
    decode_ms = max(0.0, elapsed_ms - (first_token_ms or elapsed_ms))
    return {
        "ok": chunks > 0,
        "ttft_ms": round(first_token_ms, 2) if first_token_ms is not None else None,
        "latency_ms": round(elapsed_ms, 2),
        "output_tokens": output_tokens,
        "decode_tokens_per_second": round(output_tokens / (decode_ms / 1000), 2) if decode_ms and output_tokens else None,
        "usage": usage,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    config = APIConfig.from_env(base_url=args.base_url, model=args.model, timeout=args.timeout)
    probe = APIProbe(config)
    report: dict[str, Any] = {
        "base_url": redact_base_url(config.base_url),
        "model": config.model,
        "requirements": {"tool_cases": 10, "structured_cases": 20, "stability_cases": 30},
        "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "hardware_before": _gpu_snapshot(),
    }

    # A single capability probe gives a useful diagnostic without making the
    # acceptance loop depend on the /models endpoint being enabled.
    try:
        report["capabilities"] = probe.run(include_models=False)
    except Exception as exc:
        report["capabilities"] = {"ok": False, "error": redact_secret(exc, config.api_key)}

    for name, count, callback in (
        ("tool_calls", 10, _tool_case),
        ("structured_outputs", 20, _structured_case),
        ("stability", 30, _ordinary_case),
    ):
        results: list[dict[str, Any]] = []
        latencies: list[float] = []
        for index in range(count):
            try:
                result, elapsed = callback(probe, index)
            except Exception as exc:
                result, elapsed = {"ok": False, "error": redact_secret(exc, config.api_key)}, 0.0
            results.append(result)
            latencies.append(elapsed)
            _add_usage(report["usage"], result.get("usage", {}))
        report[name] = {
            "passed": sum(bool(item.get("ok")) for item in results),
            "required": count,
            "ok": len(results) == count and all(bool(item.get("ok")) for item in results),
            "latency": _latency_summary(latencies),
            "results": results,
        }

    report["accepted"] = all(report[name]["ok"] for name in ("tool_calls", "structured_outputs", "stability"))
    telemetry: list[dict[str, Any]] = []
    for index in range(10):
        try:
            telemetry.append(_stream_latency_case(probe, index))
        except Exception as exc:
            telemetry.append({"ok": False, "error": redact_secret(exc, config.api_key)})
    report["inference_metrics"] = {
        "samples": telemetry,
        "ttft": _latency_summary([float(item["ttft_ms"]) for item in telemetry if item.get("ttft_ms") is not None]),
        "latency": _latency_summary([float(item["latency_ms"]) for item in telemetry if item.get("latency_ms") is not None]),
        "decode_tokens_per_second": _latency_summary([float(item["decode_tokens_per_second"]) for item in telemetry if item.get("decode_tokens_per_second") is not None]),
    }
    report["telemetry_ok"] = any(bool(item.get("ok")) for item in telemetry)
    report["accepted"] = bool(report["accepted"] and report["telemetry_ok"])
    report["hardware_after"] = _gpu_snapshot()
    report["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"accepted": report["accepted"], "output": str(args.output)}, ensure_ascii=False))
    raise SystemExit(0 if report["accepted"] else 2)


if __name__ == "__main__":
    main()
