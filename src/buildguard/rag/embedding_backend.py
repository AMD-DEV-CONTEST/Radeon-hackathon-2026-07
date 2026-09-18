"""Local embedding adapters."""

from __future__ import annotations

import hashlib
import os
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import cast

import numpy as np
from numpy.typing import NDArray

from buildguard.exceptions import ModelUnavailableError

TOKEN_PATTERN = re.compile(r"[\u4e00-\u9fff]|[a-zA-Z0-9_]+")


def lexical_tokens(text: str) -> list[str]:
    raw = TOKEN_PATTERN.findall(text.lower())
    chinese = [token for token in raw if len(token) == 1 and "\u4e00" <= token <= "\u9fff"]
    bigrams = [chinese[index] + chinese[index + 1] for index in range(len(chinese) - 1)]
    return raw + bigrams


class EmbeddingBackend(ABC):
    @property
    @abstractmethod
    def dimension(self) -> int:
        """Embedding vector width."""

    @abstractmethod
    def encode(self, texts: list[str]) -> NDArray[np.float32]:
        """Return normalized float32 vectors."""

    def encode_queries(self, texts: list[str]) -> NDArray[np.float32]:
        """Encode retrieval queries; adapters may add a query instruction."""
        return self.encode(texts)


class MockEmbeddingBackend(EmbeddingBackend):
    """Deterministic feature hashing for offline program tests."""

    def __init__(self, dimension: int = 128, seed: int = 42) -> None:
        if dimension < 8:
            raise ValueError("Mock embedding dimension must be at least 8")
        self._dimension = dimension
        self.seed = seed

    @property
    def dimension(self) -> int:
        return self._dimension

    def encode(self, texts: list[str]) -> NDArray[np.float32]:
        vectors = np.zeros((len(texts), self.dimension), dtype=np.float32)
        for row, text in enumerate(texts):
            for token in lexical_tokens(text):
                digest = hashlib.sha256(f"{self.seed}:{token}".encode()).digest()
                index = int.from_bytes(digest[:4], "little") % self.dimension
                sign = 1.0 if digest[4] % 2 == 0 else -1.0
                vectors[row, index] += sign
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        np.divide(vectors, norms, out=vectors, where=norms > 0)
        return vectors


class TransformersEmbeddingBackend(EmbeddingBackend):
    """Load an embedding-compatible Transformers model from local disk only."""

    def __init__(
        self,
        model_path: Path,
        *,
        device: str,
        batch_size: int,
        normalize: bool = True,
        query_instruction: str = "Represent this query for retrieval:",
        revision: str | None = None,
        tokenizer_revision: str | None = None,
    ) -> None:
        resolved = model_path.resolve()
        if not resolved.is_dir():
            raise ModelUnavailableError(f"Local embedding model directory is missing: {resolved}")
        try:
            import torch

            self._torch = torch
            self.device = torch.device(device)
            self._sentence_model: object | None = None
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
            os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
            try:
                from sentence_transformers import (  # type: ignore[import-not-found]
                    SentenceTransformer,
                )

                sentence_model = SentenceTransformer(
                    str(resolved),
                    device=device,
                    local_files_only=True,
                    revision=revision,
                )
                self._sentence_model = sentence_model
                self._dimension = int(sentence_model.get_sentence_embedding_dimension())
                self.tokenizer = None
                self.model = None
            except (ImportError, OSError, RuntimeError, ValueError):
                from transformers import AutoModel, AutoTokenizer

                self.tokenizer = AutoTokenizer.from_pretrained(
                    resolved,
                    local_files_only=True,
                    revision=tokenizer_revision,
                )
                self.model = AutoModel.from_pretrained(
                    resolved,
                    local_files_only=True,
                    revision=revision,
                )
                self.model.to(self.device)
                self.model.eval()
                hidden_size = getattr(self.model.config, "hidden_size", None)
                if not isinstance(hidden_size, int):
                    raise ModelUnavailableError(
                        "Embedding model config has no integer hidden_size"
                    )
                self._dimension = hidden_size
        except ModelUnavailableError:
            raise
        except Exception as exc:
            raise ModelUnavailableError(
                f"Failed to load local embedding model {resolved}: {exc}"
            ) from exc
        self.batch_size = batch_size
        self.normalize = normalize
        self.query_instruction = query_instruction.strip()

    @property
    def dimension(self) -> int:
        return self._dimension

    def _encode_batch(self, texts: list[str]) -> NDArray[np.float32]:
        if self._sentence_model is not None:
            sentence_model = self._sentence_model
            vectors = sentence_model.encode(  # type: ignore[attr-defined]
                texts,
                batch_size=len(texts),
                convert_to_numpy=True,
                normalize_embeddings=self.normalize,
                show_progress_bar=False,
            )
            return np.asarray(vectors, dtype=np.float32)
        torch = self._torch
        if self.tokenizer is None or self.model is None:
            raise ModelUnavailableError("Embedding backend did not load a local model")
        encoded = self.tokenizer(
            texts,
            padding=True,
            truncation=True,
            return_tensors="pt",
        )
        encoded = {key: value.to(self.device) for key, value in encoded.items()}
        with torch.no_grad():
            output = self.model(**encoded)
            hidden = output.last_hidden_state
            attention = encoded["attention_mask"]
            last_indexes = attention.sum(dim=1).sub(1).clamp(min=0)
            row_indexes = torch.arange(hidden.shape[0], device=hidden.device)
            pooled = hidden[row_indexes, last_indexes]
            if self.normalize:
                pooled = torch.nn.functional.normalize(pooled, p=2, dim=1)
        return cast(
            NDArray[np.float32],
            pooled.detach().cpu().to(torch.float32).numpy(),
        )

    def encode(self, texts: list[str]) -> NDArray[np.float32]:
        if not texts:
            return np.empty((0, self.dimension), dtype=np.float32)
        results: list[NDArray[np.float32]] = []
        offset = 0
        batch_size = self.batch_size
        while offset < len(texts):
            batch = texts[offset : offset + batch_size]
            try:
                results.append(self._encode_batch(batch))
                offset += len(batch)
            except RuntimeError as exc:
                if "out of memory" not in str(exc).lower() or batch_size == 1:
                    raise
                batch_size = max(1, batch_size // 2)
                if self.device.type == "cuda":
                    self._torch.cuda.empty_cache()
        return cast(
            NDArray[np.float32],
            np.concatenate(results, axis=0).astype(np.float32, copy=False),
        )

    def encode_queries(self, texts: list[str]) -> NDArray[np.float32]:
        instructed = [
            f"{self.query_instruction} {text}" if self.query_instruction else text
            for text in texts
        ]
        return self.encode(instructed)
