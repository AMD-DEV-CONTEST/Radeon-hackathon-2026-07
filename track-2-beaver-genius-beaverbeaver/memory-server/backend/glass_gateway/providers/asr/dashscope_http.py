from __future__ import annotations

import base64
import io
import wave
from typing import Any

import httpx

from .base import ASRProvider


class DashScopeASRHTTPError(RuntimeError):
    """HTTP failure with a bounded provider response safe for diagnostics."""

    def __init__(self, *, status_code: int, response_excerpt: str) -> None:
        self.status_code = int(status_code)
        self.response_excerpt = response_excerpt
        self.retryable = self.status_code in {408, 425, 429} or self.status_code >= 500
        detail = response_excerpt or "<empty response>"
        super().__init__(f"DashScope ASR HTTP {self.status_code}: {detail}")


class DashScopeHTTPASRProvider(ASRProvider):
    """Adapter for the LiteLLM-proxied DashScope ASR JSON contract."""

    def __init__(
        self,
        *,
        api_key: str,
        endpoint: str,
        model: str = "fun-asr-flash-2026-06-15",
        language: str = "auto",
        timeout_seconds: float = 120.0,
    ) -> None:
        if not endpoint.strip():
            raise ValueError("DashScope HTTP ASR endpoint is required")
        if language not in {"auto", "zh", "en"}:
            raise ValueError(f"unsupported ASR language: {language}")
        self.api_key = api_key.strip()
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.language = language
        self.timeout_seconds = timeout_seconds

    @property
    def provider_name(self) -> str:
        return "dashscope_http"

    @property
    def model_name(self) -> str:
        return self.model

    async def transcribe(self, pcm_bytes: bytes, sample_rate: int) -> str:
        if not pcm_bytes:
            return ""
        if not self.api_key:
            raise RuntimeError("MEMORY_ASR_API_KEY is not configured")
        wav_bytes = _pcm16_to_wav(pcm_bytes, sample_rate)
        encoded = base64.b64encode(wav_bytes).decode("ascii")
        payload: dict[str, Any] = {
            "model": self.model,
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_audio",
                                "input_audio": {
                                    "data": f"data:audio/wav;base64,{encoded}"
                                },
                            }
                        ],
                    }
                ]
            },
            "parameters": {
                "format": "wav",
                "sample_rate": str(sample_rate),
            },
        }
        if self.language != "auto":
            payload["parameters"]["language"] = self.language
        async with httpx.AsyncClient(
            timeout=self.timeout_seconds,
            trust_env=False,
        ) as client:
            response = await client.post(
                self.endpoint,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        if response.is_error:
            raise DashScopeASRHTTPError(
                status_code=response.status_code,
                response_excerpt=_response_excerpt(response),
            )
        return _extract_transcript(response.json())

    async def transcribe_live(self, pcm_bytes: bytes, sample_rate: int) -> str:
        """Compatibility alias used by the offline/full-day replay runner."""
        return await self.transcribe(pcm_bytes, sample_rate)


def _pcm16_to_wav(pcm_bytes: bytes, sample_rate: int) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_bytes)
    return output.getvalue()


def _response_excerpt(response: httpx.Response, *, limit: int = 2_000) -> str:
    """Return a single-line error excerpt without ever echoing request media."""

    text = " ".join(response.text.split())
    if len(text) <= limit:
        return text
    return f"{text[:limit]}…"


def _extract_transcript(data: Any) -> str:
    """Accept DashScope native and OpenAI-normalized response envelopes."""

    if not isinstance(data, dict):
        raise ValueError("DashScope ASR returned a non-object response")
    output = data.get("output")
    nested_output = output.get("output") if isinstance(output, dict) else None
    sentence = (
        nested_output.get("sentence") if isinstance(nested_output, dict) else None
    )
    candidates: list[Any] = [
        data.get("text"),
        data.get("transcript"),
        output.get("text") if isinstance(output, dict) else None,
        output.get("transcript") if isinstance(output, dict) else None,
        sentence.get("text") if isinstance(sentence, dict) else None,
    ]
    choices = (
        output.get("choices") if isinstance(output, dict) else None
    ) or data.get("choices")
    if isinstance(choices, list) and choices:
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        if isinstance(message, dict):
            candidates.extend((message.get("content"), message.get("text")))
    for value in candidates:
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, list):
            texts = [
                str(item.get("text") or item.get("transcript") or "")
                for item in value
                if isinstance(item, dict)
            ]
            if any(texts):
                return "".join(texts).strip()
    raise ValueError("DashScope ASR response has no transcript")
