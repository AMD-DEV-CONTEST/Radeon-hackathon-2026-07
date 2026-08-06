from abc import ABC, abstractmethod
from typing import Any


class AIProvider(ABC):
    """Provider-independent interface for future local/GPU AI runtimes."""

    @abstractmethod
    async def health(self) -> dict[str, Any]:
        raise NotImplementedError
