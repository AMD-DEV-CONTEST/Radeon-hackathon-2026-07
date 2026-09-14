from abc import ABC, abstractmethod


class ASRProvider(ABC):
    @abstractmethod
    async def transcribe(self, pcm_bytes: bytes, sample_rate: int) -> str:
        raise NotImplementedError
