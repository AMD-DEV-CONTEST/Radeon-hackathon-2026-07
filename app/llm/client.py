from __future__ import annotations

import json
import asyncio
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.config import Settings


ModelT = TypeVar("ModelT", bound=BaseModel)


class LLMClientError(RuntimeError):
    """A controlled failure while calling or validating an LLM response."""


class LLMClient:
    def __init__(self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._settings = settings
        self._transport = transport

    @property
    def endpoint(self) -> str:
        return f"{str(self._settings.llm_base_url).rstrip('/')}/chat/completions"

    async def generate_text(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        temperature: float = 0.2,
        project_id: str | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        if not project_id:
            return await self._complete(messages, temperature=temperature)
        from app.services.task_queue import get_task_queue

        return await get_task_queue(self._settings).enqueue_llm(
            project_id=project_id,
            cancel_event=cancel_event or asyncio.Event(),
            callable=self._complete,
            messages=messages,
            temperature=temperature,
        )

    async def generate_json(
        self, schema: type[ModelT], prompt: str, *, project_id: str | None = None
    ) -> ModelT:
        schema_text = json.dumps(schema.model_json_schema(), ensure_ascii=False)
        instruction = (
            "Return only one JSON object with no Markdown fences. It must validate against this JSON Schema: "
            f"{schema_text}"
        )
        last_error: Exception | None = None
        for attempt in range(2):
            retry_note = "" if attempt == 0 else " Your previous response was invalid. Return valid JSON only."
            raw = await self.generate_text(
                prompt, system_prompt=instruction + retry_note, temperature=0, project_id=project_id
            )
            try:
                return schema.model_validate_json(raw)
            except ValidationError as error:
                last_error = error
        raise LLMClientError(f"model did not produce valid {schema.__name__} JSON after one retry: {last_error}")

    async def _complete(self, messages: list[dict[str, str]], *, temperature: float) -> str:
        payload = {
            "model": self._settings.llm_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": self._settings.llm_max_tokens,
        }
        try:
            async with httpx.AsyncClient(
                timeout=self._settings.llm_timeout_seconds, transport=self._transport
            ) as client:
                response = await client.post(
                    self.endpoint,
                    json=payload,
                    headers={"Authorization": f"Bearer {self._settings.llm_api_key}"},
                )
                response.raise_for_status()
        except httpx.HTTPError as error:
            raise LLMClientError(f"model generation failed: {error}") from error

        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise LLMClientError("model response has no chat completion content") from error
        if not isinstance(content, str) or not content.strip():
            raise LLMClientError("model response content is empty or non-text")
        return content
