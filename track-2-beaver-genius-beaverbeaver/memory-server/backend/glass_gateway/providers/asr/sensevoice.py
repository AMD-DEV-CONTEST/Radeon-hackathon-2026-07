from __future__ import annotations

import asyncio
import re

from .base import ASRProvider


class SenseVoiceASRProvider(ASRProvider):
    """Local FunASR SenseVoiceSmall provider used as a reproducible baseline."""

    def __init__(
        self,
        *,
        model_id: str = "iic/SenseVoiceSmall",
        model_revision: str,
        device: str = "cuda:0",
    ) -> None:
        if not model_revision:
            raise ValueError("SenseVoice model revision must be pinned")
        try:
            from funasr import AutoModel
        except ImportError as exc:
            raise RuntimeError("SenseVoice requires the isolated ASR evaluation environment") from exc

        self.model_id = model_id
        self.model_revision = model_revision
        self.device = device
        self._model = AutoModel(
            model=model_id,
            model_revision=model_revision,
            device=device,
            disable_update=True,
            check_latest=False,
            disable_pbar=True,
        )

    async def transcribe(self, pcm_bytes: bytes, sample_rate: int) -> str:
        return await self.transcribe_live(pcm_bytes, sample_rate)

    async def transcribe_live(self, pcm_bytes: bytes, sample_rate: int) -> str:
        if not pcm_bytes:
            return ""
        if sample_rate != 16_000:
            raise ValueError(f"SenseVoice baseline expects 16 kHz PCM, got {sample_rate}")
        return await asyncio.to_thread(self._generate, pcm_bytes)

    def _generate(self, pcm_bytes: bytes) -> str:
        import numpy as np

        audio = np.frombuffer(pcm_bytes, dtype="<i2").astype("float32") / 32768.0
        result = self._model.generate(
            input=audio,
            language="auto",
            use_itn=True,
            batch_size_s=60,
        )
        if not result or not isinstance(result[0], dict):
            raise ValueError("SenseVoice returned no result")
        text = result[0].get("text")
        if not isinstance(text, str):
            raise ValueError("SenseVoice result has no text")
        return clean_sensevoice_text(text)


def clean_sensevoice_text(text: str) -> str:
    return re.sub(r"<\|[^|>]+\|>", "", text).strip()
