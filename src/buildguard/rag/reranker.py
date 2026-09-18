"""Local reranking adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from buildguard.exceptions import ModelUnavailableError
from buildguard.rag.embedding_backend import lexical_tokens
from buildguard.rag.schemas import ScoredChunk


class Reranker(ABC):
    @abstractmethod
    def rerank(
        self, query: str, candidates: list[ScoredChunk], top_k: int
    ) -> list[ScoredChunk]:
        """Return candidates in descending relevance order."""


class MockReranker(Reranker):
    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled

    def rerank(
        self, query: str, candidates: list[ScoredChunk], top_k: int
    ) -> list[ScoredChunk]:
        if not self.enabled:
            return candidates[:top_k]
        query_tokens = set(lexical_tokens(query))
        rescored: list[tuple[float, ScoredChunk]] = []
        for candidate in candidates:
            content_tokens = set(lexical_tokens(candidate.chunk.content))
            lexical = (
                len(query_tokens & content_tokens) / len(query_tokens)
                if query_tokens
                else 0.0
            )
            score = 0.85 * lexical + 0.15 * min(1.0, candidate.score)
            rescored.append((score, candidate))
        rescored.sort(key=lambda item: (-item[0], item[1].chunk.chunk_id))
        return [
            ScoredChunk(
                chunk=candidate.chunk,
                score=score,
                rank=rank,
                source="reranker",
            )
            for rank, (score, candidate) in enumerate(rescored[:top_k], start=1)
        ]


class TransformersReranker(Reranker):
    """Local sequence-classification reranker with OOM CPU fallback."""

    def __init__(
        self,
        model_path: Path,
        *,
        device: str,
        batch_size: int,
        enabled: bool = True,
        architecture: str = "cross_encoder",
        revision: str | None = None,
    ) -> None:
        self.enabled = enabled
        self.batch_size = batch_size
        self.architecture = architecture
        resolved = model_path.resolve()
        if not resolved.is_dir():
            raise ModelUnavailableError(f"Local reranker model directory is missing: {resolved}")
        try:
            import torch
            from transformers import (
                AutoModelForCausalLM,
                AutoModelForSequenceClassification,
                AutoTokenizer,
            )

            self._torch = torch
            self.device = torch.device(device)
            self.cross_encoder: Any | None = None
            if architecture == "cross_encoder":
                try:
                    from sentence_transformers import CrossEncoder  # type: ignore

                    self.cross_encoder = CrossEncoder(
                        str(resolved),
                        device=str(self.device),
                        automodel_args={
                            "local_files_only": True,
                            "revision": revision,
                        },
                        tokenizer_args={
                            "local_files_only": True,
                            "revision": revision,
                        },
                    )
                    self.tokenizer = None
                    self.model = None
                    self.yes_token_id = None
                    self.no_token_id = None
                    return
                except (ImportError, OSError, TypeError, ValueError):
                    self.cross_encoder = None
            self.tokenizer = AutoTokenizer.from_pretrained(
                resolved, local_files_only=True, revision=revision
            )
            if architecture == "causal_yes_no":
                self.model = AutoModelForCausalLM.from_pretrained(
                    resolved, local_files_only=True, revision=revision
                )
                yes_tokens = self.tokenizer.encode("yes", add_special_tokens=False)
                no_tokens = self.tokenizer.encode("no", add_special_tokens=False)
                if not yes_tokens or not no_tokens:
                    raise ModelUnavailableError(
                        "Reranker tokenizer lacks yes/no tokens"
                    )
                self.yes_token_id = int(yes_tokens[-1])
                self.no_token_id = int(no_tokens[-1])
            elif architecture == "cross_encoder":
                self.model = AutoModelForSequenceClassification.from_pretrained(
                    resolved, local_files_only=True, revision=revision
                )
                self.yes_token_id = None
                self.no_token_id = None
            else:
                raise ModelUnavailableError(
                    f"Unsupported reranker architecture: {architecture}"
                )
            self.model.to(self.device)  # type: ignore[arg-type]
            self.model.eval()
        except Exception as exc:
            raise ModelUnavailableError(
                f"Failed to load local reranker model {resolved}: {exc}"
            ) from exc

    def _scores(self, query: str, candidates: list[ScoredChunk]) -> list[float]:
        torch = self._torch
        if self.cross_encoder is not None:
            cross_scores: list[float] = []
            offset = 0
            batch_size = self.batch_size
            while offset < len(candidates):
                batch = candidates[offset : offset + batch_size]
                try:
                    values = self.cross_encoder.predict(
                        [(query, item.chunk.content) for item in batch],
                        batch_size=batch_size,
                        convert_to_numpy=True,
                    )
                    cross_scores.extend(float(value) for value in values)
                    offset += len(batch)
                except RuntimeError as exc:
                    if "out of memory" not in str(exc).lower() or batch_size == 1:
                        raise
                    batch_size = max(1, batch_size // 2)
                    if self.device.type == "cuda":
                        torch.cuda.empty_cache()
            return cross_scores
        scores: list[float] = []
        if self.tokenizer is None or self.model is None:
            raise RuntimeError("Reranker model is not initialized")
        offset = 0
        batch_size = self.batch_size
        while offset < len(candidates):
            batch = candidates[offset : offset + batch_size]
            try:
                inputs: list[tuple[str, str]] | list[str]
                if self.architecture == "causal_yes_no":
                    inputs = [
                        (
                            "Judge whether the document answers the query. "
                            "Answer only yes or no.\n"
                            f"Query: {query}\nDocument: {item.chunk.content}\nAnswer:"
                        )
                        for item in batch
                    ]
                else:
                    inputs = [(query, item.chunk.content) for item in batch]
                encoded = self.tokenizer(
                    inputs,
                    padding=True,
                    truncation=True,
                    return_tensors="pt",
                )
                encoded = {key: value.to(self.device) for key, value in encoded.items()}
                with torch.no_grad():
                    logits = self.model(**encoded).logits
                    if self.architecture == "causal_yes_no":
                        if self.yes_token_id is None or self.no_token_id is None:
                            raise RuntimeError("yes/no token IDs are unavailable")
                        last = encoded["attention_mask"].sum(dim=1).sub(1)
                        rows = torch.arange(logits.shape[0], device=self.device)
                        next_token = logits[rows, last]
                        pair_logits = torch.stack(
                            [
                                next_token[:, self.no_token_id],
                                next_token[:, self.yes_token_id],
                            ],
                            dim=-1,
                        )
                        values = torch.softmax(pair_logits, dim=-1)[:, 1]
                    elif logits.shape[-1] == 1:
                        values = torch.sigmoid(logits[:, 0])
                    else:
                        values = torch.softmax(logits, dim=-1)[:, -1]
                scores.extend(float(value) for value in values.detach().cpu().tolist())
                offset += len(batch)
            except RuntimeError as exc:
                if "out of memory" not in str(exc).lower() or batch_size == 1:
                    raise
                batch_size = max(1, batch_size // 2)
                if self.device.type == "cuda":
                    torch.cuda.empty_cache()
        return scores

    def rerank(
        self, query: str, candidates: list[ScoredChunk], top_k: int
    ) -> list[ScoredChunk]:
        if not self.enabled:
            return candidates[:top_k]
        scores = self._scores(query, candidates)
        ordered = sorted(
            zip(scores, candidates),
            key=lambda item: (-item[0], item[1].chunk.chunk_id),
        )
        return [
            ScoredChunk(
                chunk=candidate.chunk,
                score=score,
                rank=rank,
                source="reranker",
            )
            for rank, (score, candidate) in enumerate(ordered[:top_k], start=1)
        ]
