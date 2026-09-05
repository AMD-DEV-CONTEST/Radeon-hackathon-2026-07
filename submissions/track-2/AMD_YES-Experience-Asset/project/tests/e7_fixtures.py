"""Sanitized public E7 fixtures derived from the existing chair categories."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from app.experience_asset.delivery.approval import FrozenE6ApprovalAdapter
from app.experience_asset.delivery.models import (
    DraftClaimV1,
    DraftSectionV1,
    FrozenE6ApprovalBindingV1,
    RouteDraftContentV1,
    StoredRouteDraftV1,
)
from app.experience_asset.delivery.service import E7DeliveryService
from app.experience_asset.domain.enums import (
    ConfirmationState,
    EvidenceStrength,
    FindingSeverity,
    Milestone,
    MilestoneState,
    PrivacyResolution,
    RouteEligibility,
    RouteType,
    SourceAuthorship,
    SourceKind,
    StatementStatus,
)
from app.experience_asset.domain.factory import new_empty_asset
from app.experience_asset.domain.models import (
    ApprovalRecord,
    ExperienceAssetV1,
    PrivacyFinding,
    RouteDecision,
    SourceReference,
    Statement,
)

NOW = datetime(2026, 8, 2, 2, 0, tzinfo=UTC)
ASSET_ID = UUID("10000000-0000-4000-8000-000000000001")
SOURCE_ID = UUID("10000000-0000-4000-8000-000000000002")
RUN_ID = UUID("10000000-0000-4000-8000-000000000003")
STATEMENT_IDS = [
    UUID("10000000-0000-4000-8000-000000000011"),
    UUID("10000000-0000-4000-8000-000000000012"),
    UUID("10000000-0000-4000-8000-000000000013"),
]
VERSION_IDS = {
    "complete": UUID("10000000-0000-4000-8000-000000000101"),
    "privacy-risk": UUID("10000000-0000-4000-8000-000000000102"),
    "correction": UUID("10000000-0000-4000-8000-000000000103"),
    "route-ineligible": UUID("10000000-0000-4000-8000-000000000104"),
}
FINDING_ID = UUID("10000000-0000-4000-8000-000000000201")
RELATION_PROJECTION_HASH = "c" * 64


def scenarios() -> dict[str, dict[str, str | None]]:
    path = Path(__file__).parent / "fixtures" / "e7_delivery_scenarios.json"
    return json.loads(path.read_text(encoding="utf-8"))


def make_asset(
    scenario: str,
    *,
    parent_version_id: UUID | None = None,
    privacy_resolution: PrivacyResolution | None = None,
) -> ExperienceAssetV1:
    definition = scenarios()[scenario]
    version_id = VERSION_IDS[scenario]
    asset = new_empty_asset(asset_id=ASSET_ID, version_id=version_id, now=NOW)
    source = SourceReference(
        source_id=SOURCE_ID,
        kind=SourceKind.ADAPTED_PUBLIC_FIXTURE,
        display_label=f"Public E7 fixture: {definition['public_fixture']}",
        source_hash="1" * 64,
        source_url="https://www.reddit.com/r/OfficeChairs/comments/hem1s7/",
        adapted_provenance_notice="Paraphrased and anonymized public research fixture.",
        ingested_at=NOW,
        authorship=SourceAuthorship.ADAPTED_RESEARCH,
    )
    corrected = scenario == "correction"
    texts = [
        "The adapted fixture records two separate chair trial periods.",
        (
            "After correction, the second chair was preferred for adjustability during the trial."
            if corrected
            else "The second chair was preferred for comfort and adjustability during the trial."
        ),
        "The experience supports an individual-fit lesson, not a universal recommendation.",
    ]
    statements = [
        Statement(
            statement_id=statement_id,
            text=text,
            status=StatementStatus.SOURCE_FACT if index == 0 else StatementStatus.USER_JUDGMENT,
            source_refs=[SOURCE_ID] if index == 0 else [],
            confirmation=ConfirmationState.CORRECTED
            if corrected and index == 1
            else ConfirmationState.CONFIRMED,
            evidence_strength=EvidenceStrength.DIRECT
            if index == 0
            else EvidenceStrength.SELF_REPORTED,
            created_in_version=version_id,
            last_changed_in_version=version_id,
        )
        for index, (statement_id, text) in enumerate(zip(STATEMENT_IDS, texts, strict=True))
    ]
    selected_route = RouteType(definition["route"])
    selected_eligibility = RouteEligibility(definition["eligibility"])
    decisions = []
    for route in RouteType:
        eligibility = (
            selected_eligibility
            if route is selected_route
            else (
                RouteEligibility.INELIGIBLE
                if route is RouteType.CUSTOMER_EVALUATOR
                else RouteEligibility.ELIGIBLE
            )
        )
        decisions.append(
            RouteDecision(
                route=route,
                eligibility=eligibility,
                reason_codes=["MISSING_QUALIFYING_CONTEXT"]
                if eligibility is RouteEligibility.INELIGIBLE
                else [],
                explanation=(
                    "The adapted fixture has no qualifying professional or customer context."
                    if eligibility is RouteEligibility.INELIGIBLE
                    else "The route is supported by the selected public statements."
                ),
                supporting_statement_ids=[]
                if eligibility is RouteEligibility.INELIGIBLE
                else STATEMENT_IDS,
                canonical_version_id=version_id,
                policy_version="frozen-e6-route-policy-v1",
            )
        )
    findings = []
    requested_resolution = definition["privacy_resolution"]
    if requested_resolution is not None or privacy_resolution is not None:
        resolution = privacy_resolution or PrivacyResolution(requested_resolution)
        findings = [
            PrivacyFinding(
                finding_id=FINDING_ID,
                category="PURCHASE_DETAIL",
                affected_statement_ids=[STATEMENT_IDS[1]],
                severity=FindingSeverity.MEDIUM,
                explanation="A purchase detail needs explicit handling before external delivery.",
                proposed_actions=["GENERALIZE", "REMOVE", "ACKNOWLEDGE"],
                resolution=resolution,
                created_by_run_id=RUN_ID,
                resolved_by_run_id=RUN_ID if resolution is not PrivacyResolution.OPEN else None,
            )
        ]
    payload = asset.model_dump(mode="python")
    payload.update(
        sources=[source],
        statements=statements,
        context="Two anonymized office-chair trials.",
        goal="Retain a bounded, reusable selection lesson.",
        route_decisions=decisions,
        privacy_findings=findings,
        current_milestone=Milestone.M5,
        milestone_states={milestone: MilestoneState.CONFIRMED for milestone in Milestone},
        lineage={
            "version_id": version_id,
            "parent_version_id": parent_version_id,
            "schema_version": "1.0.0",
            "change_kind": "CORRECTION" if corrected else "M5_ROUTE_READY",
            "change_reason": "Public correction fixture." if corrected else "Public E7 fixture.",
            "created_at": NOW,
        },
    )
    return ExperienceAssetV1.model_validate(payload)


def content_for(asset: ExperienceAssetV1, language: str) -> RouteDraftContentV1:
    first, second, boundary = asset.statements
    if language == "zh-CN":
        return RouteDraftContentV1(
            title="椅子试用复盘",
            summary=DraftClaimV1(
                text="两次匿名试用形成了一条有边界的个人选择经验。",
                statement_ids=[first.statement_id, second.statement_id],
            ),
            sections=[
                DraftSectionV1(
                    heading="选择证据",
                    claims=[
                        DraftClaimV1(
                            text="第二把椅子在试用期间更符合个人舒适度与调节偏好。",
                            statement_ids=[second.statement_id],
                        )
                    ],
                ),
                DraftSectionV1(
                    heading="适用边界",
                    claims=[
                        DraftClaimV1(
                            text="这是一条个人适配经验, 不能当作普遍推荐。",
                            statement_ids=[boundary.statement_id],
                        )
                    ],
                ),
            ],
        )
    return RouteDraftContentV1(
        title="What two chair trials clarified",
        summary=DraftClaimV1(
            text="Two anonymized trials produced one bounded personal selection lesson.",
            statement_ids=[first.statement_id, second.statement_id],
        ),
        sections=[
            DraftSectionV1(
                heading="Decision evidence",
                claims=[
                    DraftClaimV1(
                        text=second.text,
                        statement_ids=[second.statement_id],
                    )
                ],
            ),
            DraftSectionV1(
                heading="Transfer boundary",
                claims=[
                    DraftClaimV1(
                        text=boundary.text,
                        statement_ids=[boundary.statement_id],
                    )
                ],
            ),
        ],
    )


def approval_for(
    draft: StoredRouteDraftV1,
    *,
    approved_at: datetime | None = None,
    route_draft_hash: str = "a" * 64,
    privacy_review_hash: str = "b" * 64,
) -> ApprovalRecord:
    return ApprovalRecord(
        approval_id=uuid5(NAMESPACE_URL, f"e7-frozen-approval:{draft.draft.route_draft_id}"),
        user_action="APPROVE_SHAREABLE_EXPORT",
        approved_at=approved_at or draft.created_at + timedelta(seconds=1),
        asset_id=draft.asset_id,
        version_id=draft.draft.canonical_version_id,
        route=draft.draft.route,
        language=draft.draft.language,
        route_draft_hash=route_draft_hash,
        privacy_review_hash=privacy_review_hash,
        finding_resolutions=draft.privacy_finding_resolutions,
    )


def approval_binding_for(
    draft: StoredRouteDraftV1,
    approval: ApprovalRecord,
    *,
    fixture_id: str = "synthetic-e6-contract-fixture/v1",
    source_e6_commit: str | None = None,
) -> FrozenE6ApprovalBindingV1:
    return FrozenE6ApprovalBindingV1(
        fixture_id=fixture_id,
        source_e6_commit=source_e6_commit,
        route_draft_id=draft.draft.route_draft_id,
        asset_id=draft.asset_id,
        version_id=draft.draft.canonical_version_id,
        asset_version_hash=draft.asset_version_hash,
        relation_projection_hash=draft.relation_projection_hash,
        route=draft.draft.route,
        language=draft.draft.language,
        draft_content_hash=draft.draft.content_hash,
        renderer_input_identity=draft.renderer_input_identity,
        privacy_state_hash=draft.privacy_state_hash,
        approval=approval,
    )


def register_approval(
    delivery: E7DeliveryService,
    draft: StoredRouteDraftV1,
    approval: ApprovalRecord | None = None,
) -> ApprovalRecord:
    issued = approval or approval_for(draft)
    adapter = delivery.approval_validator
    assert isinstance(adapter, FrozenE6ApprovalAdapter)
    adapter.register_fixture(approval_binding_for(draft, issued))
    return issued
