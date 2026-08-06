"""Typed argument contracts for every model-visible tool.

Only the three retrieval operations have an E1-A dispatcher. The remaining
P0 tools retain reviewed schemas but fail closed until later work packages
implement them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.experience_asset.domain.enums import Milestone, RouteType
from app.experience_asset.domain.models import ContractModel, NonEmptyText, Sha256


class CurrentExperienceSearchArguments(ContractModel):
    asset_id: UUID
    current_version_id: UUID
    scope: Literal["CURRENT_SOURCE"]
    query: NonEmptyText
    top_k: int = Field(default=3, ge=1, le=10)


class RelatedCandidateDiscoveryArguments(ContractModel):
    """Cross-asset summary discovery.

    There is deliberately no free-text query. A relation is meant to be a
    durable statement about two assets, while a query is a one-off question:
    driving discovery by phrasing lets the same pair yield different relations
    under different wordings, so the relation degrades into what one sentence
    returned once. The Runtime-owned `discovery_intent_version` removes that
    variance — though reproducibility itself comes from the discovery
    fingerprint and its idempotent cache, not from this field alone.

    `top_k` is retained for interface compatibility and is a **ceiling, never a
    quota**. Treating it as a quota would pressure the service into padding one
    defensible candidate with weaker ones, and a weak relation costs more of the
    user's attention than a missed one does.
    """

    asset_id: UUID
    current_version_id: UUID
    knowledge_card_version_id: UUID
    knowledge_card_hash: Sha256
    scope: Literal["CROSS_ASSET_SUMMARY"]
    discovery_intent_version: Literal["e5-discovery-intent/v1"] = (
        "e5-discovery-intent/v1"
    )
    top_k: int = Field(default=3, ge=1, le=10)


class RelationSelection(ContractModel):
    relation_id: UUID
    related_asset_id: UUID


class ConfirmedRelatedEvidenceArguments(ContractModel):
    """Bounded detail read for an already-confirmed relation.

    The free-text query is removed here too, but it is **not** replaced by a
    discovery intent. The readable set is computed from the exact confirmed
    relation, its bindings, and the validated mapping and boundary package, so
    any remaining tunable would mean one confirmation could read different
    things on different calls — precisely what "one confirmation unlocks one
    asset's bounded evidence" exists to prevent.
    """

    asset_id: UUID
    current_version_id: UUID
    knowledge_card_version_id: UUID
    knowledge_card_hash: Sha256
    scope: Literal["CROSS_ASSET_DETAIL"]
    relation_bindings: list[RelationSelection] = Field(min_length=1, max_length=10)
    top_k: int = Field(default=3, ge=1, le=10)


class SourceSpanReadArguments(ContractModel):
    asset_id: UUID
    current_version_id: UUID
    source_ids: list[UUID] = Field(min_length=1, max_length=10)
    max_spans: int = Field(default=5, ge=1, le=20)


class EvidenceGapInspectionArguments(ContractModel):
    asset_id: UUID
    current_version_id: UUID
    milestone: Milestone
    statement_ids: list[UUID] = Field(default_factory=list, max_length=50)


class RouteReadinessEvaluationArguments(ContractModel):
    asset_id: UUID
    current_version_id: UUID
    routes: list[RouteType] = Field(min_length=1, max_length=5)


class PrivatePreviewRenderArguments(ContractModel):
    asset_id: UUID
    current_version_id: UUID
    route_draft_id: UUID
    route_draft_hash: Sha256


@dataclass(frozen=True)
class ModelVisibleToolContract:
    arguments_model: type[ContractModel]
    executable_in_e1_a: bool


MODEL_VISIBLE_TOOL_CONTRACTS = {
    "search_current_experience": ModelVisibleToolContract(
        CurrentExperienceSearchArguments, True
    ),
    "discover_related_experience_candidates": ModelVisibleToolContract(
        RelatedCandidateDiscoveryArguments, True
    ),
    "read_confirmed_related_evidence": ModelVisibleToolContract(
        ConfirmedRelatedEvidenceArguments, True
    ),
    "read_source_spans": ModelVisibleToolContract(SourceSpanReadArguments, False),
    "inspect_evidence_gaps": ModelVisibleToolContract(
        EvidenceGapInspectionArguments, False
    ),
    "evaluate_route_readiness": ModelVisibleToolContract(
        RouteReadinessEvaluationArguments, False
    ),
    "render_private_preview": ModelVisibleToolContract(
        PrivatePreviewRenderArguments, False
    ),
}

E1_A_EXECUTABLE_TOOLS = frozenset(
    name
    for name, contract in MODEL_VISIBLE_TOOL_CONTRACTS.items()
    if contract.executable_in_e1_a
)
