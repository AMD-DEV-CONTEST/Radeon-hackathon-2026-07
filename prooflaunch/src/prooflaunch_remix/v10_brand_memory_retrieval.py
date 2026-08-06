from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Mapping, Sequence

from .v10_brand_memory import (
    BrandGenomeMemory,
    EntityKind,
    MemoryAtom,
    MemoryKind,
    PrivacyClass,
)
from .v10_contracts import V10ContractError, stable_digest


class RetrievalMode(str, Enum):
    ENTITY_CENTRIC = "entity_centric"
    SYMBOLIC = "symbolic"
    NEURAL = "neural"
    HYBRID = "hybrid"
    VECTOR_ONLY = "vector_only_ablation"
    NO_MEMORY = "no_memory_ablation"


@dataclass(frozen=True)
class DenseEmbeddingIndex:
    model_id: str
    model_revision: str
    vectors: Mapping[str, tuple[float, ...]]
    observed_neural_inference: bool
    schema: str = "ProofLaunchDenseEmbeddingIndexV1"

    def __post_init__(self) -> None:
        if not self.model_id.strip() or not self.model_revision.strip():
            raise V10ContractError("dense index requires model id and revision")
        if not self.vectors:
            raise V10ContractError("dense index requires vectors")
        dimensions = {len(vector) for vector in self.vectors.values()}
        if len(dimensions) != 1 or next(iter(dimensions)) < 2:
            raise V10ContractError("dense vectors require one shared dimension >=2")
        for vector in self.vectors.values():
            if any(not math.isfinite(value) for value in vector):
                raise V10ContractError("dense vectors must be finite")
            if math.sqrt(sum(value * value for value in vector)) == 0:
                raise V10ContractError("dense vectors cannot be zero")

    @property
    def dimension(self) -> int:
        return len(next(iter(self.vectors.values())))

    @property
    def content_sha256(self) -> str:
        return stable_digest(asdict(self))

    def rank(
        self,
        query_vector: Sequence[float],
        candidates: Sequence[MemoryAtom],
    ) -> tuple[tuple[str, float], ...]:
        if len(query_vector) != self.dimension:
            raise V10ContractError("query vector dimension does not match dense index")
        query_norm = math.sqrt(sum(value * value for value in query_vector))
        if query_norm == 0 or any(not math.isfinite(value) for value in query_vector):
            raise V10ContractError("query vector must be finite and nonzero")
        scored: list[tuple[str, float]] = []
        for atom in candidates:
            vector = self.vectors.get(atom.atom_id)
            if vector is None:
                continue
            vector_norm = math.sqrt(sum(value * value for value in vector))
            cosine = sum(
                left * right for left, right in zip(query_vector, vector, strict=True)
            ) / (query_norm * vector_norm)
            scored.append((atom.atom_id, cosine))
        return tuple(sorted(scored, key=lambda item: (-item[1], item[0])))


@dataclass(frozen=True)
class HybridFusionConfig:
    entity_weight: float = 1.0
    symbolic_weight: float = 1.1
    neural_weight: float = 1.0
    rrf_k: int = 60
    schema: str = "ProofLaunchHybridFusionConfigV1"

    def __post_init__(self) -> None:
        weights = (self.entity_weight, self.symbolic_weight, self.neural_weight)
        if any(not math.isfinite(value) or value <= 0 for value in weights):
            raise V10ContractError("fusion weights must be finite and positive")
        if self.rrf_k < 1:
            raise V10ContractError("rrf_k must be positive")

    @property
    def content_sha256(self) -> str:
        return stable_digest(asdict(self))


@dataclass(frozen=True)
class MemoryRetrievalRequest:
    request_id: str
    query_text: str
    query_vector: tuple[float, ...]
    now: str
    brand_id: str
    campaign_id: str
    subject_ids: tuple[str, ...] = ()
    entity_kinds: tuple[EntityKind, ...] = ()
    requester_role: str = "worker"
    maximum_privacy: PrivacyClass = PrivacyClass.INTERNAL
    minimum_confidence: float = 0.0
    max_context_tokens: int = 64
    top_k: int = 4
    schema: str = "ProofLaunchMemoryRetrievalRequestV1"

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (
                self.request_id,
                self.query_text,
                self.brand_id,
                self.campaign_id,
                self.requester_role,
            )
        ):
            raise V10ContractError("retrieval request identity and scope are required")
        if self.top_k < 1 or self.max_context_tokens < 1:
            raise V10ContractError("retrieval top_k and context budget must be positive")
        if not 0 <= self.minimum_confidence <= 1:
            raise V10ContractError("minimum_confidence must be in [0, 1]")


@dataclass(frozen=True)
class RankedMemory:
    atom_id: str
    score: float
    channels: tuple[str, ...]
    token_cost: int
    schema: str = "ProofLaunchRankedMemoryV1"


@dataclass(frozen=True)
class MemoryRetrievalResult:
    request_id: str
    mode: RetrievalMode
    ranked: tuple[RankedMemory, ...]
    active_candidate_count: int
    full_context_tokens: int
    retrieved_context_tokens: int
    context_saving_rate: float
    dense_index_sha256: str | None
    neural_inference_observed: bool
    fusion_config_sha256: str | None
    schema: str = "ProofLaunchMemoryRetrievalResultV1"

    @property
    def atom_ids(self) -> tuple[str, ...]:
        return tuple(item.atom_id for item in self.ranked)

    @property
    def content_sha256(self) -> str:
        return stable_digest(asdict(self))


_TOKEN = re.compile(r"[a-z0-9]+")


def _terms(value: object) -> set[str]:
    return set(_TOKEN.findall(json.dumps(value, ensure_ascii=False).lower()))


class BrandMemoryRetriever:
    """Fail-closed graph/dense hybrid retriever with frozen rank fusion.

    Dense vectors are injected through a revisioned index. The runtime never
    claims that synthetic fixture vectors were produced by a neural encoder.
    """

    def __init__(
        self,
        graph: BrandGenomeMemory,
        dense_index: DenseEmbeddingIndex,
        fusion: HybridFusionConfig = HybridFusionConfig(),
    ) -> None:
        self.graph = graph
        self.dense_index = dense_index
        self.fusion = fusion

    @staticmethod
    def _scope_allowed(atom: MemoryAtom, request: MemoryRetrievalRequest) -> bool:
        atom_brand = str(atom.payload.get("brand_id", ""))
        atom_campaign = str(atom.payload.get("campaign_id", ""))
        scope = str(atom.payload.get("scope", "campaign"))
        if atom_brand and atom_brand != request.brand_id:
            return False
        if scope == "brand_global":
            return True
        return not atom_campaign or atom_campaign == request.campaign_id

    def _active_candidates(
        self,
        request: MemoryRetrievalRequest,
        *,
        apply_brand_scope: bool,
    ) -> tuple[MemoryAtom, ...]:
        active = self.graph.retrieve(
            now=request.now,
            minimum_confidence=request.minimum_confidence,
            requester_role=request.requester_role,
            maximum_privacy=request.maximum_privacy,
        )
        if not apply_brand_scope:
            return active
        return tuple(atom for atom in active if self._scope_allowed(atom, request))

    @staticmethod
    def _entity_rank(
        request: MemoryRetrievalRequest,
        candidates: Sequence[MemoryAtom],
    ) -> tuple[tuple[str, float], ...]:
        query_terms = _terms(request.query_text)
        wanted_subjects = set(request.subject_ids)
        wanted_entities = set(request.entity_kinds)
        ranked: list[tuple[str, float]] = []
        for atom in candidates:
            exact_subject = 1.0 if atom.subject_id in wanted_subjects else 0.0
            entity_match = 1.0 if atom.entity_kind in wanted_entities else 0.0
            overlap = len(query_terms & _terms(atom.payload)) / max(1, len(query_terms))
            graph_scope = 0.25 if atom.payload.get("scope") == "brand_global" else 0.0
            score = 2.0 * exact_subject + 1.5 * entity_match + overlap + graph_scope
            if score > 0:
                ranked.append((atom.atom_id, score))
        return tuple(sorted(ranked, key=lambda item: (-item[1], item[0])))

    @staticmethod
    def _symbolic_rank(
        request: MemoryRetrievalRequest,
        candidates: Sequence[MemoryAtom],
    ) -> tuple[tuple[str, float], ...]:
        query_terms = _terms(request.query_text)
        ranked: list[tuple[str, float]] = []
        for atom in candidates:
            if atom.kind != MemoryKind.SYMBOLIC_RULE:
                continue
            declared_topic = str(atom.payload.get("topic", "")).lower()
            if declared_topic and declared_topic not in query_terms:
                continue
            overlap = len(query_terms & _terms(atom.payload)) / max(1, len(query_terms))
            scope_bonus = 1.0 if atom.payload.get("scope") == "brand_global" else 0.0
            ranked.append((atom.atom_id, overlap + scope_bonus + atom.confidence))
        return tuple(sorted(ranked, key=lambda item: (-item[1], item[0])))

    @staticmethod
    def _truncate(
        ranked: Sequence[tuple[str, float, tuple[str, ...]]],
        by_id: Mapping[str, MemoryAtom],
        request: MemoryRetrievalRequest,
    ) -> tuple[RankedMemory, ...]:
        selected: list[RankedMemory] = []
        used = 0
        for atom_id, score, channels in ranked:
            atom = by_id[atom_id]
            if used + atom.token_cost > request.max_context_tokens:
                continue
            selected.append(RankedMemory(atom_id, score, channels, atom.token_cost))
            used += atom.token_cost
            if len(selected) == request.top_k:
                break
        return tuple(selected)

    def retrieve(
        self,
        request: MemoryRetrievalRequest,
        mode: RetrievalMode,
    ) -> MemoryRetrievalResult:
        scoped = mode != RetrievalMode.VECTOR_ONLY
        candidates = self._active_candidates(request, apply_brand_scope=scoped)
        by_id = {atom.atom_id: atom for atom in candidates}
        full_context_tokens = sum(atom.token_cost for atom in candidates)
        entity = self._entity_rank(request, candidates)
        symbolic = self._symbolic_rank(request, candidates)
        neural = self.dense_index.rank(request.query_vector, candidates)

        if mode == RetrievalMode.NO_MEMORY:
            raw: tuple[tuple[str, float, tuple[str, ...]], ...] = ()
        elif mode == RetrievalMode.ENTITY_CENTRIC:
            raw = tuple((atom_id, score, ("entity",)) for atom_id, score in entity)
        elif mode == RetrievalMode.SYMBOLIC:
            raw = tuple((atom_id, score, ("symbolic",)) for atom_id, score in symbolic)
        elif mode in {RetrievalMode.NEURAL, RetrievalMode.VECTOR_ONLY}:
            raw = tuple((atom_id, score, ("dense",)) for atom_id, score in neural)
        elif mode == RetrievalMode.HYBRID:
            channel_rankings = (
                ("entity", self.fusion.entity_weight, entity),
                ("symbolic", self.fusion.symbolic_weight, symbolic),
                ("dense", self.fusion.neural_weight, neural),
            )
            scores: dict[str, float] = {}
            channels: dict[str, set[str]] = {}
            for channel, weight, ranking in channel_rankings:
                for rank, (atom_id, _) in enumerate(ranking, start=1):
                    scores[atom_id] = scores.get(atom_id, 0.0) + weight / (
                        self.fusion.rrf_k + rank
                    )
                    channels.setdefault(atom_id, set()).add(channel)
            raw = tuple(
                (
                    atom_id,
                    score
                    + 1e-6
                    * by_id[atom_id].utility
                    * by_id[atom_id].confidence
                    / math.sqrt(by_id[atom_id].token_cost),
                    tuple(sorted(channels[atom_id])),
                )
                for atom_id, score in sorted(
                    scores.items(), key=lambda item: (-item[1], item[0])
                )
            )
        else:  # pragma: no cover - Enum exhaustiveness guard
            raise V10ContractError("unknown retrieval mode")

        selected = self._truncate(raw, by_id, request)
        retrieved_tokens = sum(item.token_cost for item in selected)
        saving = (
            1.0
            if full_context_tokens == 0
            else 1.0 - retrieved_tokens / full_context_tokens
        )
        uses_dense = mode in {
            RetrievalMode.NEURAL,
            RetrievalMode.HYBRID,
            RetrievalMode.VECTOR_ONLY,
        }
        return MemoryRetrievalResult(
            request_id=request.request_id,
            mode=mode,
            ranked=selected,
            active_candidate_count=len(candidates),
            full_context_tokens=full_context_tokens,
            retrieved_context_tokens=retrieved_tokens,
            context_saving_rate=saving,
            dense_index_sha256=self.dense_index.content_sha256 if uses_dense else None,
            neural_inference_observed=(
                self.dense_index.observed_neural_inference if uses_dense else False
            ),
            fusion_config_sha256=(
                self.fusion.content_sha256 if mode == RetrievalMode.HYBRID else None
            ),
        )
