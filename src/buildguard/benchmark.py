"""Local-only LLM benchmark implementation."""

from __future__ import annotations

import ipaddress
import json
import time
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel

from buildguard.config import LLMConfig, PermissionConfig, Settings
from buildguard.exceptions import EndpointSecurityError
from buildguard.monitoring import AmdSmiMonitor, CompositeMonitor, ProcessMonitor, RocmSmiMonitor
from buildguard.monitoring.base import HardwareSnapshot


class BenchmarkResult(BaseModel):
    """Timing and hardware observations for one request."""

    mode: str
    model: str
    prompt: str
    response_text: str
    total_seconds: float
    first_token_seconds: float
    output_tokens: int
    tokens_per_second: float
    start_snapshot: HardwareSnapshot
    end_snapshot: HardwareSnapshot


def validate_local_endpoint(llm: LLMConfig, permissions: PermissionConfig) -> None:
    """Reject endpoints not explicitly local or inside an allowed LAN CIDR."""
    parsed = urlparse(str(llm.endpoint))
    host = parsed.hostname
    if parsed.scheme not in {"http", "https"} or not host:
        raise EndpointSecurityError("LLM endpoint must be a valid HTTP(S) URL")
    if host.lower() in {item.lower() for item in llm.allowed_hosts}:
        return
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise EndpointSecurityError(f"Endpoint hostname is not allowlisted: {host}") from exc
    if permissions.allow_lan_llm:
        for raw_network in permissions.allowed_lan_cidrs:
            try:
                if address in ipaddress.ip_network(raw_network, strict=False):
                    return
            except ValueError as exc:
                raise EndpointSecurityError(f"Invalid allowed LAN CIDR: {raw_network}") from exc
    raise EndpointSecurityError(f"Endpoint is not localhost or an allowed LAN address: {host}")


def _monitor(settings: Settings) -> CompositeMonitor:
    return CompositeMonitor(
        [
            AmdSmiMonitor(settings.monitoring.command_timeout_seconds),
            RocmSmiMonitor(settings.monitoring.command_timeout_seconds),
            ProcessMonitor(),
        ],
        settings.monitoring.sample_interval_seconds,
    )


def _stream_chunks(response: httpx.Response) -> Iterator[str]:
    for line in response.iter_lines():
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        try:
            payload: dict[str, Any] = json.loads(data)
            content = payload["choices"][0].get("delta", {}).get("content")
            if content:
                yield str(content)
        except (json.JSONDecodeError, KeyError, IndexError, TypeError):
            continue


def run_benchmark(settings: Settings) -> BenchmarkResult:
    """Run one deterministic prompt against mock or an approved local endpoint."""
    prompt = "Reply with exactly: BuildGuard local inference ready."
    monitor = _monitor(settings)
    start_snapshot = monitor.snapshot()
    started = time.perf_counter()
    first_token: float
    if settings.llm.mode == "mock":
        response_text = "BuildGuard local inference ready."
        first_token = 0.0
        output_tokens = 5
    else:
        validate_local_endpoint(settings.llm, settings.permissions)
        url = f"{str(settings.llm.endpoint).rstrip('/')}/chat/completions"
        headers: dict[str, str] = {}
        if settings.llm.api_key:
            headers["Authorization"] = f"Bearer {settings.llm.api_key.get_secret_value()}"
        payload = {
            "model": settings.llm.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": settings.llm.temperature,
            "max_tokens": settings.llm.max_tokens,
            "stream": True,
            "seed": settings.app.seed,
        }
        pieces: list[str] = []
        first_token = 0.0
        with httpx.stream(
            "POST",
            url,
            json=payload,
            headers=headers,
            timeout=settings.llm.timeout_seconds,
        ) as response:
            response.raise_for_status()
            for piece in _stream_chunks(response):
                if not pieces:
                    first_token = time.perf_counter() - started
                pieces.append(piece)
        response_text = "".join(pieces)
        output_tokens = max(1, len(response_text.split()))
    total = time.perf_counter() - started
    end_snapshot = monitor.snapshot()
    return BenchmarkResult(
        mode=settings.llm.mode,
        model=settings.llm.model,
        prompt=prompt,
        response_text=response_text,
        total_seconds=total,
        first_token_seconds=first_token,
        output_tokens=output_tokens,
        tokens_per_second=output_tokens / total if total > 0 else 0.0,
        start_snapshot=start_snapshot,
        end_snapshot=end_snapshot,
    )

