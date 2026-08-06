"""API client"""

from __future__ import annotations

import aiohttp


class LLMClient:
    def __init__(self, *, endpoint: str, api_key: str, model: str, timeout: int = 45):
        # Clean endpoint: strip trailing /v1 or /
        endpoint = endpoint.rstrip("/")
        if endpoint.endswith("/v1"):
            endpoint = endpoint[:-3]  # Strip /v1
        self.endpoint = endpoint.rstrip("/")
        
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self._session: aiohttp.ClientSession | None = None

    async def __aenter__(self):
        self._session = aiohttp.ClientSession(
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            timeout=aiohttp.ClientTimeout(total=self.timeout),
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._session:
            await self._session.close()
            self._session = None

    async def chat(self, messages: list[dict], **kwargs) -> dict:
        payload = {
            "model": self.model,
            "messages": messages,
            **kwargs,
        }
        
        # Use /v1/chat/completions uniformly
        url = f"{self.endpoint}/v1/chat/completions"
        
        async with self._session.post(url, json=payload) as resp:
            resp.raise_for_status()
            return await resp.json()


async def get_llm_client(**kwargs) -> LLMClient:
    return LLMClient(**kwargs)