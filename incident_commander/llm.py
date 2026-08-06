from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any


@dataclass(frozen=True)
class LLMResult:
    content: str
    latency_ms: float
    model: str
    usage: dict[str, Any]


@dataclass(frozen=True)
class StreamingLLMResult:
    content: str
    ttft_ms: float
    latency_ms: float
    model: str
    usage: dict[str, Any]


@dataclass(frozen=True)
class ToolChoiceResult:
    name: str
    arguments: dict[str, Any]
    latency_ms: float
    model: str
    usage: dict[str, Any]


class OpenAICompatibleClient:
    """Small dependency-free adapter for vLLM, llama.cpp, or another local ROCm endpoint."""

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        timeout: float = 90.0,
    ):
        _load_dotenv()
        self.base_url = (base_url or os.getenv("LIC_LLM_BASE_URL", "http://127.0.0.1:8000/v1")).rstrip("/")
        self.model = model or os.getenv("LIC_LLM_MODEL", "local-model")
        self.api_key = api_key or os.getenv("LIC_LLM_API_KEY")
        self.timeout = timeout

    def complete(self, system: str, user: str, max_tokens: int = 256) -> LLMResult:
        body = json.dumps(
            {
                "model": self.model,
                "temperature": 0.1,
                "max_tokens": max_tokens,
                "chat_template_kwargs": {"enable_thinking": False},
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            }
        ).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=body,
            headers=headers,
            method="POST",
        )
        started = perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.load(response)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"local model request failed: {exc}") from exc
        content = payload["choices"][0]["message"].get("content")
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("model returned no user-visible content")
        return LLMResult(
            content=content,
            latency_ms=round((perf_counter() - started) * 1000, 2),
            model=str(payload.get("model", self.model)),
            usage=dict(payload.get("usage", {})),
        )

    def choose_tool(
        self,
        system: str,
        user: str,
        tools: list[dict[str, Any]],
        max_tokens: int = 256,
    ) -> ToolChoiceResult:
        body = json.dumps(
            {
                "model": self.model,
                "temperature": 0.0,
                "max_tokens": max_tokens,
                "chat_template_kwargs": {"enable_thinking": False},
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "tools": tools,
                "tool_choice": "auto",
            }
        ).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions", data=body, headers=headers, method="POST"
        )
        started = perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.load(response)
            message = payload["choices"][0]["message"]
            calls = message.get("tool_calls") or []
            function = calls[0]["function"]
            arguments = json.loads(function["arguments"])
            if not isinstance(arguments, dict):
                raise TypeError("tool arguments must be an object")
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError, IndexError, TypeError, AttributeError) as exc:
            raise RuntimeError(f"local model tool request failed: {exc}") from exc
        return ToolChoiceResult(
            name=str(function["name"]),
            arguments=arguments,
            latency_ms=round((perf_counter() - started) * 1000, 2),
            model=str(payload.get("model", self.model)),
            usage=dict(payload.get("usage", {})),
        )

    def stream_complete(self, system: str, user: str, max_tokens: int = 256) -> StreamingLLMResult:
        body = json.dumps(
            {
                "model": self.model,
                "temperature": 0.1,
                "max_tokens": max_tokens,
                "stream": True,
                "stream_options": {"include_usage": True},
                "chat_template_kwargs": {"enable_thinking": False},
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            }
        ).encode("utf-8")
        headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions", data=body, headers=headers, method="POST"
        )
        started = perf_counter()
        first_token_at: float | None = None
        content_parts: list[str] = []
        usage: dict[str, Any] = {}
        observed_model = self.model
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                for raw_line in response:
                    line = raw_line.decode("utf-8").strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    chunk = json.loads(data)
                    observed_model = str(chunk.get("model", observed_model))
                    if chunk.get("usage"):
                        usage = dict(chunk["usage"])
                    choices = chunk.get("choices") or []
                    delta = choices[0].get("delta", {}) if choices else {}
                    token = delta.get("content")
                    if isinstance(token, str) and token:
                        if first_token_at is None:
                            first_token_at = perf_counter()
                        content_parts.append(token)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise RuntimeError(f"local model streaming request failed: {exc}") from exc
        finished = perf_counter()
        content = "".join(content_parts).strip()
        if first_token_at is None or not content:
            raise RuntimeError("model stream returned no user-visible content")
        return StreamingLLMResult(
            content=content,
            ttft_ms=round((first_token_at - started) * 1000, 2),
            latency_ms=round((finished - started) * 1000, 2),
            model=observed_model,
            usage=usage,
        )


def _load_dotenv(path: Path | None = None) -> None:
    env_path = path or Path.cwd() / ".env"
    if not env_path.is_file():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
