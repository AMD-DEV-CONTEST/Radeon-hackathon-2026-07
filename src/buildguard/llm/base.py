"""Language model backend contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator, Sequence
from typing import Literal, TypeVar

from pydantic import BaseModel

from buildguard.llm.token_metrics import ChatResponse

StructuredT = TypeVar("StructuredT", bound=BaseModel)
GenerationProfileName = Literal[
    "structured_plan", "normal_dialogue", "complex_replan"
]


class ChatMessage(BaseModel):
    role: str
    content: str


class LocalLLMBackend(ABC):
    """Only local implementations may satisfy this interface."""

    @abstractmethod
    def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        thinking: bool = False,
        profile: GenerationProfileName | None = None,
    ) -> ChatResponse:
        """Return one complete response."""

    @abstractmethod
    def stream_chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        thinking: bool = False,
        profile: GenerationProfileName | None = None,
    ) -> Iterator[str]:
        """Yield visible response text only."""

    @abstractmethod
    def structured_chat(
        self,
        messages: Sequence[ChatMessage],
        schema: type[StructuredT],
        *,
        thinking: bool = False,
        profile: GenerationProfileName | None = None,
    ) -> StructuredT:
        """Return a schema-validated response."""

    @abstractmethod
    def health_check(self) -> bool:
        """Report whether the configured local backend is usable."""
