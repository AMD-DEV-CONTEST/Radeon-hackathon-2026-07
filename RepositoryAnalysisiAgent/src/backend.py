"""LLM backend abstraction for RepositoryAnalysisAgent.

Communicates with the inference server (vLLM or llama.cpp) via its
OpenAI-compatible HTTP endpoint. No GPU access needed in this module —
that's the server's job.

Key design:
- ``LLMBackend`` protocol: ``chat()`` (non-streaming) and ``stream_chat()``.
- ``OpenAIBackend``: works with both vLLM and llama.cpp since both expose
  ``/v1/chat/completions``.
- The FP8 try-fail-fallback logic lives in ``start_llm.sh`` (launches the server).
  This module just talks to whatever server is running.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Protocol

import httpx

from .config import LLMConfig


@dataclass
class ChatMessage:
    role: str  # "system" | "user" | "assistant" | "tool"
    content: str = ""
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None
    name: str | None = None  # tool name for role="tool"

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_calls:
            d["tool_calls"] = self.tool_calls
        if self.tool_call_id:
            d["tool_call_id"] = self.tool_call_id
        if self.name:
            d["name"] = self.name
        return d


@dataclass
class ToolDef:
    """OpenAI-compatible function tool definition."""
    name: str
    description: str
    parameters: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass
class ChatResponse:
    content: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    finish_reason: str = "stop"
    usage: dict[str, int] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


class LLMBackend(Protocol):
    """Protocol for LLM backends."""

    async def chat(
        self,
        messages: list[ChatMessage],
        tools: list[ToolDef] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> ChatResponse: ...

    async def stream_chat(
        self,
        messages: list[ChatMessage],
        tools: list[ToolDef] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[dict[str, Any]]: ...

    async def health(self) -> bool: ...


class OpenAIBackend:
    """HTTP client for vLLM / llama.cpp OpenAI-compatible API."""

    def __init__(self, config: LLMConfig) -> None:
        self.config = config
        self.base_url = config.base_url.rstrip("/")
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(connect=10.0, read=300.0, write=10.0, pool=5.0),
            headers={"Authorization": f"Bearer {config.api_key}"},
        )

    async def chat(
        self,
        messages: list[ChatMessage],
        tools: list[ToolDef] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> ChatResponse:
        payload = self._build_payload(messages, tools, temperature, max_tokens, stream=False)
        resp = await self.client.post("/chat/completions", json=payload)
        resp.raise_for_status()
        data = resp.json()
        choice = data["choices"][0]
        message = choice["message"]
        return ChatResponse(
            content=message.get("content") or "",
            tool_calls=message.get("tool_calls", []),
            finish_reason=choice.get("finish_reason", "stop"),
            usage=data.get("usage", {}),
            raw=data,
        )

    async def stream_chat(
        self,
        messages: list[ChatMessage],
        tools: list[ToolDef] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield SSE-parsed delta dicts.

        Each yielded dict has keys like:
        - ``content``: str (text delta)
        - ``tool_calls``: list (incremental tool call deltas)
        - ``finish_reason``: str | None
        """
        payload = self._build_payload(messages, tools, temperature, max_tokens, stream=True)
        async with self.client.stream("POST", "/chat/completions", json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line or not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str.strip() == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                except json.JSONDecodeError:
                    continue
                choice = chunk.get("choices", [{}])[0]
                delta = choice.get("delta", {})
                yield {
                    "content": delta.get("content") or "",
                    "tool_calls": delta.get("tool_calls", []),
                    "finish_reason": choice.get("finish_reason"),
                }

    async def health(self) -> bool:
        try:
            resp = await self.client.get("/models", timeout=5.0)
            return resp.status_code == 200
        except (httpx.HTTPError, httpx.TimeoutException):
            return False

    def _build_payload(
        self,
        messages: list[ChatMessage],
        tools: list[ToolDef] | None,
        temperature: float | None,
        max_tokens: int | None,
        stream: bool,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": [m.to_dict() for m in messages],
            "temperature": temperature if temperature is not None else self.config.temperature,
            "top_p": self.config.top_p,
            "stream": stream,
        }
        if tools:
            payload["tools"] = [t.to_dict() for t in tools]
            payload["tool_choice"] = "auto"
        if max_tokens:
            payload["max_tokens"] = max_tokens
        return payload

    async def close(self) -> None:
        await self.client.aclose()


def create_backend(config: LLMConfig) -> LLMBackend:
    """Factory: create the appropriate backend based on config."""
    return OpenAIBackend(config)
