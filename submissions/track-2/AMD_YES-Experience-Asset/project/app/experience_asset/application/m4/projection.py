"""Canonical M4 projection preserving unrelated canonical content."""

from datetime import datetime
from uuid import UUID, uuid4

from app.experience_asset.domain.enums import (
    ConfirmationState,
    EvidenceStrength,
    Milestone,
    MilestoneState,
    ReviewStatus,
    StatementStatus,
)
from app.experience_asset.domain.m4 import InsightBoundaryMapV1
from app.experience_asset.domain.models import (
    ExperienceAssetV1,
    InsightRecord,
    MilestoneArtifact,
    Statement,
    VersionLineage,
)

ACCEPTED_STATES = frozenset({MilestoneState.CONFIRMED, MilestoneState.COMPLETE_WITH_GAPS})

_ROLE_FIELDS = {
    "SUPPORT": "support_statement_ids",
    "COUNTERFACTUAL": "counterfactual_statement_ids",
    "LIMITATION": "limitation_statement_ids",
    "COUNTEREXAMPLE": "counterexample_statement_ids",
    "APPLICABILITY": "applicability_statement_ids",
}


def rebase_m4_projection(
    canonical: ExperienceAssetV1, artifact: InsightBoundaryMapV1
) -> ExperienceAssetV1:
    """Bind an M3 transition snapshot to its exact M4 successor identity and state."""
    projections = []
    found = False
    for item in canonical.milestone_artifacts:
        if item.milestone is Milestone.M4:
            found = True
            projections.append(
                item.model_copy(
                    update={
                        "version_id": canonical.version_id,
                        "state": artifact.state,
                        "updated_at": canonical.updated_at,
                        "payload": {
                            "m4_artifact_id": str(artifact.artifact_id),
                            "base_m3_artifact_id": str(artifact.base_m3_artifact_id),
                        },
                    }
                )
            )
        else:
            projections.append(item)
    if not found:
        raise ValueError("canonical snapshot lacks existing M4 projection")
    payload = canonical.model_dump(mode="python")
    payload.update(
        milestone_artifacts=projections,
        milestone_states={**canonical.milestone_states, Milestone.M4: artifact.state},
        current_milestone=(
            Milestone.M4
            if artifact.state is MilestoneState.INVALIDATED
            else canonical.current_milestone
        ),
    )
    return ExperienceAssetV1.model_validate(payload)


def project_m4(
    current: ExperienceAssetV1,
    artifact: InsightBoundaryMapV1,
    *,
    version_id: UUID,
    now: datetime,
    change_kind: str,
    change_reason: str,
) -> ExperienceAssetV1:
    """Map M4 insight statements onto canonical Statements and InsightRecords.

    The map's own statements become canonical statements so that the boundary
    content is addressable by the same identifiers as everything else: a
    downstream readiness binding, an evidence card and a relation projection all
    resolve statement IDs against one canonical set, and a lesson that lived only
    inside the artifact would be invisible to all three.
    """
    previous_projection = next(
        (item for item in current.milestone_artifacts if item.milestone is Milestone.M4), None
    )
    previous_m4_ids = set(previous_projection.statement_ids) if previous_projection else set()
    m4_ids = {
        statement.statement_id for entry in artifact.entries for statement in entry.statements
    }
    statements = [
        statement
        for statement in current.statements
        if statement.statement_id not in previous_m4_ids
    ]
    for entry in artifact.entries:
        for item in entry.statements:
            previous = next(
                (s for s in current.statements if s.statement_id == item.statement_id), None
            )
            unchanged = (
                previous is not None
                and previous.text == item.text
                and previous.status == item.status
            )
            # A visible gap carries no citations by contract, so it cannot claim
            # AGENT_INFERENCE — that status requires derived_from and would make
            # an unsupported statement indistinguishable from a grounded one.
            status = (
                StatementStatus.UNRESOLVED
                if item.is_visible_gap
                else item.status
                if item.status is not StatementStatus.SOURCE_FACT
                else StatementStatus.AGENT_INFERENCE
            )
            statements.append(
                Statement(
                    statement_id=item.statement_id,
                    text=item.text,
                    status=status,
                    source_refs=[],
                    derived_from=sorted(set(item.source_statement_ids), key=str),
                    confirmation=(
                        ConfirmationState.CONFIRMED
                        if item.status is StatementStatus.USER_JUDGMENT
                        else ConfirmationState.UNCONFIRMED
                    ),
                    evidence_strength=(
                        EvidenceStrength.NONE
                        if item.is_visible_gap
                        else EvidenceStrength.SELF_REPORTED
                        if item.status is StatementStatus.USER_JUDGMENT
                        else EvidenceStrength.INDIRECT
                    ),
                    created_in_version=previous.created_in_version if previous else version_id,
                    last_changed_in_version=previous.last_changed_in_version
                    if unchanged and previous
                    else version_id,
                )
            )
    insights = [
        insight
        for insight in current.insights
        if insight.insight_id not in {entry.insight_id for entry in artifact.entries}
        and not (
            set(
                insight.support_statement_ids
                + insight.counterfactual_statement_ids
                + insight.limitation_statement_ids
                + insight.counterexample_statement_ids
                + insight.applicability_statement_ids
            )
            & previous_m4_ids
        )
    ]
    for entry in artifact.entries:
        by_role: dict[str, list[UUID]] = {
            field: [s.statement_id for s in entry.statements if s.role == role]
            for role, field in _ROLE_FIELDS.items()
        }
        insights.append(
            InsightRecord(
                insight_id=entry.insight_id,
                lesson=next(s.text for s in entry.statements if s.role == "LESSON"),
                **by_role,
            )
        )
    projection = MilestoneArtifact(
        artifact_id=uuid4(),
        artifact_type="M4_INSIGHT_BOUNDARY_MAP_REFERENCE",
        asset_id=current.asset_id,
        version_id=version_id,
        milestone=Milestone.M4,
        state=artifact.state,
        statement_ids=sorted(m4_ids, key=str),
        unresolved_question_ids=artifact.unresolved_question_ids,
        generated_by_run_id=artifact.generated_by_run_id,
        user_review_status=(
            ReviewStatus.ACCEPTED
            if artifact.state is MilestoneState.CONFIRMED
            else ReviewStatus.ACCEPTED_WITH_GAPS
            if artifact.state is MilestoneState.COMPLETE_WITH_GAPS
            else ReviewStatus.NOT_REVIEWED
        ),
        created_at=now,
        updated_at=now,
        payload={
            "m4_artifact_id": str(artifact.artifact_id),
            "base_m3_artifact_id": str(artifact.base_m3_artifact_id),
        },
    )
    payload = current.model_dump(mode="python")
    payload.update(
        version_id=version_id,
        updated_at=now,
        statements=statements,
        insights=insights,
        current_milestone=Milestone.M5
        if artifact.state in ACCEPTED_STATES
        else Milestone.M4,
        milestone_states={**current.milestone_states, Milestone.M4: artifact.state},
        milestone_artifacts=[
            a for a in current.milestone_artifacts if a.milestone is not Milestone.M4
        ]
        + [projection],
        route_decisions=[
            d.model_copy(update={"canonical_version_id": version_id})
            for d in current.route_decisions
        ],
        lineage=VersionLineage(
            version_id=version_id,
            parent_version_id=current.version_id,
            change_kind=change_kind,
            change_reason=change_reason,
            created_at=now,
            derived_by_run_id=artifact.generated_by_run_id,
        ),
    )
    return ExperienceAssetV1.model_validate(payload)
