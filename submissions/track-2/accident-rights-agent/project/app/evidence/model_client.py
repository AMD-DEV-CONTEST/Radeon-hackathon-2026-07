"""Minimal OpenAI-compatible client restricted to the local vLLM endpoint."""

from __future__ import annotations

import base64
import json
import mimetypes
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.evidence.errors import ModelResponseError
from app.policy.local_only import local_api_url, require_local_vllm_base_url


@dataclass(frozen=True)
class ModelCall:
    content: str
    model: str
    latency_seconds: float
    usage: dict[str, Any]


class LocalVLLMClient:
    def __init__(
        self,
        base_url: str | None = None,
        *,
        timeout_seconds: int = 300,
    ):
        self.base_url = require_local_vllm_base_url(base_url)
        self.timeout_seconds = timeout_seconds
        self._model: str | None = None

    def model_name(self) -> str:
        if self._model:
            return self._model
        payload = self._request("GET", "/models")
        models = payload.get("data")
        if not isinstance(models, list) or not models or not models[0].get("id"):
            raise ModelResponseError("Local /v1/models returned no model ID.")
        self._model = str(models[0]["id"])
        return self._model

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int = 1200,
        temperature: float = 0.0,
    ) -> ModelCall:
        model = self.model_name()
        started = time.perf_counter()
        payload = self._request(
            "POST",
            "/chat/completions",
            {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "response_format": {"type": "json_object"},
            },
        )
        latency = time.perf_counter() - started
        try:
            content = str(payload["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelResponseError(
                "Local chat response lacks choices[0].message.content."
            ) from exc
        return ModelCall(
            content=content,
            model=model,
            latency_seconds=latency,
            usage=payload.get("usage") or {},
        )

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            local_api_url(path, self.base_url),
            data=body,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(
                request, timeout=self.timeout_seconds
            ) as response:
                decoded = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise ModelResponseError(
                f"Local vLLM request failed for {path}: {exc}"
            ) from exc
        if not isinstance(decoded, dict):
            raise ModelResponseError("Local vLLM returned a non-object JSON response.")
        return decoded


def image_data_url(path: Path, *, max_bytes: int = 20 * 1024 * 1024) -> str:
    stat = path.stat()
    if stat.st_size > max_bytes:
        raise ModelResponseError(
            f"Derived image {path.name} exceeds {max_bytes} bytes."
        )
    media_type = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{media_type};base64,{encoded}"


def strict_json(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        if start < 0:
            raise ModelResponseError("Model output contains no JSON object.")
        parsed = None
        for end in range(len(stripped), start, -1):
            try:
                parsed = json.loads(stripped[start:end])
                break
            except json.JSONDecodeError:
                continue
        if parsed is None:
            raise ModelResponseError("Model output is not valid JSON.")
    if not isinstance(parsed, dict):
        raise ModelResponseError("Model output JSON must be an object.")
    return parsed
