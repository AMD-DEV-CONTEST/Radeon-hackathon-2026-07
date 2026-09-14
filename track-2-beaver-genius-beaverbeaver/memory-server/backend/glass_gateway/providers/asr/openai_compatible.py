from glass_gateway.config import Settings
from glass_gateway.providers.asr.base import ASRProvider

import base64
import io
import wave
import asyncio
import json
import uuid

import httpx
import websockets


class OpenAICompatibleASRProvider(ASRProvider):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def transcribe(self, pcm_bytes: bytes, sample_rate: int) -> str:
        text = await self.transcribe_live(pcm_bytes, sample_rate)
        if text:
            return text
        return self.settings.asr_fixed_text

    async def transcribe_live(self, pcm_bytes: bytes, sample_rate: int) -> str:
        if not pcm_bytes:
            return ""
        if self.settings.dashscope_api_key:
            text = await self._transcribe_dashscope_realtime(pcm_bytes, sample_rate)
            if text:
                return text
        if self.settings.asr_base_url:
            text = await self._transcribe_blackbox(pcm_bytes, sample_rate)
            if text:
                return text
        return ""

    async def transcribe_live_strict(self, pcm_bytes: bytes, sample_rate: int) -> str:
        """Transcribe without hiding transport/provider failures.

        An empty successful response means speech was present but could not be
        recognized. A raised exception means the ASR service itself failed.
        """
        if not pcm_bytes:
            return ""
        if self.settings.dashscope_api_key:
            return await self._transcribe_dashscope_realtime(
                pcm_bytes,
                sample_rate,
                strict=True,
            )
        if self.settings.asr_base_url:
            return await self._transcribe_blackbox(
                pcm_bytes,
                sample_rate,
                strict=True,
            )
        raise RuntimeError("no live ASR provider is configured")

    async def _transcribe_dashscope_realtime(
        self,
        pcm_bytes: bytes,
        sample_rate: int,
        *,
        strict: bool = False,
    ) -> str:
        url = f"{self.settings.dashscope_base_url}?model={self.settings.dashscope_asr_model}"
        texts: list[str] = []
        chunk_size = 3200

        try:
            async with websockets.connect(
                url,
                additional_headers={
                    "Authorization": f"Bearer {self.settings.dashscope_api_key}",
                    "OpenAI-Beta": "realtime=v1",
                },
                open_timeout=15,
                close_timeout=5,
                max_size=8 * 1024 * 1024,
            ) as ws:
                await ws.send(
                    json.dumps(
                        {
                            "event_id": f"event_{uuid.uuid4().hex}",
                            "type": "session.update",
                            "session": {
                                "modalities": ["text"],
                                "input_audio_format": "pcm",
                                "sample_rate": sample_rate,
                                "input_audio_transcription": {"language": "zh"},
                            },
                        }
                    )
                )
                await asyncio.sleep(0.2)

                for offset in range(0, len(pcm_bytes), chunk_size):
                    chunk = pcm_bytes[offset : offset + chunk_size]
                    await ws.send(
                        json.dumps(
                            {
                                "event_id": f"event_{uuid.uuid4().hex}",
                                "type": "input_audio_buffer.append",
                                "audio": base64.b64encode(chunk).decode(),
                            }
                        )
                    )
                    await asyncio.sleep(0.05)

                await ws.send(
                    json.dumps(
                        {
                            "event_id": f"event_{uuid.uuid4().hex}",
                            "type": "input_audio_buffer.commit",
                        }
                    )
                )
                await ws.send(
                    json.dumps(
                        {
                            "event_id": f"event_{uuid.uuid4().hex}",
                            "type": "session.finish",
                        }
                    )
                )

                while True:
                    raw = await asyncio.wait_for(ws.recv(), timeout=30)
                    if isinstance(raw, bytes):
                        continue
                    data = json.loads(raw)
                    msg_type = data.get("type")
                    if msg_type == "conversation.item.input_audio_transcription.completed":
                        text = data.get("transcript") or data.get("text") or ""
                        if text:
                            texts.append(text)
                    elif msg_type == "session.finished":
                        break
                    elif msg_type == "error":
                        if strict:
                            raise RuntimeError(f"DashScope ASR error: {data}")
                        return ""
        except Exception:
            if strict:
                raise
            return ""

        return "".join(texts).strip()

    async def _transcribe_blackbox(
        self,
        pcm_bytes: bytes,
        sample_rate: int,
        *,
        strict: bool = False,
    ) -> str:
        wav_bytes = _pcm16_to_wav(pcm_bytes, sample_rate=sample_rate, channels=1)
        headers = {}
        if self.settings.asr_api_key:
            headers["Authorization"] = f"Bearer {self.settings.asr_api_key}"

        try:
            openai_endpoint = self.settings.asr_base_url.rstrip("/").endswith(
                "/audio/transcriptions"
            )
            if openai_endpoint:
                data = {"model": self.settings.asr_model or "sensevoice"}
                files = {"file": ("audio.wav", wav_bytes, "audio/wav")}
            else:
                data = {"sample_rate": str(sample_rate), "encoding": "pcm_s16le"}
                if self.settings.asr_model:
                    data["model_name"] = self.settings.asr_model
                files = {"audio": ("audio.wav", wav_bytes, "audio/wav")}
            async with httpx.AsyncClient(timeout=20.0, trust_env=False) as client:
                response = await client.post(
                    self.settings.asr_base_url,
                    headers=headers,
                    files=files,
                    data=data,
                )
            response.raise_for_status()
        except Exception:
            if strict:
                raise
            return ""

        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            try:
                data = response.json()
            except ValueError:
                if strict:
                    raise ValueError("ASR provider returned invalid JSON")
                return ""
            return _extract_text(data)
        return response.text.strip()


def _pcm16_to_wav(pcm_bytes: bytes, sample_rate: int, channels: int) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm_bytes)
    return out.getvalue()


def _extract_text(data) -> str:
    if isinstance(data, str):
        return data.strip()
    if not isinstance(data, dict):
        return ""
    for key in ("text", "transcript", "result", "answer"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    nested = data.get("data")
    if isinstance(nested, dict):
        return _extract_text(nested)
    return ""
