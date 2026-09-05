"""Pure M1-to-M2 dependency invalidation."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from app.experience_asset.domain.enums import MilestoneState
from app.experience_asset.domain.m2 import CriticalMomentMapV1


def invalidate_after_m1_correction(
    artifact: CriticalMomentMapV1,
    *,
    corrected_statement_ids: set[UUID],
    new_m1_version_id: UUID,
    changed_at: datetime,
) -> CriticalMomentMapV1:
    """Invalidate only when a corrected M1 statement supports this M2 artifact."""

    affected = corrected_statement_ids.intersection(artifact.dependency_statement_ids)
    if not affected:
        return artifact

    if new_m1_version_id == artifact.base_m1_version_id:
        raise ValueError("new_m1_version_id must differ from the bound M1 version")
    if changed_at.tzinfo is None or changed_at.utcoffset() is None:
        raise ValueError("changed_at must include a timezone")
    if changed_at < artifact.updated_at:
        raise ValueError("changed_at must not predate the current M2 artifact")

    payload = artifact.model_dump(mode="python")
    payload.update(
        state=MilestoneState.INVALIDATED,
        updated_at=changed_at,
        invalidated_by_m1_version_id=new_m1_version_id,
        invalidation_reason=(
            "M1 correction changed statements used by this Critical Moment Map: "
            + ", ".join(sorted(str(statement_id) for statement_id in affected))
        ),
    )
    return CriticalMomentMapV1.model_validate(payload)
