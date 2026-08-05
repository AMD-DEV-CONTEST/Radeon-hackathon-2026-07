"""Streaming, local-only vLLM calls with TTFT and TPOT measurements."""

from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any

from app.policy.local_only import local_api_url, require_local_vllm_base_url


@dataclass(frozen=True)
class StreamingResult:
    model: str
    content: str
    input_tokens: int | None
    output_tokens: int | None
    ttft_seconds: float | None
    total_latency_seconds: float
    decode_seconds: float | None
    tpot_seconds: float | None
    tokens_per_second: float | None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def model_name(base_url: str | None = None, *, timeout: int = 30) -> str:
    endpoint = require_local_vllm_base_url(base_url)
    request = urllib.request.Request(
        local_api_url("/models", endpoint), method="GET"
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    models = payload.get("data") or []
    if not models or not models[0].get("id"):
        raise RuntimeError("Local /v1/models returned no model ID.")
    return str(models[0]["id"])


def stream_chat(
    messages: list[dict[str, Any]],
    *,
    base_url: str | None = None,
    max_tokens: int = 700,
    temperature: float = 0.0,
    timeout: int = 300,
) -> StreamingResult:
    endpoint = require_local_vllm_base_url(base_url)
    model = model_name(endpoint, timeout=min(timeout, 30))
    body = json.dumps(
        {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
            "response_format": {"type": "json_object"},
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        local_api_url("/chat/completions", endpoint),
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    started = time.perf_counter()
    first_token_at: float | None = None
    finished = started
    output: list[str] = []
    usage: dict[str, Any] = {}
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
                usage = dict(chunk["usage"])
            choices = chunk.get("choices") or []
            if not choices:
                continue
            content = choices[0].get("delta", {}).get("content")
            if content:
                if first_token_at is None:
                    first_token_at = time.perf_counter()
                output.append(str(content))
        finished = time.perf_counter()
    output_tokens = usage.get("completion_tokens")
    decode_seconds = (
        finished - first_token_at if first_token_at is not None else None
    )
    tpot = (
        decode_seconds / max(1, int(output_tokens) - 1)
        if decode_seconds is not None and output_tokens is not None
        else None
    )
    throughput = (
        float(output_tokens) / decode_seconds
        if decode_seconds and output_tokens
        else None
    )
    return StreamingResult(
        model=model,
        content="".join(output),
        input_tokens=usage.get("prompt_tokens"),
        output_tokens=output_tokens,
        ttft_seconds=(
            first_token_at - started if first_token_at is not None else None
        ),
        total_latency_seconds=finished - started,
        decode_seconds=decode_seconds,
        tpot_seconds=tpot,
        tokens_per_second=throughput,
    )
