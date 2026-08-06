"""Repository interface that makes retrieval scope explicit and testable."""

from __future__ import annotations

import hashlib
from typing import Protocol
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from app.experience_asset.domain.enums import RetrievalScope
from app.experience_asset.domain.models import ContractModel, NonEmptyText
from app.experience_asset.persistence import AssetNotFoundError, SQLiteAssetRepository
from app.experience_asset.role_graph import normalize_lexical_text


class RetrievalRequest(ContractModel):
    """One scoped retrieval request.

    The three scopes take different inputs, and the rule is encoded here so a
    mismatch fails at validation rather than reaching the repository:

    - `CURRENT_SOURCE` takes a free-text query. Searching one's own sources is
      genuinely a query operation.
    - `CROSS_ASSET_SUMMARY` takes a Runtime-owned discovery intent instead. A
      user- or model-supplied query would let the same pair of assets yield
      different relations under different phrasings, so a durable relation would
      degrade into what one sentence returned once.
    - `CROSS_ASSET_DETAIL` takes neither. The readable set is computed from the
      confirmed relation and its validated mapping package, so any tunable would
      mean one confirmation could read different things on different calls.
    """

    retrieval_id: UUID
    scope: RetrievalScope
    current_asset_id: UUID
    current_version_id: UUID
    query: NonEmptyText | None = None
    discovery_intent_version: NonEmptyText | None = None
    top_k: int = Field(gt=0, le=10)
    related_asset_ids: list[UUID] = Field(default_factory=list)

    @model_validator(mode="after")
    def inputs_match_the_scope(self) -> RetrievalRequest:
        if self.scope is RetrievalScope.CURRENT_SOURCE:
            if self.query is None:
                raise ValueError("current-source retrieval requires a query")
            if self.discovery_intent_version is not None:
                raise ValueError(
                    "current-source retrieval does not take a discovery intent"
                )
            return self
        if self.query is not None:
            raise ValueError(
                f"{self.scope.value} retrieval does not take a free-text query"
            )
        if self.scope is RetrievalScope.CROSS_ASSET_SUMMARY:
            if self.discovery_intent_version is None:
                raise ValueError(
                    "cross-asset summary discovery requires the Runtime-owned "
                    "discovery intent version"
                )
        elif self.discovery_intent_version is not None:
            raise ValueError(
                "confirmed-detail retrieval is bounded by the confirmed relation "
                "itself and takes no discovery intent"
            )
        return self


class RetrievalHit(ContractModel):
    hit_id: UUID
    asset_id: UUID
    version_id: UUID
    provenance_ref: NonEmptyText
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    summary_only: bool


class RetrievalResult(ContractModel):
    retrieval_id: UUID
    scope: RetrievalScope
    hits: list[RetrievalHit] = Field(default_factory=list)
    no_match: bool
    declined: bool = False


class SummaryLexicalHit(ContractModel):
    projection_id: UUID
    asset_id: UUID
    bm25_score: float


class SummaryLexicalResult(ContractModel):
    hits: list[SummaryLexicalHit] = Field(default_factory=list)
    no_match: bool


class ScopedRetrievalRepository(Protocol):
    def search(self, request: RetrievalRequest) -> RetrievalResult:
        """Return bounded local references without mutating canonical state."""


class FakeScopedRetrievalRepository:
    """Deterministic public fake used by the E1-A2 durable loop."""

    def __init__(self, *, return_match: bool = True) -> None:
        self.return_match = return_match

    def search(self, request: RetrievalRequest) -> RetrievalResult:
        if not self.return_match or (
            request.scope is not RetrievalScope.CURRENT_SOURCE
            and not request.related_asset_ids
        ):
            return RetrievalResult(
                retrieval_id=request.retrieval_id,
                scope=request.scope,
                no_match=True,
            )
        hit_asset_id = (
            request.current_asset_id
            if request.scope is RetrievalScope.CURRENT_SOURCE
            else (
                request.related_asset_ids[0]
                if request.related_asset_ids
                else request.current_asset_id
            )
        )
        return RetrievalResult(
            retrieval_id=request.retrieval_id,
            scope=request.scope,
            no_match=False,
            hits=[
                RetrievalHit(
                    hit_id=uuid4(),
                    asset_id=hit_asset_id,
                    version_id=request.current_version_id,
                    provenance_ref=f"synthetic:{request.scope.value.lower()}",
                    content_hash="c" * 64,
                    summary_only=request.scope is RetrievalScope.CROSS_ASSET_SUMMARY,
                )
            ],
        )


class SQLiteCurrentSourceRetrievalRepository:
    """Read-only retrieval over source-linked statements in one exact version."""

    def __init__(self, repository: SQLiteAssetRepository) -> None:
        self.repository = repository

    def search(self, request: RetrievalRequest) -> RetrievalResult:
        if request.scope is not RetrievalScope.CURRENT_SOURCE:
            return RetrievalResult(
                retrieval_id=request.retrieval_id,
                scope=request.scope,
                no_match=True,
                declined=True,
            )
        try:
            asset = self.repository.get_version(request.current_version_id)
        except AssetNotFoundError:
            return RetrievalResult(
                retrieval_id=request.retrieval_id,
                scope=request.scope,
                no_match=True,
            )
        if asset.asset_id != request.current_asset_id:
            return RetrievalResult(
                retrieval_id=request.retrieval_id,
                scope=request.scope,
                no_match=True,
                declined=True,
            )

        query_text = request.query or ""
        terms = {
            term.casefold()
            for term in query_text.replace("\uFF0C", " ").replace(",", " ").split()
            if term.strip()
        }
        ranked = []
        for index, statement in enumerate(asset.statements):
            if not statement.source_refs:
                continue
            folded = statement.text.casefold()
            score = sum(1 for term in terms if term in folded)
            if score > 0:
                ranked.append((score, -index, statement))
        ranked.sort(reverse=True, key=lambda item: (item[0], item[1]))
        selected = ranked[: request.top_k]
        hits = [
            RetrievalHit(
                hit_id=uuid4(),
                asset_id=asset.asset_id,
                version_id=asset.version_id,
                provenance_ref=(
                    f"asset:{asset.asset_id}/version:{asset.version_id}/"
                    f"statement:{statement.statement_id}"
                ),
                content_hash=hashlib.sha256(
                    statement.text.encode("utf-8")
                ).hexdigest(),
                summary_only=False,
            )
            for _, _, statement in selected
        ]
        return RetrievalResult(
            retrieval_id=request.retrieval_id,
            scope=request.scope,
            hits=hits,
            no_match=not hits,
        )


class SQLiteSummaryLexicalRepository:
    """BM25 ordering over active, ready-card summary rows only."""

    def __init__(self, repository: SQLiteAssetRepository) -> None:
        self.repository = repository

    def search(
        self, *, query: str, current_asset_id: UUID, top_k: int = 10
    ) -> SummaryLexicalResult:
        if top_k <= 0 or top_k > 10:
            raise ValueError("summary lexical top_k must be between 1 and 10")
        tokens = normalize_lexical_text(query)
        if not tokens:
            return SummaryLexicalResult(no_match=True)
        rows = self.repository.search_active_projection_summaries(
            tokens=tokens,
            current_asset_id=current_asset_id,
            top_k=top_k,
        )
        hits = [SummaryLexicalHit.model_validate(row) for row in rows]
        return SummaryLexicalResult(hits=hits, no_match=not hits)
