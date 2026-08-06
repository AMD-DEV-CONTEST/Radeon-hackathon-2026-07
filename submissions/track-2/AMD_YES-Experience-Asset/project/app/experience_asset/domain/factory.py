"""Factories for valid empty canonical state."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from .enums import Milestone, MilestoneState, RouteEligibility, RouteType
from .models import ExperienceAssetV1, RouteDecision, VersionLineage


def new_empty_asset(
    *,
    asset_id: UUID | None = None,
    version_id: UUID | None = None,
    now: datetime | None = None,
) -> ExperienceAssetV1:
    """Create a valid unsourced asset without inventing any user fact."""

    created = now or datetime.now(UTC)
    current_asset_id = asset_id or uuid4()
    current_version_id = version_id or uuid4()
    return ExperienceAssetV1(
        asset_id=current_asset_id,
        version_id=current_version_id,
        created_at=created,
        updated_at=created,
        milestone_states={milestone: MilestoneState.NOT_STARTED for milestone in Milestone},
        route_decisions=[
            RouteDecision(
                route=route,
                eligibility=RouteEligibility.BLOCKED,
                reason_codes=["MISSING_EVIDENCE"],
                explanation="尚无足够证据判断该路线。",
                canonical_version_id=current_version_id,
                policy_version="route-policy-v1",
            )
            for route in RouteType
        ],
        lineage=VersionLineage(
            version_id=current_version_id,
            change_kind="CREATE",
            change_reason="Create an empty canonical asset without inferred content.",
            created_at=created,
        ),
    )
