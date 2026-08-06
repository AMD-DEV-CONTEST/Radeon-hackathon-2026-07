"""Build the canonical, read-only projection of the editable M2 artifact."""

from datetime import datetime
from uuid import UUID, uuid4

from app.experience_asset.domain.enums import Milestone, MilestoneState, ReviewStatus
from app.experience_asset.domain.m2 import CriticalMomentMapV1
from app.experience_asset.domain.models import (
    CriticalMoment,
    ExperienceAssetV1,
    MilestoneArtifact,
    VersionLineage,
)


def project_m2(
    current: ExperienceAssetV1,
    artifact: CriticalMomentMapV1,
    *,
    version_id: UUID,
    now: datetime,
    change_kind: str,
    change_reason: str,
    parent_version_id: UUID | None = None,
    derived_by_run_id: UUID | None = None,
) -> ExperienceAssetV1:
    """Return a new canonical version referencing, not copying, M2 editable content."""
    accepted = artifact.state in {
        MilestoneState.CONFIRMED,
        MilestoneState.COMPLETE_WITH_GAPS,
    }
    projection = MilestoneArtifact(
        artifact_id=uuid4(),
        artifact_type="M2_CRITICAL_MOMENT_MAP_REFERENCE",
        asset_id=current.asset_id,
        version_id=version_id,
        milestone=Milestone.M2,
        state=artifact.state,
        statement_ids=artifact.dependency_statement_ids,
        unresolved_question_ids=artifact.unresolved_question_ids,
        generated_by_run_id=artifact.generated_by_run_id,
        user_review_status=(
            ReviewStatus.ACCEPTED_WITH_GAPS
            if artifact.state is MilestoneState.COMPLETE_WITH_GAPS
            else ReviewStatus.ACCEPTED
            if artifact.state is MilestoneState.CONFIRMED
            else ReviewStatus.NOT_REVIEWED
        ),
        created_at=now,
        updated_at=now,
        invalidated_by_version_id=(
            artifact.invalidated_by_m1_version_id
            if artifact.state is MilestoneState.INVALIDATED
            else None
        ),
        payload={"m2_artifact_id": str(artifact.artifact_id)},
    )
    payload = current.model_dump(mode="python")
    payload.update(
        version_id=version_id,
        updated_at=now,
        current_milestone=Milestone.M3 if accepted else Milestone.M2,
        critical_moments=[
            CriticalMoment(
                moment_id=moment.moment_id,
                order=moment.display_order,
                title=moment.title,
                description=moment.description,
                cue_statement_ids=moment.cue_statement_ids,
                change_statement_ids=moment.change_statement_ids,
                surprise_statement_ids=moment.surprise_statement_ids,
                conflict_statement_ids=moment.conflict_statement_ids,
            )
            for moment in artifact.moments
        ],
        milestone_states={**current.milestone_states, Milestone.M2: artifact.state},
        milestone_artifacts=[
            item for item in current.milestone_artifacts if item.milestone is not Milestone.M2
        ]
        + [projection],
        route_decisions=[
            decision.model_copy(update={"canonical_version_id": version_id})
            for decision in current.route_decisions
        ],
        lineage=VersionLineage(
            version_id=version_id,
            parent_version_id=parent_version_id or current.version_id,
            change_kind=change_kind,
            change_reason=change_reason,
            created_at=now,
            derived_by_run_id=derived_by_run_id,
        ),
    )
    return ExperienceAssetV1.model_validate(payload)
