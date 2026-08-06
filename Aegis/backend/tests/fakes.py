"""
Test doubles for expensive/external dependencies. These exist ONLY under
tests/ and are never imported by application code — the real InferenceClient
(app/inference/client.py) is what runs in production against ROCm/vLLM.
"""
import json

from app.inference.client import CompletionResult


class FakeInferenceClient:
    """Deterministic stand-in for InferenceClient so agent logic can be
    verified without a running GPU/vLLM server."""

    def __init__(self, scripted_responses: dict[str, str] | None = None) -> None:
        self.scripted_responses = scripted_responses or {}
        self.call_log: list[dict] = []

    async def complete(self, *, system_prompt: str, user_prompt: str, temperature=0.2, max_tokens=1024):
        self.call_log.append({"system_prompt": system_prompt[:50], "user_prompt": user_prompt[:200]})
        # Route by a keyword in the system prompt to the right scripted agent response.
        for keyword, response_text in self.scripted_responses.items():
            if keyword in system_prompt:
                return CompletionResult(
                    text=response_text, prompt_tokens=50, completion_tokens=40, duration_ms=120.0
                )
        return CompletionResult(text="No anomalies found.", prompt_tokens=50, completion_tokens=10, duration_ms=80.0)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        # Deterministic pseudo-embedding (hash-based) — enough for cosine-similarity
        # plumbing tests without a real embedding model.
        return [[float((hash(t) >> i) % 100) / 100 for i in range(1024)] for t in texts]

    async def aclose(self) -> None:
        pass
