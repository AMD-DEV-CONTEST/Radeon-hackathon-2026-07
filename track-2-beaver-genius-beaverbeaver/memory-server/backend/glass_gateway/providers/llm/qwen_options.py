from __future__ import annotations

import json
from typing import Any

import httpx


def apply_qwen_request_options(
    payload: dict[str, Any],
    *,
    model: str,
) -> dict[str, Any]:
    """Apply Model Studio requirements without affecting other providers."""

    normalized = model.strip().lower()
    if "qwen" not in normalized:
        return payload
    if "omni" in normalized:
        # Qwen-Omni requires streaming even when Beaver only asks for text.
        payload["stream"] = True
        payload["stream_options"] = {"include_usage": True}
        payload["modalities"] = ["text"]
    else:
        # DashScope's OpenAI-compatible API exposes this as an extra body
        # field. qwen3.7-flash is used only for deterministic text work here.
        payload["enable_thinking"] = False
    return payload


async def post_chat_completion(
    client: httpx.AsyncClient,
    *,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Return one OpenAI-shaped completion from JSON or SSE streaming."""

    if not payload.get("stream"):
        response = await client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        value = response.json()
        if not isinstance(value, dict):
            raise ValueError("chat completion returned non-object JSON")
        return value

    chunks: list[str] = []
    usage: dict[str, Any] = {}
    model = str(payload.get("model") or "")
    async with client.stream("POST", url, headers=headers, json=payload) as response:
        response.raise_for_status()
        async for line in response.aiter_lines():
            line = line.strip()
            if not line or line.startswith(":"):
                continue
            if line.startswith("data:"):
                line = line[5:].strip()
            if line == "[DONE]":
                break
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            if isinstance(event.get("usage"), dict):
                usage = event["usage"]
            if event.get("model"):
                model = str(event["model"])
            choices = event.get("choices")
            if not isinstance(choices, list):
                continue
            for choice in choices:
                if not isinstance(choice, dict):
                    continue
                message = choice.get("delta") or choice.get("message") or {}
                content = message.get("content") if isinstance(message, dict) else None
                if isinstance(content, str):
                    chunks.append(content)
    return {
        "model": model,
        "choices": [{"message": {"content": "".join(chunks)}}],
        "usage": usage,
    }
