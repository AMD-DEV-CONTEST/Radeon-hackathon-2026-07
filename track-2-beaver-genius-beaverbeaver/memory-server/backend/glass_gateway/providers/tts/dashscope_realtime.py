import asyncio
import base64
import json
import uuid

import websockets

from glass_gateway.config import Settings
from glass_gateway.providers.tts.base import TTSProvider


class DashScopeRealtimeTTSProvider(TTSProvider):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def synthesize(self, text: str) -> tuple[bytes, int]:
        if not text or not self.settings.dashscope_api_key:
            return b"", self.settings.dashscope_tts_sample_rate

        url = f"{self.settings.dashscope_base_url}?model={self.settings.dashscope_tts_model}"
        audio = bytearray()
        sample_rate = self.settings.dashscope_tts_sample_rate

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
                                "voice": self.settings.dashscope_tts_voice,
                                "mode": "server_commit",
                                "language_type": "Chinese",
                                "response_format": "pcm",
                                "sample_rate": self.settings.dashscope_tts_sample_rate,
                            },
                        }
                    )
                )
                await ws.send(
                    json.dumps(
                        {
                            "event_id": f"event_{uuid.uuid4().hex}",
                            "type": "input_text_buffer.append",
                            "text": text,
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
                    if msg_type in {"session.created", "session.updated"}:
                        session = data.get("session") or {}
                        if isinstance(session.get("sample_rate"), int):
                            sample_rate = int(session["sample_rate"])
                    if msg_type == "response.audio.delta":
                        chunk = data.get("delta") or data.get("audio") or ""
                        if chunk:
                            audio.extend(base64.b64decode(chunk))
                    elif msg_type == "session.finished":
                        break
                    elif msg_type == "error":
                        return b"", sample_rate
        except Exception:
            return b"", sample_rate

        return bytes(audio), sample_rate
