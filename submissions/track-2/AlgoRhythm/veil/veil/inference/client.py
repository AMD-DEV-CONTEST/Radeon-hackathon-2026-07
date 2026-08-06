"""Async vLLM client with a hard egress guarantee.

Every model call goes through here, and every call is routed through the
allowlisted transport in security/egress.py. There is no second HTTP client
in this codebase — that is the point.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

import httpx

from veil.config import CONFIG
from veil.security.egress import guarded_async_client


@dataclass
class CallMetrics:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_s: float = 0.0
    ttft_s: float | None = None

    @property
    def tokens_per_second(self) -> float:
        if self.latency_s <= 0:
            return 0.0
        return self.completion_tokens / self.latency_s


@dataclass
class MetricsCollector:
    """Aggregates across a run so the benchmark and the UI read the same
    numbers. Nothing here is estimated — every field comes from vLLM."""

    calls: list[CallMetrics] = field(default_factory=list)

    def record(self, m: CallMetrics) -> None:
        self.calls.append(m)

    def summary(self) -> dict[str, Any]:
        if not self.calls:
            return {"calls": 0}
        total_completion = sum(c.completion_tokens for c in self.calls)
        total_prompt = sum(c.prompt_tokens for c in self.calls)
        wall = sum(c.latency_s for c in self.calls)
        ttfts = [c.ttft_s for c in self.calls if c.ttft_s is not None]
        return {
            "calls": len(self.calls),
            "prompt_tokens": total_prompt,
            "completion_tokens": total_completion,
            "mean_tokens_per_second": round(total_completion / wall, 2) if wall else 0,
            "mean_ttft_s": round(sum(ttfts) / len(ttfts), 3) if ttfts else None,
        }


class VLLMClient:
    def __init__(self, metrics: MetricsCollector | None = None) -> None:
        self.cfg = CONFIG.inference
        self.metrics = metrics or MetricsCollector()

    async def complete(
        self,
        prefix: str,
        suffix: str,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> tuple[str, CallMetrics]:
        """Single non-streaming completion.

        prefix and suffix are kept separate by the caller so that prefix
        determinism is auditable; they are concatenated only here.
        """
        payload = {
            "model": self.cfg.model,
            "messages": [
                {"role": "system", "content": prefix},
                {"role": "user", "content": suffix},
            ],
            "max_tokens": max_tokens or self.cfg.max_tokens,
            "temperature": self.cfg.temperature if temperature is None else temperature,
        }
        started = time.perf_counter()
        async with guarded_async_client(timeout=self.cfg.request_timeout_s) as client:
            resp = await client.post(f"{self.cfg.base_url}/chat/completions", json=payload)
            resp.raise_for_status()
            data = resp.json()
        elapsed = time.perf_counter() - started

        usage = data.get("usage", {})
        m = CallMetrics(
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            latency_s=elapsed,
        )
        self.metrics.record(m)
        return data["choices"][0]["message"]["content"], m

    async def stream(self, prefix: str, suffix: str) -> AsyncIterator[str]:
        """Token stream, used by the attack theatre UI so judges watch the
        reasoning arrive rather than waiting on a spinner."""
        payload = {
            "model": self.cfg.model,
            "messages": [
                {"role": "system", "content": prefix},
                {"role": "user", "content": suffix},
            ],
            "max_tokens": self.cfg.max_tokens,
            "temperature": self.cfg.temperature,
            "stream": True,
        }
        async with guarded_async_client(timeout=self.cfg.request_timeout_s) as client:
            async with client.stream(
                "POST", f"{self.cfg.base_url}/chat/completions", json=payload
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    body = line[6:]
                    if body.strip() == "[DONE]":
                        return
                    try:
                        chunk = json.loads(body)
                    except json.JSONDecodeError:
                        continue
                    delta = chunk["choices"][0]["delta"].get("content")
                    if delta:
                        yield delta

    async def health(self) -> bool:
        try:
            async with guarded_async_client(timeout=5.0) as client:
                r = await client.get(f"{self.cfg.base_url}/models")
                return r.status_code == 200
        except (httpx.HTTPError, OSError):
            return False

    async def prefix_cache_stats(self) -> dict[str, Any]:
        """Scrape vLLM's Prometheus endpoint for the cache hit rate.

        This is the number that validates the whole concurrency design, so we
        read it from the server rather than inferring it from timings.
        """
        base = self.cfg.base_url.rsplit("/v1", 1)[0]
        try:
            async with guarded_async_client(timeout=5.0) as client:
                r = await client.get(f"{base}/metrics")
                r.raise_for_status()
        except (httpx.HTTPError, OSError):
            return {"available": False}

        out: dict[str, Any] = {"available": True, "gpu_prefix_cache_hit_rate": 0.0}
        hits = 0.0
        queries = 0.0
        usage = None

        for line in r.text.splitlines():
            if line.startswith("#"):
                continue
            for key in ("gpu_prefix_cache_hit_rate", "gpu_cache_usage_perc"):
                if key in line:
                    try:
                        out[key] = float(line.rsplit(" ", 1)[1])
                    except (ValueError, IndexError):
                        pass

            if "vllm:prefix_cache_hits_total" in line:
                try:
                    hits = float(line.rsplit(" ", 1)[1])
                except (ValueError, IndexError):
                    pass
            elif "vllm:prefix_cache_queries_total" in line:
                try:
                    queries = float(line.rsplit(" ", 1)[1])
                except (ValueError, IndexError):
                    pass
            elif "vllm:kv_cache_usage_perc" in line:
                try:
                    usage = float(line.rsplit(" ", 1)[1])
                except (ValueError, IndexError):
                    pass

        if queries > 0:
            out["gpu_prefix_cache_hit_rate"] = round(hits / queries, 4)
        if usage is not None:
            out["gpu_cache_usage_perc"] = usage

        return out
