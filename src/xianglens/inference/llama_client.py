"""OpenAI-compatible client for the user-controlled llama.cpp service."""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Any, Protocol

import httpx


class ModelNotConfiguredError(RuntimeError):
    pass


class ModelRequestError(RuntimeError):
    pass


class ModelClient(Protocol):
    async def health(self) -> bool: ...

    async def chat(
        self, messages: list[dict[str, Any]], *, temperature: float = 0.2, max_tokens: int = 1200
    ) -> str: ...

    async def inspect_image(self, path: Path, prompt: str) -> dict[str, Any]: ...


def parse_json_object(text: str) -> dict[str, Any]:
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*", "", candidate)
        candidate = re.sub(r"\s*```$", "", candidate)
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start < 0 or end <= start:
            raise ModelRequestError("The model response did not contain a JSON object") from None
        try:
            value = json.loads(candidate[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ModelRequestError("The model returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise ModelRequestError("The model response must be a JSON object")
    return value


class LlamaCppClient:
    """Thin adapter that avoids coupling the graph to a specific SDK."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: float,
        enable_thinking: bool = True,
        reasoning_budget: int = 2048,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.enable_thinking = enable_thinking
        self.reasoning_budget = reasoning_budget
        self.transport = transport

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _require_configured(self) -> None:
        if not self.base_url:
            raise ModelNotConfiguredError(
                "Set XIANG_LLM_BASE_URL after the self-hosted Radeon endpoint is available"
            )

    async def health(self) -> bool:
        self._require_configured()
        try:
            async with httpx.AsyncClient(
                timeout=min(self.timeout_seconds, 10.0), transport=self.transport
            ) as client:
                response = await client.get(f"{self.base_url}/models", headers=self._headers())
                response.raise_for_status()
            return True
        except httpx.HTTPError:
            return False

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float = 0.2,
        max_tokens: int = 1200,
    ) -> str:
        self._require_configured()
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            # llama.cpp counts reasoning and final content against the same generation
            # budget. Treat the public argument as final-content capacity and reserve
            # the configured reasoning allowance separately.
            "max_tokens": max_tokens + (self.reasoning_budget if self.enable_thinking else 0),
            "stream": False,
            "chat_template_kwargs": {"enable_thinking": self.enable_thinking},
            "reasoning_budget": self.reasoning_budget if self.enable_thinking else 0,
        }
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds, transport=self.transport
            ) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=self._headers(),
                    json=payload,
                )
                response.raise_for_status()
                body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ModelRequestError(f"Self-hosted model request failed: {exc}") from exc
        try:
            message = body["choices"][0]["message"]
            content = str(message["content"] or "")
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelRequestError(
                "The model response did not match the chat-completions schema"
            ) from exc
        if not content.strip() and message.get("reasoning_content"):
            raise ModelRequestError(
                "The model used the output budget for reasoning before producing final content"
            )
        return content

    async def inspect_image(self, path: Path, prompt: str) -> dict[str, Any]:
        mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        content = [
            {"type": "text", "text": prompt},
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{encoded}"},
            },
        ]
        text = await self.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "You are the visual observation component of XiangLens. Return only JSON. "
                        "Describe visible evidence and uncertainty. Never identify a person "
                        "or infer personality, health, wealth, politics, religion, protected "
                        "attributes, or destiny."
                    ),
                },
                {"role": "user", "content": content},
            ],
            temperature=0.1,
            max_tokens=1200,
        )
        return parse_json_object(text)
