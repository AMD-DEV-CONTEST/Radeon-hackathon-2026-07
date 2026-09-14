from abc import ABC, abstractmethod


class TTSProvider(ABC):
    @abstractmethod
    async def synthesize(self, text: str) -> tuple[bytes, int]:
        raise NotImplementedError
