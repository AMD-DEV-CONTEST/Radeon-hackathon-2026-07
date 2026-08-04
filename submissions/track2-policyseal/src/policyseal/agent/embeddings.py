from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Protocol

from fastembed import TextEmbedding
from fastembed.common.model_description import ModelSource, PoolingType


class TextEncoder(Protocol):
    def encode_passages(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]: ...

    def encode_query(self, text: str) -> tuple[float, ...]: ...


class FastEmbedTextEncoder:
    """Lazy local ONNX encoder for the frozen, small policy corpus."""

    _registered_name = "policyseal/intfloat-multilingual-e5-small"

    def __init__(
        self,
        *,
        source_model: str = "intfloat/multilingual-e5-small",
        cache_dir: Path | None = None,
        local_files_only: bool = False,
    ) -> None:
        self.source_model = source_model
        self.cache_dir = cache_dir
        self.local_files_only = local_files_only
        self._model: TextEmbedding | None = None

    def encode_passages(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        return self._encode(f"passage: {text}" for text in texts)

    def encode_query(self, text: str) -> tuple[float, ...]:
        encoded = self._encode((f"query: {text}",))
        return encoded[0]

    def _encode(self, texts: Iterable[str]) -> tuple[tuple[float, ...], ...]:
        model = self._get_model()
        return tuple(tuple(float(value) for value in vector) for vector in model.embed(list(texts)))

    def _get_model(self) -> TextEmbedding:
        if self._model is not None:
            return self._model
        supported = {item["model"].casefold() for item in TextEmbedding.list_supported_models()}
        if self._registered_name.casefold() not in supported:
            TextEmbedding.add_custom_model(
                model=self._registered_name,
                pooling=PoolingType.MEAN,
                normalization=True,
                sources=ModelSource(hf=self.source_model),
                dim=384,
                model_file="onnx/model.onnx",
                description="PolicySeal local multilingual E5 evidence encoder",
                license="mit",
                size_in_gb=0.47,
            )
        self._model = TextEmbedding(
            model_name=self._registered_name,
            cache_dir=str(self.cache_dir) if self.cache_dir is not None else None,
            lazy_load=True,
            local_files_only=self.local_files_only,
        )
        return self._model


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or not left:
        return 0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0
    return dot / (left_norm * right_norm)


__all__ = ["FastEmbedTextEncoder", "TextEncoder", "cosine_similarity"]
