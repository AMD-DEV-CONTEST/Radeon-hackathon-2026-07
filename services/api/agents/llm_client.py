import json
import os
from typing import Any

from openai import OpenAI
from config import settings


class LLMClient:
    """OpenAI-compatible LLM client with a deterministic mock fallback for dev/tests."""

    def __init__(self):
        self._client: OpenAI | None = None
        if not settings.llm_mock_mode and settings.llm_api_key:
            self._client = OpenAI(
                api_key=settings.llm_api_key,
                base_url=settings.llm_base_url,
            )

    def chat_json(
        self,
        system: str,
        user: str,
        schema: dict[str, Any],
        fallback: dict[str, Any],
    ) -> dict[str, Any]:
        """Return a JSON object parsed from the LLM response. Falls back to deterministic fallback if no key/mock."""
        if self._client is None:
            return fallback

        try:
            response = self._client.chat.completions.create(
                model=settings.llm_model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_format={"type": "json_object"},
                temperature=0.2,
            )
            content = response.choices[0].message.content or "{}"
            return json.loads(content)
        except Exception as exc:
            # In production this should be logged; for now return fallback to keep dev stable.
            print(f"LLM call failed: {exc}")
            return fallback


llm_client = LLMClient()
