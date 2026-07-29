from __future__ import annotations

import os
from typing import Any

import httpx


class LocalLLM:
    """OpenAI-compatible client restricted to loopback/private endpoints."""

    def __init__(self) -> None:
        self.base_url = os.getenv("LOCAL_LLM_URL", "http://127.0.0.1:8080/v1").rstrip("/")
        self.model = os.getenv("LOCAL_LLM_MODEL", "qwen2.5-7b-instruct")
        self.enabled = os.getenv("LOCAL_LLM_ENABLED", "0") == "1"

    @property
    def backend(self) -> str:
        return f"{self.base_url} :: {self.model}" if self.enabled else "deterministic demo mode"

    def _is_local(self) -> bool:
        return any(host in self.base_url for host in ("127.0.0.1", "localhost", "0.0.0.0", "10.", "192.168."))

    def complete(self, system: str, user: str) -> str | None:
        if not self.enabled:
            return None
        if not self._is_local():
            raise RuntimeError("Remote LLM endpoints are disabled. Use a local ROCm-backed server.")
        payload: dict[str, Any] = {
            "model": self.model,
            "temperature": 0.1,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        response = httpx.post(f"{self.base_url}/chat/completions", json=payload, timeout=90)
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]

