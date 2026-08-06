"""Canonical M3 projection preserving unrelated canonical content."""

from datetime import datetime
from uuid import UUID, uuid4

from app.experience_asset.domain.enums import Milestone, MilestoneState, ReviewStatus
from app.experience_asset.domain.m3 import DecisionEvidenceLedgerV1
from app.experience_asset.domain.models import (
    DecisionRecord,
    ExperienceAssetV1,
    MilestoneArtifact,
    Statement,
    VersionLineage,
)


def rebase_m3_projection(
    canonical: ExperienceAssetV1, artifact: DecisionEvidenceLedgerV1
) -> ExperienceAssetV1:
    """Bind an M2 transition snapshot to its exact M3 successor identity and state."""
    projections = []
    found = False
    for item in canonical.milestone_artifacts:
        if item.milestone is Milestone.M3:
            found = True
            projections.append(
                item.model_copy(
                    update={
                        "version_id": canonical.version_id,
                        "state": artifact.state,
                        "updated_at": canonical.updated_at,
                        "payload": {
                            "m3_artifact_id": str(artifact.artifact_id),
                            "base_m2_artifact_id": str(artifact.base_m2_artifact_id),
                        },
                    }
                )
            )
        else:
            projections.append(item)
    if not found:
        raise ValueError("canonical snapshot lacks existing M3 projection")
    payload = canonical.model_dump(mode="python")
    payload.update(
        milestone_artifacts=projections,
        milestone_states={**canonical.milestone_states, Milestone.M3: artifact.state},
        current_milestone=(
            Milestone.M3
            if artifact.state is MilestoneState.INVALIDATED
            else canonical.current_milestone
        ),
    )
    return ExperienceAssetV1.model_validate(payload)


def project_m3(
    current: ExperienceAssetV1,
    artifact: DecisionEvidenceLedgerV1,
    *,
    version_id: UUID,
    now: datetime,
    change_kind: str,
    change_reason: str,
) -> ExperienceAssetV1:
    """Map M3 role IDs to canonical Statements/DecisionRecords without replacing other data."""
    previous_projection = next(
        (item for item in current.milestone_artifacts if item.milestone is Milestone.M3), None
    )
    previous_m3_ids = set(previous_projection.statement_ids) if previous_projection else set()
    m3_ids = {
        statement.statement_id for entry in artifact.entries for statement in entry.statements
    }
    statements = [
        statement
        for statement in current.statements
        if statement.statement_id not in previous_m3_ids
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
                and previous.confirmation == item.confirmation
                and previous.evidence_strength == item.evidence_strength
            )
            statements.append(
                Statement(
                    statement_id=item.statement_id,
                    text=item.text,
                    status=item.status,
                    source_refs=[],
                    derived_from=sorted(
                        set(item.source_statement_ids + item.derived_from_statement_ids), key=str
                    ),
                    confirmation=item.confirmation,
                    evidence_strength=item.evidence_strength,
                    created_in_version=previous.created_in_version if previous else version_id,
                    last_changed_in_version=previous.last_changed_in_version
                    if unchanged
                    else version_id,
                )
            )
    previous_decision_ids = {
        decision.decision_id
        for decision in current.decisions
        if any(
            statement_id in previous_m3_ids
            for statement_id in (
                decision.decision_statement_ids
                + decision.alternative_statement_ids
                + decision.reason_statement_ids
                + decision.action_statement_ids
                + decision.result_statement_ids
            )
        )
    }
    decisions = [
        decision
        for decision in current.decisions
        if decision.decision_id not in previous_decision_ids
    ]
    for entry in artifact.entries:
        by_role = {
            role: [s.statement_id for s in entry.statements if s.role == role]
            for role in ("ALTERNATIVE", "REASON", "DECISION", "ACTION", "OBSERVED_RESULT")
        }
        decisions.append(
            DecisionRecord(
                decision_id=entry.decision_id,
                summary=next(s.text for s in entry.statements if s.role == "DECISION"),
                decision_statement_ids=by_role["DECISION"],
                alternative_statement_ids=by_role["ALTERNATIVE"],
                reason_statement_ids=by_role["REASON"],
                action_statement_ids=by_role["ACTION"],
                result_statement_ids=by_role["OBSERVED_RESULT"],
                evidence_statement_ids=sorted(
                    {ref for s in entry.statements for ref in s.source_statement_ids}, key=str
                ),
            )
        )
    projection = MilestoneArtifact(
        artifact_id=uuid4(),
        artifact_type="M3_DECISION_EVIDENCE_LEDGER_REFERENCE",
        asset_id=current.asset_id,
        version_id=version_id,
        milestone=Milestone.M3,
        state=artifact.state,
        statement_ids=sorted(m3_ids, key=str),
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
            "m3_artifact_id": str(artifact.artifact_id),
            "base_m2_artifact_id": str(artifact.base_m2_artifact_id),
        },
    )
    payload = current.model_dump(mode="python")
    payload.update(
        version_id=version_id,
        updated_at=now,
        statements=statements,
        decisions=decisions,
        current_milestone=Milestone.M4
        if artifact.state in {MilestoneState.CONFIRMED, MilestoneState.COMPLETE_WITH_GAPS}
        else Milestone.M3,
        milestone_states={**current.milestone_states, Milestone.M3: artifact.state},
        milestone_artifacts=[
            a for a in current.milestone_artifacts if a.milestone is not Milestone.M3
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
