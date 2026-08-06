"""Evidence-bound resonance clustering and deterministic publication."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit
from uuid import UUID

from creative_hub.db.canonical import canonical_json_digest
from creative_hub.shidu.repository import (
    EvidencePackNotPublishable,
    ShiduRepository,
)
from creative_hub.shidu.resonance_validator import (
    CLUSTER_SCHEMA_DIGEST,
    CLUSTER_SCHEMA_VERSION,
    CLUSTERING_VERSION,
    DIRECTION_SCORE_VERSION,
    PENALTY_VERSION,
    RESONANCE_VALIDATOR_VERSION,
    ClusterProposal,
    DirectionPenalties,
    DirectionSignals,
    GroundedText,
    ResonancePolicy,
    ResonanceScorer,
    ResonanceValidationError,
    parse_cluster_proposals,
    stable_gap_codes,
    validate_cluster,
)
from creative_hub.shidu.schemas import (
    DirectionDraft,
    PublishDirections,
    ResonanceDirectionRevision,
)
from creative_hub.shidu.research_service import registrable_site_key


@dataclass(frozen=True)
class ClusteringClaim:
    evidence_id: UUID
    claim_type: str
    normalized_claim: str
    spoiler_level: str
    confidence: float
    source_document_revision_id: UUID
    registered_domain: str
    source_type: str


@dataclass(frozen=True)
class ResonanceClusterRequest:
    """Fixed data-only boundary; it deliberately has no tool/provider controls."""

    evidence_pack_revision_id: UUID
    evidence_pack_digest: str
    model_version: str
    prompt_version: str
    schema_version: str
    schema_digest: str
    claims: tuple[ClusteringClaim, ...]
    max_proposals: int = 16
    tools_allowed: bool = False


class ResonanceProposalTransport(Protocol):
    def propose(self, request: ResonanceClusterRequest) -> object: ...


def _paraphrase_text(value: str, maximum: int) -> str:
    text = " ".join(value.split()).replace("“", "").replace("”", "")
    text = text.replace("‘", "").replace("’", "")
    if len(text) >= 2 and text[0] in {'"', "'"} and text[-1] == text[0]:
        text = text[1:-1].strip()
    return text[:maximum]


class DeterministicClusterer:
    """Offline application-owned fallback that creates at most one truthful cluster."""

    def propose(self, request: ResonanceClusterRequest) -> object:
        by_type: dict[str, list[ClusteringClaim]] = {}
        for claim in request.claims:
            by_type.setdefault(claim.claim_type, []).append(claim)
        if not all(
            by_type.get(kind)
            for kind in ("plot_node", "emotional_reaction", "reader_fit")
        ):
            return {"clusters": []}
        ordered = sorted(request.claims, key=lambda item: str(item.evidence_id))
        selected: list[ClusteringClaim] = []
        selected_ids: set[UUID] = set()

        def include(item: ClusteringClaim) -> None:
            if item.evidence_id not in selected_ids and len(selected) < 16:
                selected.append(item)
                selected_ids.add(item.evidence_id)

        for kind in ("plot_node", "emotional_reaction", "reader_fit"):
            include(sorted(by_type[kind], key=lambda item: str(item.evidence_id))[0])
        seen_domains = {item.registered_domain for item in selected}
        for item in ordered:
            if item.registered_domain not in seen_domains:
                include(item)
                seen_domains.add(item.registered_domain)
            if len(seen_domains) >= 3:
                break
        seen_types = {item.source_type for item in selected}
        for item in ordered:
            if item.source_type not in seen_types:
                include(item)
                seen_types.add(item.source_type)
            if len(seen_types) >= 2:
                break
        for item in ordered:
            include(item)
        selected_by_type: dict[str, list[ClusteringClaim]] = {}
        for item in selected:
            selected_by_type.setdefault(item.claim_type, []).append(item)
        plot = selected_by_type["plot_node"][0]
        reader = selected_by_type["reader_fit"][0]
        evidence_ids = tuple(item.evidence_id for item in selected)
        perceived = _paraphrase_text(plot.normalized_claim, 80)
        reader_text = _paraphrase_text(reader.normalized_claim, 300)
        proposal = ClusterProposal(
            cluster_key="application-owned",
            evidence_ids=evidence_ids,
            title=perceived,
            factual_statements=tuple(
                GroundedText(
                    _paraphrase_text(item.normalized_claim, 400),
                    (item.evidence_id,),
                )
                for item in sorted(
                    selected, key=lambda item: str(item.evidence_id)
                )
            ),
            first_person_entry=GroundedText(
                f"我正经历这一刻：{perceived}", (plot.evidence_id,)
            ),
            perceived_detail=GroundedText(perceived, (plot.evidence_id,)),
            fit_for=(
                GroundedText(reader_text, (reader.evidence_id,)),
            ),
            not_fit_for=(
                GroundedText(
                    (
                        "不适合不认同这一阅读处境的读者："
                        + reader_text
                    ),
                    (reader.evidence_id,),
                ),
            ),
            spoiler_level=max(
                (item.spoiler_level for item in selected),
                key={"none": 0, "light": 1, "moderate": 2, "critical": 3}.__getitem__,
            ),
        )
        return {"clusters": [proposal.model_dump(mode="json")]}


class ResonanceService:
    def __init__(
        self,
        *,
        repository: ShiduRepository,
        proposal_transport: ResonanceProposalTransport | None = None,
        model_version: str = "application-owned-deterministic-v1",
        prompt_version: str = "shidu-resonance-prompt-v1",
        policy: ResonancePolicy | None = None,
        scorer: ResonanceScorer | None = None,
    ) -> None:
        if not model_version or len(model_version) > 160:
            raise ValueError("model_version is invalid")
        if not prompt_version or len(prompt_version) > 160:
            raise ValueError("prompt_version is invalid")
        self._repository = repository
        self._transport = proposal_transport or DeterministicClusterer()
        self._model_version = model_version
        self._prompt_version = prompt_version
        self._policy = policy or ResonancePolicy()
        self._scorer = scorer or ResonanceScorer()
        self.last_gap_codes: tuple[str, ...] = ()

    def _command_key(self, pack_digest: str) -> str:
        digest = canonical_json_digest(
            {
                "pack_digest": pack_digest,
                "model_version": self._model_version,
                "prompt_version": self._prompt_version,
                "cluster_schema_version": CLUSTER_SCHEMA_VERSION,
                "cluster_schema_digest": CLUSTER_SCHEMA_DIGEST,
                "clustering_version": CLUSTERING_VERSION,
                "validator_version": RESONANCE_VALIDATOR_VERSION,
                "score_version": DIRECTION_SCORE_VERSION,
                "penalty_version": PENALTY_VERSION,
                "policy_version": self._policy.version,
                "max_spoiler_level": self._policy.max_spoiler_level,
            }
        )
        return f"resonance:{digest}"

    def publish(
        self, evidence_pack_revision_id: UUID
    ) -> tuple[ResonanceDirectionRevision, ...]:
        pack, claims, sources = self._repository.load_resonance_context(
            evidence_pack_revision_id
        )
        if not pack.publishable:
            self.last_gap_codes = stable_gap_codes(
                pack.insufficiency_reason_codes or ("pack_not_publishable",)
            )
            return ()
        command_key = self._command_key(pack.digest)
        replay = self._repository.list_directions_for_command(
            pack.project_id, command_key
        )
        if replay:
            self.last_gap_codes = ()
            return replay

        request = ResonanceClusterRequest(
            evidence_pack_revision_id=pack.id,
            evidence_pack_digest=pack.digest,
            model_version=self._model_version,
            prompt_version=self._prompt_version,
            schema_version=CLUSTER_SCHEMA_VERSION,
            schema_digest=CLUSTER_SCHEMA_DIGEST,
            claims=tuple(
                ClusteringClaim(
                    evidence_id=item.id,
                    claim_type=item.claim_type,
                    normalized_claim=item.normalized_claim,
                    spoiler_level=item.spoiler_level,
                    confidence=item.confidence,
                    source_document_revision_id=(
                        item.source_document_revision_id
                    ),
                    registered_domain=registrable_site_key(
                        urlsplit(
                            next(
                                source.canonical_url
                                for source in sources
                                if source.id
                                == item.source_document_revision_id
                            )
                        ).hostname
                        or ""
                    ),
                    source_type=next(
                        source.source_type
                        for source in sources
                        if source.id == item.source_document_revision_id
                    ),
                )
                for item in sorted(claims, key=lambda value: str(value.id))
            ),
        )
        try:
            proposals = parse_cluster_proposals(self._transport.propose(request))
        except Exception as error:
            if not isinstance(error, ResonanceValidationError):
                error = ResonanceValidationError(
                    "cluster structured output is invalid"
                )
            self.last_gap_codes = ("model_contract_invalid",)
            return ()

        claims_by_id = {item.id: item for item in claims}
        sources_by_id = {item.id: item for item in sources}
        valid = []
        gaps: list[str] = []
        seen_direction_keys: set[str] = set()
        for proposal in proposals:
            direction, proposal_gaps = validate_cluster(
                proposal,
                pack=pack,
                claims_by_id=claims_by_id,
                sources_by_id=sources_by_id,
                policy=self._policy,
                model_version=self._model_version,
                prompt_version=self._prompt_version,
                scorer=self._scorer,
            )
            gaps.extend(proposal_gaps)
            if direction is None:
                continue
            if direction.direction_key in seen_direction_keys:
                gaps.append("duplicate_cluster")
                continue
            seen_direction_keys.add(direction.direction_key)
            valid.append(direction)
        valid.sort(key=lambda item: (-item.score, item.direction_key))
        chosen = tuple(valid[:4])
        self.last_gap_codes = stable_gap_codes(gaps)
        if not chosen:
            return ()
        try:
            return self._repository.publish_directions(
                PublishDirections(
                    project_id=pack.project_id,
                    evidence_pack_revision_id=pack.id,
                    directions=tuple(
                        DirectionDraft(item.direction_key, item.payload)
                        for item in chosen
                    ),
                    command_key=command_key,
                )
            )
        except EvidencePackNotPublishable:
            self.last_gap_codes = ("critical_conflict_unresolved",)
            return ()


__all__ = [
    "ClusterProposal",
    "ClusteringClaim",
    "DeterministicClusterer",
    "DirectionPenalties",
    "DirectionSignals",
    "GroundedText",
    "ResonanceClusterRequest",
    "ResonancePolicy",
    "ResonanceProposalTransport",
    "ResonanceScorer",
    "ResonanceService",
]
