"""Sanitized builders for the four public E6 fixture categories."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from app.experience_asset.application.m5.contracts import (
    M5ContextProjectionV1,
    M5EvidenceIndexV1,
    M5RelationProjectionV1,
    PrivacyCategoryV1,
    PrivacyFindingProposalV1,
    RelationOutcomeV1,
)
from app.experience_asset.domain.enums import (
    ConfirmationState,
    EvidenceStrength,
    FindingSeverity,
    MilestoneState,
    SourceAuthorship,
    SourceKind,
    StatementStatus,
)
from app.experience_asset.domain.models import SourceReference, Statement
from app.experience_asset.domain.relation import KnowledgeCardReadinessRecordV1

CONTENT_HASH = "1" * 64
RELATION_HASH = "2" * 64
RENDERER_INPUT_HASH = "3" * 64
SOURCE_HASH = "4" * 64
NOW = datetime(2026, 8, 1, 4, 0, tzinfo=UTC)


def uid(value: int) -> UUID:
    return UUID(int=value)


ASSET_ID = uid(100)
VERSION_ID = uid(101)
SOURCE_ID = uid(102)
RUN_ID = uid(103)
READINESS_ID = uid(104)
M4_ARTIFACT_ID = uid(105)
STATEMENT_IDS = {name: uid(200 + index) for index, name in enumerate(
    (
        "decision",
        "lesson",
        "prerequisite",
        "guidance",
        "risk",
        "comparison",
        "result",
        "boundary",
        "event",
        "disclosure",
        "unresolved",
        "identity",
        "health",
        "qualifying",
    )
)}


def _statement(name: str, *, sensitivity_tags: list[str] | None = None) -> Statement:
    statement_id = STATEMENT_IDS[name]
    return Statement(
        statement_id=statement_id,
        text=f"Sanitized public fixture statement: {name}.",
        status=(
            StatementStatus.UNRESOLVED
            if name == "unresolved"
            else StatementStatus.SOURCE_FACT
        ),
        source_refs=[] if name == "unresolved" else [SOURCE_ID],
        confirmation=ConfirmationState.UNCONFIRMED,
        evidence_strength=(
            EvidenceStrength.NONE if name == "unresolved" else EvidenceStrength.DIRECT
        ),
        sensitivity_tags=sensitivity_tags or [],
        created_in_version=VERSION_ID,
        last_changed_in_version=VERSION_ID,
    )


def complete_context(
    *,
    relation_outcome: RelationOutcomeV1 = RelationOutcomeV1.NO_MATCH,
    relation_current: bool | None = None,
    include_qualifying_context: bool = False,
    include_sensitive_tags: bool = True,
    readiness: bool = True,
) -> M5ContextProjectionV1:
    names = [
        "decision",
        "lesson",
        "prerequisite",
        "guidance",
        "risk",
        "comparison",
        "result",
        "boundary",
        "event",
        "disclosure",
        "unresolved",
        "identity",
        "health",
    ]
    if include_qualifying_context:
        names.append("qualifying")
    statements = [
        _statement(
            name,
            sensitivity_tags=(
                ["IDENTITY"]
                if include_sensitive_tags and name == "identity"
                else ["HEALTH_BODY"]
                if include_sensitive_tags and name == "health"
                else []
            ),
        )
        for name in names
    ]
    confirmed = relation_outcome is RelationOutcomeV1.CONFIRMED_RELATION
    if relation_current is None:
        relation_current = relation_outcome is not RelationOutcomeV1.STALE
    relation = M5RelationProjectionV1(
        bound_asset_id=ASSET_ID,
        bound_version_id=VERSION_ID,
        bound_content_hash=CONTENT_HASH,
        outcome=relation_outcome,
        projection_hash=RELATION_HASH,
        is_current=relation_current,
        confirmed_relation_id=uid(300) if confirmed else None,
        confirmed_related_asset_id=uid(301) if confirmed else None,
        confirmed_related_version_id=uid(303) if confirmed else None,
        confirmed_related_content_hash="9" * 64 if confirmed else None,
        authorized_historical_statement_ids=[uid(302)] if confirmed else [],
    )
    evidence = M5EvidenceIndexV1(
        decision_context=[STATEMENT_IDS["decision"]],
        personal_lesson=[STATEMENT_IDS["lesson"]],
        beginner_prerequisite=[STATEMENT_IDS["prerequisite"]],
        beginner_guidance_basis=[STATEMENT_IDS["guidance"]],
        common_mistake_or_risk=[STATEMENT_IDS["risk"]],
        peer_comparison=[STATEMENT_IDS["comparison"]],
        peer_evidence=[STATEMENT_IDS["result"]],
        tradeoff_or_constraint=[STATEMENT_IDS["comparison"]],
        qualifying_context=(
            [STATEMENT_IDS["qualifying"]] if include_qualifying_context else []
        ),
        verifiable_result=[STATEMENT_IDS["result"]],
        event_arc=[STATEMENT_IDS["event"]],
        transferable_lesson=[STATEMENT_IDS["lesson"]],
        applicability_boundary=[STATEMENT_IDS["boundary"]],
        disclosure_basis=[STATEMENT_IDS["disclosure"]],
        unresolved_statement_ids=[STATEMENT_IDS["unresolved"]],
    )
    return M5ContextProjectionV1(
        asset_id=ASSET_ID,
        version_id=VERSION_ID,
        content_hash=CONTENT_HASH,
        current_version_id=VERSION_ID,
        readiness=(
            KnowledgeCardReadinessRecordV1(
                readiness_id=READINESS_ID,
                asset_id=ASSET_ID,
                version_id=VERSION_ID,
                m4_artifact_id=M4_ARTIFACT_ID,
                knowledge_card_hash=CONTENT_HASH,
                milestone_state=MilestoneState.CONFIRMED,
                explicit_user_acceptance=True,
                accepted_at=NOW,
            )
            if readiness
            else None
        ),
        statements=statements,
        sources=[
            SourceReference(
                source_id=SOURCE_ID,
                kind=SourceKind.ADAPTED_PUBLIC_FIXTURE,
                display_label="Sanitized office-chair fixture",
                source_hash=SOURCE_HASH,
                source_url="https://www.reddit.com/r/OfficeChairs/comments/hem1s7/",
                adapted_provenance_notice="Paraphrased public research fixture.",
                ingested_at=NOW,
                authorship=SourceAuthorship.ADAPTED_RESEARCH,
            )
        ],
        evidence=evidence,
        relation=relation,
        schema_identity="experience-asset/1.0.0",
        workflow_identity="experience-asset/e6-m5-isolated/v1",
        policy_identity="m5-route-policy-v1",
        model_run_id=RUN_ID,
    )


def privacy_risk_proposals() -> list[PrivacyFindingProposalV1]:
    return [
        PrivacyFindingProposalV1(
            category=PrivacyCategoryV1.IDENTITY,
            affected_statement_ids=[STATEMENT_IDS["identity"]],
            severity=FindingSeverity.HIGH,
            explanation="A direct identity detail may identify the person.",
        ),
        PrivacyFindingProposalV1(
            category=PrivacyCategoryV1.HEALTH_BODY,
            affected_statement_ids=[STATEMENT_IDS["health"]],
            severity=FindingSeverity.MEDIUM,
            explanation="A body or health detail needs explicit review.",
        ),
        PrivacyFindingProposalV1(
            category=PrivacyCategoryV1.COPYRIGHT,
            affected_source_ids=[SOURCE_ID],
            severity=FindingSeverity.LOW,
            explanation="Adapted third-party source provenance must remain visible.",
        ),
        PrivacyFindingProposalV1(
            category=PrivacyCategoryV1.UNVERIFIED_BRAND_CLAIM,
            affected_statement_ids=[STATEMENT_IDS["comparison"]],
            severity=FindingSeverity.MEDIUM,
            explanation="The product comparison is personal rather than universal.",
        ),
    ]


def route_ineligible_context() -> M5ContextProjectionV1:
    return complete_context(include_qualifying_context=False)


def correction_context(context: M5ContextProjectionV1) -> M5ContextProjectionV1:
    return context.model_copy(
        update={
            "version_id": uid(401),
            "current_version_id": uid(401),
            "content_hash": "5" * 64,
        }
    )
