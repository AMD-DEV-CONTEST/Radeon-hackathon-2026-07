from __future__ import annotations

import base64
import io
import wave

import httpx

from .base import ASRProvider


class MimoASRProvider(ASRProvider):
    """MiMo-V2.5-ASR adapter following Xiaomi's OpenAI-compatible contract."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://asr-service.example/v1",
        model: str = "mimo-v2.5-asr",
        language: str = "auto",
        timeout_seconds: float = 60.0,
    ) -> None:
        if not api_key.strip():
            raise ValueError("MiMo API key is required")
        if language not in {"auto", "zh", "en"}:
            raise ValueError(f"unsupported MiMo ASR language: {language}")
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.language = language
        self.timeout_seconds = timeout_seconds

    @property
    def provider_name(self) -> str:
        return "mimo"

    @property
    def model_name(self) -> str:
        return self.model

    async def transcribe(self, pcm_bytes: bytes, sample_rate: int) -> str:
        return await self.transcribe_live(pcm_bytes, sample_rate)

    async def transcribe_live(self, pcm_bytes: bytes, sample_rate: int) -> str:
        if not pcm_bytes:
            return ""
        wav_bytes = _pcm16_to_wav(pcm_bytes, sample_rate)
        audio_data = base64.b64encode(wav_bytes).decode("ascii")
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_audio",
                            "input_audio": {
                                "data": f"data:audio/wav;base64,{audio_data}",
                            },
                        }
                    ],
                }
            ],
            "asr_options": {"language": self.language},
        }
        async with httpx.AsyncClient(timeout=self.timeout_seconds, trust_env=False) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"api-key": self.api_key, "Content-Type": "application/json"},
                json=payload,
            )
        response.raise_for_status()
        return _extract_completion_text(response.json())


def _pcm16_to_wav(pcm_bytes: bytes, sample_rate: int) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_bytes)
    return output.getvalue()


def _extract_completion_text(data: object) -> str:
    if not isinstance(data, dict):
        raise ValueError("MiMo ASR returned a non-object response")
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("MiMo ASR response has no choices")
    choice = choices[0]
    if not isinstance(choice, dict):
        raise ValueError("MiMo ASR choice is invalid")
    message = choice.get("message")
    if not isinstance(message, dict):
        raise ValueError("MiMo ASR response has no message")
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        texts: list[str] = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                texts.append(item["text"])
        return "".join(texts).strip()
    raise ValueError("MiMo ASR response content is invalid")
