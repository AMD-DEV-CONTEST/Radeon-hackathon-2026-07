from dataclasses import dataclass
from typing import List, Protocol, Sequence, runtime_checkable


class EmbeddingRuntimeUnavailable(RuntimeError):
    code = "EMBEDDING_RUNTIME_UNAVAILABLE"

    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


@dataclass(frozen=True)
class EmbeddingRuntimeStatus:
    available: bool
    model_id: str
    revision: str
    dimensions: int
    execution_provider: str | None
    detail: str = ""


@dataclass(frozen=True)
class EmbeddingBatchResult:
    vectors: List[List[float]]
    model_id: str
    revision: str
    dimensions: int
    execution_provider: str
    normalized: bool
    elapsed_ms: float


@runtime_checkable
class EmbeddingRuntime(Protocol):
    def status(self) -> EmbeddingRuntimeStatus:
        ...

    def embed_batch(self, texts: Sequence[str]) -> EmbeddingBatchResult:
        ...
