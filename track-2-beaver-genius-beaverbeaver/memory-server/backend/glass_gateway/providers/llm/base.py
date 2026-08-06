from abc import ABC, abstractmethod


class LLMProvider(ABC):
    @abstractmethod
    async def complete(self, text: str) -> str:
        raise NotImplementedError
