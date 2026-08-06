from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from typing import Sequence

from .v10_contracts import V10ContractError, stable_digest
from .v10_submission_api import AgencyLaunchRequest, AgencyRunStore


@dataclass(frozen=True)
class SubmissionFlowProfile:
    profile_id: str
    todo_id: str
    vertical: str
    mode: str
    required_artifacts: tuple[str, ...]
    required_capabilities: tuple[str, ...]
    maximum_actions: int
    maximum_cost_usd: float
    required_image_count: int
    required_video_count: int
    requires_real_model: bool = True
    requires_radeon: bool = True

    def __post_init__(self) -> None:
        if self.todo_id not in {"1181", "1182", "1183", "1184"}:
            raise V10ContractError("submission flow must bind TODO 1181-1184")
        if self.vertical not in {"physical_product", "ai_agent_product", "cross_vertical"}:
            raise V10ContractError("submission flow vertical is unknown")
        if self.mode not in {"full", "rapid", "quality"}:
            raise V10ContractError("submission flow mode is unknown")
        if not self.required_artifacts or not self.required_capabilities:
            raise V10ContractError("submission flow requires artifacts and capabilities")
        if not self.requires_real_model or not self.requires_radeon:
            raise V10ContractError("canonical submission flow cannot waive real model or Radeon evidence")

    @property
    def digest(self) -> str:
        return stable_digest(asdict(self))


FLOW_PROFILES = (
    SubmissionFlowProfile(
        "entity-product-full-v1", "1181", "physical_product", "full",
        ("brief", "product_image", "claim_evidence", "brand_rules", "channel_constraints"),
        ("evidence", "strategy", "creative", "production", "compliance"),
        100, 0.0, 12, 3,
    ),
    SubmissionFlowProfile(
        "ai-agent-full-v1", "1182", "ai_agent_product", "full",
        ("brief", "product_ui", "capability_evidence", "competitive_evidence", "buyer_committee"),
        ("evidence", "audience", "strategy", "creative", "compliance"),
        100, 0.0, 12, 3,
    ),
    SubmissionFlowProfile(
        "rapid-realtime-v1", "1183", "cross_vertical", "rapid",
        ("brief", "primary_evidence", "release_owner"),
        ("evidence", "strategy", "compliance"),
        12, 0.0, 0, 0,
    ),
    SubmissionFlowProfile(
        "complete-quality-v1", "1184", "cross_vertical", "quality",
        ("brief", "multimodal_evidence", "brand_rules", "channel_constraints", "release_owner"),
        ("evidence", "audience", "strategy", "creative", "production", "compliance", "experiment"),
        100, 0.0, 12, 3,
    ),
)


def mechanical_preflight(
    profile: SubmissionFlowProfile,
    *,
    store: AgencyRunStore | None = None,
) -> dict[str, object]:
    """Exercise control-plane mechanics without claiming the canonical flow complete."""

    run_store = store or AgencyRunStore()
    artifacts = {
        name: hashlib.sha256(f"synthetic:{profile.profile_id}:{name}".encode()).hexdigest()
        for name in profile.required_artifacts
    }
    request = AgencyLaunchRequest(
        request_id=f"preflight-{profile.profile_id}",
        campaign_id=f"campaign-{profile.profile_id}",
        objective=f"Mechanical preflight for {profile.profile_id}",
        required_capabilities=profile.required_capabilities,
        input_artifacts=artifacts,
        maximum_actions=profile.maximum_actions,
        maximum_cost_usd=profile.maximum_cost_usd,
        created_at="2026-07-31T16:00:00Z",
        data_class="synthetic",
    )
    record = run_store.create(request)
    pre_approval_status = record.status
    run_store.approve(
        record.run_id,
        decision="approve",
        approver="mechanical-preflight-reviewer",
        decided_at="2026-07-31T16:01:00Z",
        reason="Mechanical control-plane preflight only; no model or release evidence",
    )
    bundle = run_store.bundle(record.run_id)
    missing_acceptance_evidence = (
        "real_model_outputs",
        "radeon_execution_trace",
        "required_media_assets" if profile.required_image_count or profile.required_video_count else "live_realtime_latency",
        "independent_quality_evaluation",
    )
    return {
        "schema": "ProofLaunchSubmissionFlowPreflightV1",
        "profile": asdict(profile),
        "profile_sha256": profile.digest,
        "request_sha256": request.digest,
        "run_id": record.run_id,
        "pre_approval_status": pre_approval_status,
        "post_approval_status": record.status,
        "bundle_sha256": hashlib.sha256(bundle).hexdigest(),
        "mechanical_preflight_passed": True,
        "canonical_todo_complete": False,
        "real_model_observed": False,
        "radeon_observed": False,
        "external_release_executed": False,
        "missing_acceptance_evidence": missing_acceptance_evidence,
    }


def build_flow_preflight(profiles: Sequence[SubmissionFlowProfile] = FLOW_PROFILES) -> dict[str, object]:
    if tuple(profile.todo_id for profile in profiles) != ("1181", "1182", "1183", "1184"):
        raise V10ContractError("submission flow profiles must preserve canonical source order")
    receipts = [mechanical_preflight(profile) for profile in profiles]
    return {
        "schema": "ProofLaunchSubmissionFlowPreflightBundleV1",
        "receipts": receipts,
        "mechanical_pass_count": sum(bool(item["mechanical_preflight_passed"]) for item in receipts),
        "canonical_complete_count": sum(bool(item["canonical_todo_complete"]) for item in receipts),
        "truth_boundary": "Four control-plane preflights pass; TODO 1181-1184 remain open until real model, Radeon and required output evidence exist.",
    }
