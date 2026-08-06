from __future__ import annotations

import hashlib
import io
import json
import re
import threading
import zipfile
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .audience_pulse import LexicalAudiencePulse, VALID_EMOTIONS
from .contracts import (
    CampaignRequest,
    CampaignState,
    ReleaseApproval,
    ReleaseApprovalKind,
    ReleaseDecision,
    Stage,
)
from .gtm_memory import (
    ApprovalStatus,
    MemoryEntry,
    MemoryKind,
    MemoryScope,
    MemorySource,
    ProjectMemory,
)
from .gtm_effect_feedback import EffectFeedbackError, compile_effect_observation
from .gtm_production_observation_kit import (
    ProductionObservationKitError,
    compile_aggregate_attribution_plan,
    compile_production_observation_field_kit,
)
from .gtm_manual_publication_receipt import (
    ManualPublicationReceiptError,
    compile_manual_publication_receipt,
)
from .gtm_revenue_feedback import RevenueFeedbackError, compile_revenue_economics
from .gtm_content_calendar import (
    ContentCalendarError,
    compile_content_calendar,
    verify_content_calendar,
)
from .gtm_distribution_operations import (
    DistributionOperationsError,
    compile_distribution_operations,
)
from .gtm_revenue_journey import (
    RevenueJourneyError,
    compile_revenue_journey_operations,
)
from .gtm_mechanism_abstraction import compile_mechanism_abstraction_register
from .gtm_promotion_governance import compile_promotion_governance
from .gtm_learning_memory import (
    LearningMemoryError,
    compile_project_learning_context,
    compile_strategy_memory_application,
    compile_strategy_memory_decision,
    compile_strategy_memory_resolution_context,
    promoted_memory_payload,
    strategy_memory_resolution_payload,
    validate_project_learning_context,
    validate_strategy_memory_application,
    validate_strategy_memory_decision,
    validate_strategy_memory_resolution_context,
)
from .gtm_memory_capsule import (
    MemoryCapsuleError,
    issue_memory_capsule,
    merge_project_learning_contexts,
    verify_memory_capsule,
)
from .gtm_adaptive_capability_graph import (
    AdaptiveContext,
    compile_context as compile_adaptive_context,
    distribution_operating_floor,
)
from .gtm_production_pack import ProductionPackCompiler, ProductionPackError
from .gtm_brief_intelligence import (
    BriefIntelligenceError,
    ProductEvidenceInput,
    compile_brief_intelligence,
    compile_product_evidence_register,
)
from .gtm_signal_intelligence import (
    SignalIntelligenceError,
    empty_signal_intelligence,
    parse_and_compile_signal_intelligence,
)
from .graph_loop_harness import production_graph_loop_harness
from .gtm_strategy import (
    AudienceICP,
    BrandConstitution,
    BudgetTier,
    BusinessModel,
    CampaignStrategyInput,
    ClaimEvidence,
    CompanyScale,
    ContentCapacity,
    DistributionStrength,
    EvidenceRights,
    IndustryRisk,
    LifecycleStage,
    ProductSurface,
    SalesMotion,
    StrategyCompiler,
    StrategyContractError,
    strategy_digest as gtm_strategy_digest,
)
from .ledger import EvidenceLedger, canonical_json
from .files import atomic_write_bytes
from .runtime import build_supervisor
from .v10_submission_store import (
    ConflictError,
    JobRecord,
    SubmissionStore,
)
from .workflow import Supervisor, WorkflowBlocked


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_TERMINAL_STATUSES = frozenset(
    {"bundle_ready", "blocked", "failed", "rejected", "cancelled"}
)
_PUBLIC_EVENT_FIELDS = frozenset(
    {
        "count",
        "round",
        "asset_count",
        "finding_count",
        "blocker_count",
        "claim_count",
        "brief_count",
        "emotion_matches",
        "preview_digest",
        "approval_id",
    }
)
_STRATEGY_ARTIFACT_NAMES = (
    "brief-intelligence.json",
    "product-evidence-register.json",
    "gtm-strategy.json",
    "seven-day-schedule.json",
    "seo-geo-questions.json",
    "experiment.json",
    "gtm-production-pack.json",
    "big-idea-and-message-hierarchy.json",
    "channel-copy.json",
    "landing-page-draft.json",
    "lifecycle-email-draft.json",
    "channel-portfolio.json",
    "breakout-growth-loop.json",
    "text-creative-challenger-plan.json",
    "industry-gtm-profile.json",
    "creative-strategy-kernel.json",
    "editorial-quality-receipt.json",
    "multimodal-direction-receipt.json",
    "content-calendar.json",
    "distribution-operations.json",
    "revenue-journey-operations.json",
    "mechanism-abstraction-register.json",
    "promotion-governance.json",
    "seo-geo-faq-drafts.json",
    "video-production-brief.json",
    "audio-production-brief.json",
    "analytics-plan.json",
    "manual-release-instructions.json",
    "graph-loop-harness.json",
    "creative-signal-intelligence.json",
    "approved-learning-context.json",
    "approved-strategy-memory-resolutions.json",
)

_GTM_EFFECT_CAPABILITIES = (
    "cross_device_memory",
    "data_strategy",
    "content_scheduling",
    "video_generation",
    "audio_generation",
    "text_generation",
    "data_analysis",
    "geo_visibility",
    "seo_operations",
    "employee_agent",
    "advertising",
)

_CAPABILITY_DELIVERABLE_ARTIFACTS = {
    "data_strategy": "gtm-strategy.json",
    "content_scheduling": "content-calendar.json",
    "text_generation": "channel-copy.json",
    "data_analysis": "analytics-plan.json",
    "geo_visibility": "seo-geo-faq-drafts.json",
    "seo_operations": "seo-geo-questions.json",
    "employee_agent": "graph-loop-harness.json",
    "advertising": "channel-portfolio.json",
}


def _compile_capability_effect_matrix(
    *,
    strategy: Mapping[str, Any],
    workspace: Mapping[str, Any],
    portfolio: Mapping[str, Any],
    calendar: Mapping[str, Any],
    inherited_memory_count: int,
    multimodal_deliverables: tuple[Any, ...] = (),
    multimodal_reviews: tuple[Any, ...] = (),
    capability_deliverables: tuple[Any, ...] = (),
    capability_reviews: tuple[Any, ...] = (),
) -> dict[str, Any]:
    """Separate connected product contracts from observed production effect."""

    workspace_available = bool(workspace)
    strategy_available = bool(strategy)
    schedule_slots = calendar.get("slots")
    schedule_ready = isinstance(schedule_slots, list) and len(schedule_slots) == 7
    portfolio_rows = portfolio.get("portfolio")
    advertising_ready = isinstance(portfolio_rows, list) and len(portfolio_rows) == 12
    all_deliverables = (*multimodal_deliverables, *capability_deliverables)
    all_reviews = (*multimodal_reviews, *capability_reviews)
    deliverable_by_capability = {item.capability_id: item for item in all_deliverables}
    passed_registration_ids = {
        item.registration_id
        for item in all_reviews
        if item.decision == "pass"
    }

    def registered_stage(capability_id: str, fallback: str) -> str:
        deliverable = deliverable_by_capability.get(capability_id)
        if deliverable is None:
            return fallback
        if deliverable.registration_id in passed_registration_ids:
            return "generated_human_review_passed"
        return "generated_unreviewed"

    stages = {
        "cross_device_memory": (
            "approved_context_available"
            if inherited_memory_count > 0
            else "contract_ready"
        ),
        "data_strategy": registered_stage(
            "data_strategy", "source_bound_draft" if strategy_available else "pending"
        ),
        "content_scheduling": registered_stage(
            "content_scheduling", "source_bound_draft" if schedule_ready else "pending"
        ),
        "video_generation": (
            "generated_human_review_passed"
            if deliverable_by_capability.get("video_generation")
            and deliverable_by_capability["video_generation"].registration_id
            in passed_registration_ids
            else "generated_unreviewed"
            if deliverable_by_capability.get("video_generation")
            else "brief_only"
            if workspace_available
            else "pending"
        ),
        "audio_generation": (
            "generated_human_review_passed"
            if deliverable_by_capability.get("audio_generation")
            and deliverable_by_capability["audio_generation"].registration_id
            in passed_registration_ids
            else "generated_unreviewed"
            if deliverable_by_capability.get("audio_generation")
            else "brief_only"
            if workspace_available
            else "pending"
        ),
        "text_generation": registered_stage(
            "text_generation", "source_bound_drafts" if workspace_available else "pending"
        ),
        "data_analysis": registered_stage(
            "data_analysis", "measurement_plan_only" if workspace_available else "pending"
        ),
        "geo_visibility": registered_stage(
            "geo_visibility", "source_bound_draft" if workspace_available else "pending"
        ),
        "seo_operations": registered_stage(
            "seo_operations", "source_bound_draft" if workspace_available else "pending"
        ),
        "employee_agent": registered_stage("employee_agent", "local_graph_observed"),
        "advertising": registered_stage(
            "advertising", "plan_only_activation_disabled" if advertising_ready else "pending"
        ),
    }
    evidence = {
        "cross_device_memory": "signed aggregate memory contract; human application required",
        "data_strategy": "immutable operating context plus industry/channel strategy",
        "content_scheduling": "seven-slot timezone-bound review calendar",
        "video_generation": (
            "rights-cleared run-bound video master with immutable execution receipt"
            if "video_generation" in deliverable_by_capability
            else "video production brief; no run-bound generated video"
        ),
        "audio_generation": (
            "rights-cleared run-bound audio master with immutable execution receipt"
            if "audio_generation" in deliverable_by_capability
            else "audio production brief; no run-bound generated audio"
        ),
        "text_generation": "channel, landing, email and SEO/GEO drafts",
        "data_analysis": "preregistered analytics and observation contract",
        "geo_visibility": "answer-visibility FAQ draft with source citation",
        "seo_operations": "owned-site SEO draft; no measured ranking change",
        "employee_agent": "durable tenant-scoped Graph/Loop/Harness run",
        "advertising": "twelve-route channel plan; spend and activation disabled",
    }
    next_gate = {
        "cross_device_memory": "named human review and later-run application",
        "data_strategy": "blind strategist preference on the frozen brief",
        "content_scheduling": "human approval followed by observed delivery receipts",
        "video_generation": (
            "pass named blind review against the frozen video rubric"
            if "video_generation" in deliverable_by_capability
            else "generate a rights-cleared run-bound master and pass blind review"
        ),
        "audio_generation": (
            "pass named listening review against the frozen audio rubric"
            if "audio_generation" in deliverable_by_capability
            else "generate a rights-cleared run-bound master and pass listening review"
        ),
        "text_generation": "blind human preference and channel outcome observation",
        "data_analysis": "bind one real production observation to the preregistered experiment",
        "geo_visibility": "measure answer citation/share on the declared query panel",
        "seo_operations": "measure owned-site defects, rank and qualified conversion change",
        "employee_agent": "deployed trace coverage and real-traffic guardrail calibration",
        "advertising": "separate human authorization plus randomized incremental lift",
    }
    rows = []
    for capability_id in _GTM_EFFECT_CAPABILITIES:
        deliverable = deliverable_by_capability.get(capability_id)
        human_passed = bool(
            deliverable and deliverable.registration_id in passed_registration_ids
        )
        row = {
            "capability_id": capability_id,
            "evidence_stage": stages[capability_id],
            "evidence": evidence[capability_id],
            "next_gate": next_gate[capability_id],
            "generated_deliverable_observed": deliverable is not None,
            "named_human_quality_observed": human_passed,
            "production_effect_attributed": False,
        }
        if deliverable is not None:
            row["deliverable_registration_id"] = deliverable.registration_id
            row["deliverable_sha256"] = deliverable.artifact_sha256
            row["execution_receipt_sha256"] = deliverable.execution_receipt_sha256
            if hasattr(deliverable, "artifact_role"):
                row["artifact_role"] = deliverable.artifact_role
            row["model_id"] = deliverable.model_id
            row["model_revision"] = deliverable.model_revision
            row["accelerator"] = deliverable.accelerator
        rows.append(row)
    connected = sum(row["evidence_stage"] != "pending" for row in rows)
    generated_count = sum(row["generated_deliverable_observed"] for row in rows)
    human_count = sum(row["named_human_quality_observed"] for row in rows)
    return {
        "schema": "ProofLaunchGTMCapabilityEffectMatrixV1",
        "capability_count": len(rows),
        "contract_connected_count": connected,
        "generated_deliverable_count": generated_count,
        "named_human_quality_count": human_count,
        "production_effect_attributed_count": 0,
        "all_capability_effects_proven": False,
        "capabilities": rows,
        "truth_boundary": (
            "A registered master proves only run-bound generation and integrity; a passed "
            "named review proves only the frozen review decision. Neither proves publication, "
            "incremental effect, revenue, 4A preference or Top-1 standing."
        ),
    }


class ProductionRuntimeError(RuntimeError):
    """A fail-closed production runtime contract violation."""


@dataclass(frozen=True)
class ProductionLaunchRequest:
    """Minimal rights-bound request for the Day-3 GTM vertical slice."""

    request_id: str
    campaign_id: str
    product_name: str
    specification_text: str
    market: str
    platform: str
    goal: str
    target_emotion: str
    product_image_sha256: str
    rights_basis: str
    creative_signal_snapshot_sha256: str | None = None
    creative_signal_collection_receipt_sha256: str | None = None
    creative_signal_data_class: str | None = None
    learning_context_sha256: str | None = None
    strategy_memory_resolution_context_sha256: str | None = None
    rights_confirmed: bool = True
    maximum_actions: int = 12
    maximum_cost_usd: float = 0.0
    human_release_required: bool = True
    data_class: str = "internal"
    org_id: str = "org-local"
    project_id: str = "project-local"
    owner: str = "rights-attestor-unspecified"
    industry: str = "unspecified"
    business_model: str = BusinessModel.B2C.value
    lifecycle: str = LifecycleStage.LAUNCH.value
    budget: str = BudgetTier.ZERO.value
    industry_risk: str = IndustryRisk.STANDARD.value
    company_scale: str = CompanyScale.STARTUP.value
    brand_reach: str = DistributionStrength.EMERGING.value
    owned_audience_strength: str = DistributionStrength.EMERGING.value
    community_access: str = DistributionStrength.EMERGING.value
    partner_access: str = DistributionStrength.EMERGING.value
    content_capacity: str = ContentCapacity.STANDARD.value
    sales_motion: str = SalesMotion.HYBRID.value
    product_category: str = "owner_category_unspecified"
    product_surface: str = ProductSurface.WEB_APP.value
    audience_role: str = "owner_role_unspecified"
    audience_name: str = "intended audience"
    audience_problem: str = "needs reliable evidence before taking the next step"
    audience_outcome: str = "make an informed next-step decision"
    buying_context: str = "owner context not supplied"
    brand_purpose: str = "Help the audience evaluate the product using traceable evidence."
    customer_promise: str = "A traceable, reviewable product explanation."
    brand_voice: str = "specific, calm, evidence-first"
    offer: str = "review the owner-attested product evidence"
    landing_url: str = "https://example.invalid/pending-owner-input"
    schedule_timezone: str = "UTC"
    claim_assurance: str = "owner_attested"
    claim_approved_by: str | None = None
    specialist_approved_by: str | None = None
    product_claims: tuple[ProductEvidenceInput, ...] = ()
    schema: str = "ProofLaunchProductionLaunchRequestV1"

    def __post_init__(self) -> None:
        normalized_claims: list[ProductEvidenceInput] = []
        for claim in self.product_claims:
            if isinstance(claim, ProductEvidenceInput):
                normalized_claims.append(claim)
            elif isinstance(claim, Mapping):
                try:
                    normalized_claims.append(ProductEvidenceInput.from_mapping(claim))
                except BriefIntelligenceError as error:
                    raise ProductionRuntimeError(
                        f"product evidence contract failed: {error}"
                    ) from error
            else:
                raise ProductionRuntimeError("product claims must be evidence objects")
        object.__setattr__(self, "product_claims", tuple(normalized_claims))
        bounded = {
            "request_id": (self.request_id, 128),
            "campaign_id": (self.campaign_id, 128),
            "product_name": (self.product_name, 200),
            "specification_text": (self.specification_text, 20_000),
            "market": (self.market, 120),
            "platform": (self.platform, 120),
            "goal": (self.goal, 1_000),
            "rights_basis": (self.rights_basis, 1_000),
            "org_id": (self.org_id, 128),
            "project_id": (self.project_id, 128),
            "owner": (self.owner, 200),
            "industry": (self.industry, 200),
            "product_category": (self.product_category, 200),
            "audience_role": (self.audience_role, 160),
            "audience_name": (self.audience_name, 300),
            "audience_problem": (self.audience_problem, 1_000),
            "audience_outcome": (self.audience_outcome, 1_000),
            "buying_context": (self.buying_context, 1_000),
            "brand_purpose": (self.brand_purpose, 1_000),
            "customer_promise": (self.customer_promise, 1_000),
            "brand_voice": (self.brand_voice, 500),
            "offer": (self.offer, 1_000),
            "landing_url": (self.landing_url, 2_000),
            "schedule_timezone": (self.schedule_timezone, 64),
        }
        for name, (value, maximum) in bounded.items():
            if not isinstance(value, str) or not value.strip() or len(value) > maximum:
                raise ProductionRuntimeError(f"{name} must be a non-empty bounded string")
            if "\x00" in value:
                raise ProductionRuntimeError(f"{name} contains a NUL byte")
        if not _SAFE_ID.fullmatch(self.request_id) or not _SAFE_ID.fullmatch(
            self.campaign_id
        ):
            raise ProductionRuntimeError("request and campaign IDs contain unsafe characters")
        if not _SHA256.fullmatch(self.product_image_sha256):
            raise ProductionRuntimeError("product image must be content-addressed by SHA-256")
        if self.creative_signal_snapshot_sha256 is not None and not _SHA256.fullmatch(
            self.creative_signal_snapshot_sha256
        ):
            raise ProductionRuntimeError(
                "creative signal snapshot must be content-addressed by SHA-256"
            )
        if (
            self.creative_signal_collection_receipt_sha256 is not None
            and not _SHA256.fullmatch(
                self.creative_signal_collection_receipt_sha256
            )
        ):
            raise ProductionRuntimeError(
                "creative signal collection receipt must be content-addressed by SHA-256"
            )
        if self.learning_context_sha256 is not None and not _SHA256.fullmatch(
            self.learning_context_sha256
        ):
            raise ProductionRuntimeError(
                "learning context must be content-addressed by SHA-256"
            )
        if (
            self.strategy_memory_resolution_context_sha256 is not None
            and not _SHA256.fullmatch(
                self.strategy_memory_resolution_context_sha256
            )
        ):
            raise ProductionRuntimeError(
                "strategy memory resolution context must be content-addressed by SHA-256"
            )
        if self.target_emotion not in VALID_EMOTIONS:
            raise ProductionRuntimeError("target_emotion is outside the supported label set")
        if self.rights_confirmed is not True:
            raise ProductionRuntimeError("product input rights must be explicitly confirmed")
        if self.human_release_required is not True:
            raise ProductionRuntimeError("human release cannot be disabled")
        if type(self.maximum_actions) is not int or not 5 <= self.maximum_actions <= 24:
            raise ProductionRuntimeError("maximum_actions must be an integer in [5, 24]")
        if type(self.maximum_cost_usd) not in {int, float} or self.maximum_cost_usd != 0:
            raise ProductionRuntimeError("the local deterministic slice has a zero spend cap")
        if self.data_class not in {"synthetic", "internal", "confidential"}:
            raise ProductionRuntimeError("data_class is unsupported")
        signal_components = (
            self.creative_signal_snapshot_sha256,
            self.creative_signal_collection_receipt_sha256,
            self.creative_signal_data_class,
        )
        if any(item is not None for item in signal_components) and not all(
            item is not None for item in signal_components
        ):
            raise ProductionRuntimeError(
                "creative signals require a snapshot, collection receipt and field-level data class"
            )
        if self.creative_signal_data_class not in {None, "public"}:
            raise ProductionRuntimeError(
                "open-source creative signals must use the public field-level data class"
            )
        try:
            BusinessModel(self.business_model)
            LifecycleStage(self.lifecycle)
            BudgetTier(self.budget)
            risk = IndustryRisk(self.industry_risk)
            CompanyScale(self.company_scale)
            DistributionStrength(self.brand_reach)
            DistributionStrength(self.owned_audience_strength)
            DistributionStrength(self.community_access)
            DistributionStrength(self.partner_access)
            ContentCapacity(self.content_capacity)
            SalesMotion(self.sales_motion)
            ProductSurface(self.product_surface)
        except ValueError as error:
            raise ProductionRuntimeError("strategy dimensions contain an unknown value") from error
        if not self.landing_url.startswith(("https://", "http://")):
            raise ProductionRuntimeError("landing_url must be HTTP(S)")
        try:
            ZoneInfo(self.schedule_timezone)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ProductionRuntimeError(
                "schedule_timezone must be an installed IANA timezone"
            ) from error
        if not tuple(
            item.strip() for item in self.brand_voice.split(",") if item.strip()
        ):
            raise ProductionRuntimeError("brand_voice must contain a usable principle")
        if self.claim_assurance not in {"owner_attested", "verified"}:
            raise ProductionRuntimeError(
                "claim_assurance must be owner_attested or verified"
            )
        if self.claim_assurance == "verified" and not (
            isinstance(self.claim_approved_by, str) and self.claim_approved_by.strip()
        ):
            raise ProductionRuntimeError(
                "verified claims require a named claim_approved_by"
            )
        if self.claim_approved_by is not None and (
            not isinstance(self.claim_approved_by, str)
            or not self.claim_approved_by.strip()
            or len(self.claim_approved_by) > 200
        ):
            raise ProductionRuntimeError("claim_approved_by must be a bounded name")
        if self.specialist_approved_by is not None and (
            not isinstance(self.specialist_approved_by, str)
            or not self.specialist_approved_by.strip()
            or len(self.specialist_approved_by) > 200
        ):
            raise ProductionRuntimeError("specialist_approved_by must be a bounded name")
        if risk is IndustryRisk.HIGH_REGULATION and not (
            self.specialist_approved_by
            or (
                self.product_claims
                and all(claim.specialist_approved_by for claim in self.product_claims)
            )
        ):
            raise ProductionRuntimeError(
                "high-regulation strategy requires a named specialist approval"
            )
        if self.product_claims:
            claim_ids = [claim.claim_id for claim in self.product_claims]
            if len(claim_ids) != len(set(claim_ids)):
                raise ProductionRuntimeError("product claim IDs must be unique")

    @property
    def digest(self) -> str:
        return hashlib.sha256(canonical_json(asdict(self)).encode("utf-8")).hexdigest()

    @property
    def run_id(self) -> str:
        return f"run-{self.digest[:24]}"

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "ProductionLaunchRequest":
        if not isinstance(payload, Mapping):
            raise ProductionRuntimeError("launch payload must be an object")
        campaign = payload.get("campaign")
        artifacts = payload.get("input_artifacts")
        rights = payload.get("rights")
        strategy = payload.get("strategy", {})
        if not isinstance(campaign, Mapping):
            raise ProductionRuntimeError("campaign must be an object")
        allowed_artifacts = {
            "product_image",
            "creative_signal_snapshot",
            "creative_signal_collection_receipt",
        }
        if (
            not isinstance(artifacts, Mapping)
            or "product_image" not in artifacts
            or not set(artifacts).issubset(allowed_artifacts)
        ):
            raise ProductionRuntimeError(
                "input_artifacts must contain only product_image and the optional "
                "creative signal snapshot/collection receipt pair"
            )
        if not isinstance(rights, Mapping):
            raise ProductionRuntimeError("rights must be an object")
        if not isinstance(strategy, Mapping):
            raise ProductionRuntimeError("strategy must be an object when supplied")
        raw_product_claims = strategy.get("product_claims", [])
        if not isinstance(raw_product_claims, list):
            raise ProductionRuntimeError("strategy.product_claims must be a list")
        try:
            product_claims = tuple(
                ProductEvidenceInput.from_mapping(item)
                for item in raw_product_claims
            )
        except BriefIntelligenceError as error:
            raise ProductionRuntimeError(
                f"product evidence contract failed: {error}"
            ) from error
        try:
            return cls(
                request_id=str(payload["request_id"]),
                campaign_id=str(payload["campaign_id"]),
                product_name=str(campaign["product_name"]),
                specification_text=str(campaign["specification_text"]),
                market=str(campaign["market"]),
                platform=str(campaign["platform"]),
                goal=str(campaign["goal"]),
                target_emotion=str(campaign.get("target_emotion", "joy")),
                product_image_sha256=str(artifacts["product_image"]),
                creative_signal_snapshot_sha256=(
                    str(artifacts["creative_signal_snapshot"])
                    if artifacts.get("creative_signal_snapshot") is not None
                    else None
                ),
                creative_signal_collection_receipt_sha256=(
                    str(artifacts["creative_signal_collection_receipt"])
                    if artifacts.get("creative_signal_collection_receipt") is not None
                    else None
                ),
                creative_signal_data_class=(
                    str(payload["creative_signal_data_class"])
                    if payload.get("creative_signal_data_class") is not None
                    else None
                ),
                rights_basis=str(rights["basis"]),
                rights_confirmed=rights.get("confirmed") is True,
                maximum_actions=payload.get("maximum_actions", 12),
                maximum_cost_usd=payload.get("maximum_cost_usd", 0),
                human_release_required=payload.get("human_release_required", True),
                data_class=str(payload.get("data_class", "internal")),
                org_id=str(strategy.get("org_id", "org-local")),
                project_id=str(strategy.get("project_id", "project-local")),
                owner=str(strategy.get("owner", "rights-attestor-unspecified")),
                industry=str(strategy.get("industry", "unspecified")),
                business_model=str(strategy.get("business_model", BusinessModel.B2C.value)),
                lifecycle=str(strategy.get("lifecycle", LifecycleStage.LAUNCH.value)),
                budget=str(strategy.get("budget", BudgetTier.ZERO.value)),
                industry_risk=str(
                    strategy.get("industry_risk", IndustryRisk.STANDARD.value)
                ),
                company_scale=str(
                    strategy.get("company_scale", CompanyScale.STARTUP.value)
                ),
                brand_reach=str(
                    strategy.get(
                        "brand_reach", DistributionStrength.EMERGING.value
                    )
                ),
                owned_audience_strength=str(
                    strategy.get(
                        "owned_audience_strength",
                        DistributionStrength.EMERGING.value,
                    )
                ),
                community_access=str(
                    strategy.get(
                        "community_access", DistributionStrength.EMERGING.value
                    )
                ),
                partner_access=str(
                    strategy.get(
                        "partner_access", DistributionStrength.EMERGING.value
                    )
                ),
                content_capacity=str(
                    strategy.get("content_capacity", ContentCapacity.STANDARD.value)
                ),
                sales_motion=str(
                    strategy.get("sales_motion", SalesMotion.HYBRID.value)
                ),
                product_category=str(
                    strategy.get("product_category", "owner_category_unspecified")
                ),
                product_surface=str(
                    strategy.get("product_surface", ProductSurface.WEB_APP.value)
                ),
                audience_role=str(
                    strategy.get("audience_role", "owner_role_unspecified")
                ),
                audience_name=str(strategy.get("audience_name", "intended audience")),
                audience_problem=str(
                    strategy.get(
                        "audience_problem",
                        "needs reliable evidence before taking the next step",
                    )
                ),
                audience_outcome=str(
                    strategy.get(
                        "audience_outcome", "make an informed next-step decision"
                    )
                ),
                buying_context=str(
                    strategy.get("buying_context", "owner context not supplied")
                ),
                brand_purpose=str(
                    strategy.get(
                        "brand_purpose",
                        "Help the audience evaluate the product using traceable evidence.",
                    )
                ),
                customer_promise=str(
                    strategy.get(
                        "customer_promise",
                        "A traceable, reviewable product explanation.",
                    )
                ),
                brand_voice=str(
                    strategy.get("brand_voice", "specific, calm, evidence-first")
                ),
                offer=str(
                    strategy.get(
                        "offer", "review the owner-attested product evidence"
                    )
                ),
                landing_url=str(
                    strategy.get(
                        "landing_url", "https://example.invalid/pending-owner-input"
                    )
                ),
                schedule_timezone=str(strategy.get("schedule_timezone", "UTC")),
                claim_assurance=str(
                    strategy.get("claim_assurance", "owner_attested")
                ),
                claim_approved_by=(
                    str(strategy["claim_approved_by"])
                    if strategy.get("claim_approved_by") is not None
                    else None
                ),
                specialist_approved_by=(
                    str(strategy["specialist_approved_by"])
                    if strategy.get("specialist_approved_by") is not None
                    else None
                ),
                product_claims=product_claims,
            )
        except KeyError as error:
            raise ProductionRuntimeError(f"missing launch field: {error.args[0]}") from error


def _pretty_json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _named_artifact_set_sha256(documents: Mapping[str, bytes]) -> str:
    """Bind a non-empty, explicitly named artifact set into one stable receipt."""

    if not documents or any(not name or not isinstance(payload, bytes) for name, payload in documents.items()):
        raise ProductionRuntimeError("named artifact set is invalid")
    receipt = [
        {
            "name": name,
            "sha256": hashlib.sha256(documents[name]).hexdigest(),
        }
        for name in sorted(documents)
    ]
    return hashlib.sha256(canonical_json(receipt).encode("utf-8")).hexdigest()


def _artifact_set_sha256(documents: Mapping[str, bytes]) -> str:
    """Bind every GTM artifact name and content digest into one stable receipt."""

    if set(documents) != set(_STRATEGY_ARTIFACT_NAMES):
        raise ProductionRuntimeError("GTM artifact set is incomplete")
    return _named_artifact_set_sha256(documents)


def _first_owner_claim(specification_text: str) -> str:
    spans = [
        item.strip()
        for item in re.split(
            r"(?<=[.!?])\s+|[\n;]+", specification_text.strip()
        )
        if item.strip()
    ]
    if not spans:
        raise ProductionRuntimeError("strategy requires a non-empty owner claim")
    return spans[0]


def _strategy_documents(
    launch: ProductionLaunchRequest,
    *,
    run_id: str,
    compiled_at: str,
    signal_intelligence: Mapping[str, Any] | None = None,
    learning_context: Mapping[str, Any] | None = None,
    strategy_memory_resolution_context: Mapping[str, Any] | None = None,
) -> dict[str, bytes]:
    """Compile deterministic, draft-only strategy artifacts.

    The requester has attested input rights, but ProofLaunch has not
    independently verified the product claim. The strategy compiler therefore
    receives an explicit owner approval identity while every outward artifact
    retains the narrower ``owner_attested`` assurance boundary.
    """

    governed_learning = validate_project_learning_context(
        dict(learning_context or compile_project_learning_context([]))
    )
    governed_resolutions = validate_strategy_memory_resolution_context(
        dict(
            strategy_memory_resolution_context
            or compile_strategy_memory_resolution_context([])
        )
    )
    governed_signals = dict(signal_intelligence or empty_signal_intelligence())
    raw_hypotheses = governed_signals.get("hypotheses", [])
    signal_hypotheses = [
        {
            "hypothesis_id": str(item["hypothesis_id"]),
            "feature": str(item["feature"]),
            "statement": str(item["statement"]),
            "status": str(item["status"]),
        }
        for item in raw_hypotheses
        if isinstance(item, Mapping)
        and all(
            isinstance(item.get(field), str)
            for field in ("hypothesis_id", "feature", "statement", "status")
        )
    ][:3]
    signal_guidance = {
        "source_snapshot_sha256": governed_signals.get("source_snapshot_sha256"),
        "input_artifact_sha256": governed_signals.get("input_artifact_sha256"),
        "collection_receipt_artifact_sha256": governed_signals.get(
            "collection_receipt_artifact_sha256"
        ),
        "collection_receipt_sha256": governed_signals.get(
            "collection_receipt_sha256"
        ),
        "collection_plan_sha256": governed_signals.get(
            "collection_plan_sha256"
        ),
        "collection_run_count": governed_signals.get("collection_run_count", 0),
        "collection_status": governed_signals.get("collection_status", "not_supplied"),
        "evidence_sufficient_for_hypothesis_generation": bool(
            governed_signals.get("evidence_sufficient_for_hypothesis_generation", False)
        ),
        "hypothesis_queue": signal_hypotheses,
        "queue_status": (
            "pending_human_experiment_review"
            if signal_hypotheses
            else "no_admissible_signal_hypotheses"
        ),
        "automatic_strategy_mutation_executed": False,
        "automatic_schedule_mutation_executed": False,
        "external_activation_executed": False,
        "human_review_required_before_application": True,
    }
    authorized_platform_counts: dict[str, int] = {}
    raw_platform_counts = governed_signals.get("platform_counts")
    if (
        signal_guidance["evidence_sufficient_for_hypothesis_generation"]
        and isinstance(raw_platform_counts, Mapping)
    ):
        authorized_platform_counts = {
            str(platform).strip().casefold(): int(count)
            for platform, count in raw_platform_counts.items()
            if str(platform).strip() and type(count) is int and count > 0
        }
    signal_guidance["authorized_platform_counts_applied"] = dict(
        sorted(authorized_platform_counts.items())
    )
    signal_guidance["platform_signal_decision_input_used"] = bool(
        authorized_platform_counts
    )
    specification_sha256 = hashlib.sha256(
        launch.specification_text.encode("utf-8")
    ).hexdigest()
    if launch.product_claims:
        product_evidence_inputs = launch.product_claims
    else:
        product_evidence_inputs = (
            ProductEvidenceInput(
                claim_id="claim-owner-001",
                claim_type="feature",
                claim_text=_first_owner_claim(launch.specification_text),
                source_uri=(
                    f"request://{launch.request_id}/specification_text#claim-owner-001"
                ),
                source_sha256=specification_sha256,
                rights_status=(
                    "owner_approved"
                    if launch.claim_assurance == "verified"
                    else "owner_attested"
                ),
                rights_reference=launch.rights_basis,
                release_scope=(
                    "campaign_public_channels"
                    if launch.claim_assurance == "verified"
                    else "draft_only"
                ),
                valid_from=compiled_at,
                approved_by=launch.claim_approved_by,
                specialist_approved_by=launch.specialist_approved_by,
            ),
        )
    try:
        product_evidence_register = compile_product_evidence_register(
            product_evidence_inputs,
            evaluated_at=compiled_at,
            high_regulation=(launch.industry_risk == IndustryRisk.HIGH_REGULATION.value),
        )
    except BriefIntelligenceError as error:
        raise ProductionRuntimeError(
            f"product evidence register failed: {error}"
        ) from error

    rights_by_status = {
        "owner_attested": EvidenceRights.OWNED,
        "owner_approved": EvidenceRights.OWNED,
        "licensed": EvidenceRights.LICENSED,
        "public_measurement": EvidenceRights.PUBLIC_PERMISSION,
        "restricted": EvidenceRights.RESTRICTED,
    }
    strategy_claims = tuple(
        ClaimEvidence(
            claim_id=claim.claim_id,
            text=claim.claim_text,
            evidence_uri=claim.source_uri,
            evidence_sha256=claim.source_sha256,
            rights=rights_by_status[claim.rights_status],
            rights_reference=claim.rights_reference,
            valid_from=claim.valid_from,
            valid_until=claim.valid_until,
            approved_by=(
                claim.approved_by or f"owner-attestation:{launch.owner}"
            ),
            specialist_approved_by=(
                claim.specialist_approved_by or launch.specialist_approved_by
            ),
            claim_type=claim.claim_type,
            assurance_status=(
                "verified"
                if claim.rights_status
                in {"owner_approved", "licensed", "public_measurement"}
                and bool(claim.approved_by)
                else "owner_attested"
            ),
            release_scope=claim.release_scope,
        )
        for claim in product_evidence_inputs
    )
    voice_principles = tuple(
        item.strip() for item in launch.brand_voice.split(",") if item.strip()
    )
    strategy_request = CampaignStrategyInput(
        org_id=launch.org_id,
        project_id=launch.project_id,
        campaign_id=launch.campaign_id,
        owner=launch.owner,
        industry=launch.industry,
        lifecycle=LifecycleStage(launch.lifecycle),
        budget=BudgetTier(launch.budget),
        industry_risk=IndustryRisk(launch.industry_risk),
        brand=BrandConstitution(
            brand_name=launch.product_name,
            purpose=launch.brand_purpose,
            customer_promise=launch.customer_promise,
            voice_principles=voice_principles,
            prohibited_tactics=(
                "spam",
                "fabricated testimonials",
                "automated publishing",
            ),
        ),
        audience=AudienceICP(
            audience_id=f"audience-{launch.campaign_id}",
            name=launch.audience_name,
            business_model=BusinessModel(launch.business_model),
            core_problem=launch.audience_problem,
            desired_outcome=launch.audience_outcome,
            buying_context=launch.buying_context,
        ),
        objective=launch.goal,
        offer=launch.offer,
        landing_url=launch.landing_url,
        claims=strategy_claims,
        company_scale=CompanyScale(launch.company_scale),
        brand_reach=DistributionStrength(launch.brand_reach),
        owned_audience_strength=DistributionStrength(
            launch.owned_audience_strength
        ),
        community_access=DistributionStrength(launch.community_access),
        partner_access=DistributionStrength(launch.partner_access),
        content_capacity=ContentCapacity(launch.content_capacity),
        sales_motion=SalesMotion(launch.sales_motion),
        product_category=launch.product_category,
        product_surface=ProductSurface(launch.product_surface),
        distribution_platform=launch.platform,
        audience_role=launch.audience_role,
        schedule_timezone=launch.schedule_timezone,
    )
    try:
        strategy = StrategyCompiler().compile(
            strategy_request,
            at=compiled_at,
            signal_platform_counts=authorized_platform_counts,
        )
    except StrategyContractError as error:
        raise ProductionRuntimeError(f"strategy safety gate failed: {error}") from error
    if launch.budget == BudgetTier.ZERO.value and (
        strategy.primary_channel.paid or strategy.secondary_channel.paid
    ):
        raise ProductionRuntimeError("zero-budget strategy selected a paid channel")
    for constraint in strategy.channel_constraints:
        if constraint.automated_publish_allowed:
            raise ProductionRuntimeError("strategy enabled automated publishing")
        if launch.budget == BudgetTier.ZERO.value and not {
            "paid_placement",
            "media_spend",
            "spam",
            "automated_publish",
        }.issubset(set(constraint.prohibited_actions)):
            raise ProductionRuntimeError("zero-budget strategy lost a mandatory prohibition")

    try:
        strategy_memory_decision = validate_strategy_memory_decision(
            compile_strategy_memory_decision(
                governed_learning,
                operating_context={
                    "industry": launch.industry,
                    "business_model": launch.business_model,
                    "lifecycle": launch.lifecycle,
                    "budget": launch.budget,
                    "industry_risk": launch.industry_risk,
                    "market": launch.market,
                },
                selected_channels=(
                    strategy.primary_channel.value,
                    strategy.secondary_channel.value,
                ),
            )
        )
        strategy_memory_application = validate_strategy_memory_application(
            compile_strategy_memory_application(
                strategy_memory_decision,
                governed_resolutions,
            )
        )
    except LearningMemoryError as error:
        raise ProductionRuntimeError(
            f"strategy memory arbitration failed: {error}"
        ) from error

    try:
        production_pack = ProductionPackCompiler().compile(
            strategy_request,
            strategy,
            signal_platform_counts=authorized_platform_counts,
            signal_intelligence=governed_signals,
        )
    except ProductionPackError as error:
        raise ProductionRuntimeError(
            f"GTM production pack safety gate failed: {error}"
        ) from error
    production_artifacts = production_pack.to_artifacts()
    promotion_governance = compile_promotion_governance(
        strategy_id=strategy.strategy_id,
        campaign_id=launch.campaign_id,
        candidate_revision=production_pack.content_sha256,
        stable_revision=production_pack.source_strategy_sha256,
        g0_contract_passed=(
            production_pack.editorial_quality_receipt["mechanical_screen_passed"]
            and production_pack.multimodal_direction_receipt[
                "first_frame_three_second_gate"
            ]["brief_gate_passed"]
            and product_evidence_register["all_claims_draft_generation_eligible"]
        ),
    )
    production_artifacts["promotion-governance.json"] = _pretty_json_bytes(
        promotion_governance
    )
    try:
        content_calendar = compile_content_calendar(
            strategy_request,
            strategy,
            production_pack.channel_portfolio,
            source_draft_ids={
                production_pack.primary_copy.channel: production_pack.primary_copy.draft_id,
                production_pack.secondary_copy.channel: production_pack.secondary_copy.draft_id,
            },
            compiled_at=compiled_at,
            schedule_timezone=launch.schedule_timezone,
        )
    except ContentCalendarError as error:
        raise ProductionRuntimeError(f"content calendar safety gate failed: {error}") from error
    content_calendar.pop("content_sha256", None)
    content_calendar["signal_guidance"] = signal_guidance
    content_calendar["strategy_memory_decision"] = {
        "decision_sha256": strategy_memory_decision["decision_sha256"],
        "status": strategy_memory_decision["status"],
        "eligible_memory_count": strategy_memory_decision[
            "eligible_memory_count"
        ],
        "conflict_count": strategy_memory_decision["conflict_count"],
        "recommended_directives": strategy_memory_decision[
            "recommended_directives"
        ],
        "human_application_required": True,
        "automatic_schedule_mutation_executed": False,
    }
    content_calendar["strategy_memory_application"] = strategy_memory_application
    content_calendar["content_sha256"] = hashlib.sha256(
        canonical_json(content_calendar).encode("utf-8")
    ).hexdigest()
    try:
        verify_content_calendar(content_calendar, compiled_at=compiled_at)
    except ContentCalendarError as error:
        raise ProductionRuntimeError(
            f"signal-guided content calendar safety gate failed: {error}"
        ) from error
    production_artifacts["content-calendar.json"] = _pretty_json_bytes(content_calendar)
    try:
        distribution_operations = compile_distribution_operations(
            strategy_request,
            strategy,
            channel_portfolio=production_pack.channel_portfolio,
            content_calendar=content_calendar,
        )
    except DistributionOperationsError as error:
        raise ProductionRuntimeError(
            f"distribution operations safety gate failed: {error}"
        ) from error
    production_artifacts["distribution-operations.json"] = _pretty_json_bytes(
        distribution_operations
    )
    try:
        revenue_journey = compile_revenue_journey_operations(
            strategy_request,
            strategy,
            compiled_at=compiled_at,
        )
    except RevenueJourneyError as error:
        raise ProductionRuntimeError(
            f"revenue journey safety gate failed: {error}"
        ) from error
    production_artifacts["revenue-journey-operations.json"] = _pretty_json_bytes(
        revenue_journey
    )
    production_artifacts["mechanism-abstraction-register.json"] = _pretty_json_bytes(
        compile_mechanism_abstraction_register(())
    )
    # The runtime-owned schedule carries approval and channel-constraint context.
    # The compiler's canonical schedule remains embedded in the full pack instead
    # of replacing that stronger outer contract.
    production_artifacts.pop("seven-day-schedule.json", None)

    strategy_payload = asdict(strategy)
    try:
        brief_intelligence = compile_brief_intelligence(
            {
                "campaign_id": launch.campaign_id,
                "product_name": launch.product_name,
                "industry": launch.industry,
                "market": launch.market,
                "business_model": launch.business_model,
                "lifecycle": launch.lifecycle,
                "budget": launch.budget,
                "brand_reach": launch.brand_reach,
                "company_scale": launch.company_scale,
                "sales_motion": launch.sales_motion,
                "product_category": launch.product_category,
                "audience_role": launch.audience_role,
                "buying_context": launch.buying_context,
                "goal": launch.goal,
            },
            product_evidence_register=product_evidence_register,
            growth_tension=asdict(strategy.growth_tensions[0]),
        )
    except BriefIntelligenceError as error:
        raise ProductionRuntimeError(f"brief intelligence failed: {error}") from error
    distribution_inputs = {
        "brand_reach": launch.brand_reach,
        "owned_audience_strength": launch.owned_audience_strength,
        "community_access": launch.community_access,
        "partner_access": launch.partner_access,
    }
    distribution_floor = distribution_operating_floor(
        *(DistributionStrength(value) for value in distribution_inputs.values())
    )
    adaptive_context = compile_adaptive_context(
        AdaptiveContext(
            business_model=BusinessModel(launch.business_model),
            lifecycle=LifecycleStage(launch.lifecycle),
            budget=BudgetTier(launch.budget),
            industry_risk=IndustryRisk(launch.industry_risk),
            company_scale=CompanyScale(launch.company_scale),
            distribution_strength=distribution_floor,
            content_capacity=ContentCapacity(launch.content_capacity),
            sales_motion=SalesMotion(launch.sales_motion),
        )
    )
    adaptive_capability_plan = {
        "schema": "ProofLaunchGTMAdaptiveCapabilityPlanV1",
        "compiled_context": adaptive_context,
        "distribution_inputs": distribution_inputs,
        "distribution_aggregation": "weakest_link_operating_floor",
        "hardware_and_provider_in_plan_identity": False,
        "human_release_required": True,
        "automatic_publish_send_spend_or_strategy_mutation": False,
    }
    adaptive_capability_plan["content_sha256"] = hashlib.sha256(
        canonical_json(adaptive_capability_plan).encode("utf-8")
    ).hexdigest()
    memory = ProjectMemory()
    draft_entry = MemoryEntry(
        entry_id=f"draft-{strategy.strategy_id}",
        key="campaign.gtm_strategy",
        value=strategy_payload,
        kind=MemoryKind.GENERATED_DRAFT,
        scope=MemoryScope(
            org_id=launch.org_id,
            project_id=launch.project_id,
            campaign_id=launch.campaign_id,
        ),
        source=MemorySource(
            uri=f"request://{launch.request_id}/specification_text",
            sha256=specification_sha256,
            owner=launch.owner,
            storage_allowed=False,
        ),
        owner=launch.owner,
        valid_from=compiled_at,
        valid_until=None,
        approval_status=ApprovalStatus.PENDING,
        approved_by=None,
        temporary_run_id=run_id,
    )
    memory.stage_run(draft_entry)
    selected_claim = next(
        claim for claim in strategy_claims if claim.claim_id == strategy.proof_claim_id
    )
    assurance = {
        "source_status": selected_claim.assurance_status,
        "owner_attested": selected_claim.assurance_status == "owner_attested",
        "requester_named_claim_approver": (
            next(
                item.approved_by
                for item in product_evidence_inputs
                if item.claim_id == selected_claim.claim_id
            )
        ),
        "independently_verified_by_prooflaunch": False,
        "evidence_sha256": selected_claim.evidence_sha256,
        "rights_basis": launch.rights_basis,
        "release_scope": selected_claim.release_scope,
        "product_evidence_register_sha256": product_evidence_register[
            "content_sha256"
        ],
        "all_claims_public_release_eligible": product_evidence_register[
            "all_claims_public_release_eligible"
        ],
    }
    memory_receipt = {
        "entry_id": draft_entry.entry_id,
        "kind": draft_entry.kind.value,
        "approval_status": draft_entry.approval_status.value,
        "temporary_run_id": run_id,
        "temporary_count": memory.temporary_count,
        "durable_count": memory.durable_count,
        "durable_promotion_status": "not_promoted",
        "source_storage_allowed": False,
        "events": [asdict(item) for item in memory.events],
    }
    plan = {
        "schema": "ProofLaunchGTMStrategyPlanV1",
        "run_id": run_id,
        "compiled_at": compiled_at,
        "plan_status": "draft_pending_human_release",
        "strategy_sha256": gtm_strategy_digest(strategy),
        "production_pack_id": production_pack.pack_id,
        "production_pack_sha256": production_pack.content_sha256,
        "production_artifact_status": {
            "copy": "draft_only",
            "video": "production_brief_only",
            "audio": "production_brief_only",
            "external_publish_executed": False,
        },
        "claim_assurance": assurance,
        "memory_receipt": memory_receipt,
        "approved_learning_context": {
            "context_sha256": governed_learning["context_sha256"],
            "memory_count": governed_learning["memory_count"],
            "latest_next_cycle_decision": governed_learning[
                "latest_next_cycle_decision"
            ],
            "automatic_strategy_mutation_executed": False,
            "human_review_required_before_application": True,
        },
        "strategy_memory_decision": strategy_memory_decision,
        "strategy_memory_application": strategy_memory_application,
        "signal_guidance": signal_guidance,
        "adaptive_capability_plan": adaptive_capability_plan,
        "strategy": strategy_payload,
        "external_publish_executed": False,
        "truth_boundary": (
            "This is a deterministic draft plan based on requester-provided, "
            "owner-attested evidence. ProofLaunch did not independently verify the "
            "claim, publish content, buy media, or establish causal lift or revenue."
        ),
    }
    schedule = {
        "schema": "ProofLaunchSevenDayScheduleV1",
        "run_id": run_id,
        "strategy_id": strategy.strategy_id,
        "status": "draft_pending_human_release",
        "automated_publish_allowed": False,
        "items": [asdict(item) for item in strategy.seven_day_content],
        "production_entries": [
            asdict(item) for item in production_pack.seven_day_schedule
        ],
        "channel_constraints": [
            asdict(item) for item in strategy.channel_constraints
        ],
        "strategy_memory_decision": {
            "decision_sha256": strategy_memory_decision["decision_sha256"],
            "status": strategy_memory_decision["status"],
            "conflict_count": strategy_memory_decision["conflict_count"],
            "recommended_directives": strategy_memory_decision[
                "recommended_directives"
            ],
            "human_application_required": True,
            "automatic_schedule_mutation_executed": False,
        },
        "strategy_memory_application": strategy_memory_application,
        "claim_assurance": assurance,
    }
    seo_geo = {
        "schema": "ProofLaunchSEOGEOQuestionPlanV1",
        "run_id": run_id,
        "strategy_id": strategy.strategy_id,
        "status": "draft_questions_only",
        "question_intents": list(strategy.seo_geo_question_intents),
        "answers_generated": False,
        "draft_answers_generated": True,
        "faq_drafts": [asdict(item) for item in production_pack.seo_geo_faqs],
        "keyword_stuffing_allowed": False,
        "claim_assurance": assurance,
    }
    experiment = {
        "schema": "ProofLaunchExperimentPreregistrationV1",
        "run_id": run_id,
        "strategy_id": strategy.strategy_id,
        "status": "draft_not_started",
        "attribution": asdict(strategy.attribution),
        "metrics": [asdict(item) for item in strategy.metrics],
        "stop_rules": list(strategy.stop_rules),
        "causal_outcome_claim_allowed": False,
        "observed_results": [],
        "approved_learning_context_sha256": governed_learning["context_sha256"],
        "approved_learning_memory_count": governed_learning["memory_count"],
        "next_cycle_directive": governed_learning["latest_next_cycle_decision"],
        "strategy_memory_decision_sha256": strategy_memory_decision[
            "decision_sha256"
        ],
        "strategy_memory_decision_status": strategy_memory_decision["status"],
        "strategy_memory_conflict_count": strategy_memory_decision[
            "conflict_count"
        ],
        "strategy_memory_recommended_directives": strategy_memory_decision[
            "recommended_directives"
        ],
        "strategy_memory_application_sha256": strategy_memory_application[
            "application_sha256"
        ],
        "strategy_memory_application_status": strategy_memory_application["status"],
        "strategy_memory_selected_directives": strategy_memory_application[
            "selected_directives"
        ],
        "human_review_required_before_memory_application": True,
        "signal_hypotheses": signal_hypotheses,
        "signal_source_snapshot_sha256": governed_signals.get(
            "source_snapshot_sha256"
        ),
        "human_review_required_before_signal_activation": True,
        "automatic_strategy_mutation_executed": False,
        "analytics_plan_sha256": hashlib.sha256(
            production_artifacts["analytics-plan.json"]
        ).hexdigest(),
        "external_activation_executed": False,
        "claim_assurance": assurance,
    }
    return {
        "brief-intelligence.json": _pretty_json_bytes(brief_intelligence),
        "product-evidence-register.json": _pretty_json_bytes(
            product_evidence_register
        ),
        "gtm-strategy.json": _pretty_json_bytes(plan),
        "seven-day-schedule.json": _pretty_json_bytes(schedule),
        "seo-geo-questions.json": _pretty_json_bytes(seo_geo),
        "experiment.json": _pretty_json_bytes(experiment),
        **production_artifacts,
        "graph-loop-harness.json": _pretty_json_bytes(
            production_graph_loop_harness(
                maximum_actions=launch.maximum_actions,
                maximum_cost_usd=launch.maximum_cost_usd,
            ).receipt()
        ),
        "creative-signal-intelligence.json": _pretty_json_bytes(
            governed_signals
        ),
        "approved-learning-context.json": _pretty_json_bytes(governed_learning),
        "approved-strategy-memory-resolutions.json": _pretty_json_bytes(
            governed_resolutions
        ),
    }


def _signal_intelligence_document(
    store: SubmissionStore,
    launch: ProductionLaunchRequest,
) -> dict[str, object]:
    digest = launch.creative_signal_snapshot_sha256
    if digest is None:
        return empty_signal_intelligence()
    record = store.artifacts.head(digest)
    if record.media_type != "application/json":
        raise ProductionRuntimeError(
            "creative signal snapshot must use application/json"
        )
    raw = store.artifacts.resolve_server_path(digest).read_bytes()
    try:
        result = parse_and_compile_signal_intelligence(raw)
    except SignalIntelligenceError as error:
        raise ProductionRuntimeError(
            f"creative signal safety gate failed: {error}"
        ) from error
    result["input_artifact_sha256"] = digest
    receipt_digest = launch.creative_signal_collection_receipt_sha256
    if receipt_digest is not None:
        receipt_record = store.artifacts.head(receipt_digest)
        if receipt_record.media_type != "application/json":
            raise ProductionRuntimeError(
                "creative signal collection receipt must use application/json"
            )
        receipt_raw = store.artifacts.resolve_server_path(receipt_digest).read_bytes()
        try:
            snapshot = json.loads(raw.decode("utf-8"))
            receipt = json.loads(receipt_raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ProductionRuntimeError(
                "creative signal collection receipt must be valid UTF-8 JSON"
            ) from error
        if not isinstance(snapshot, Mapping) or not isinstance(receipt, Mapping):
            raise ProductionRuntimeError(
                "creative signal snapshot and collection receipt must be objects"
            )
        unsigned_receipt = dict(receipt)
        supplied_receipt_sha256 = unsigned_receipt.pop("receipt_sha256", None)
        computed_receipt_sha256 = hashlib.sha256(
            canonical_json(unsigned_receipt).encode("utf-8")
        ).hexdigest()
        snapshot_content_sha256 = hashlib.sha256(
            canonical_json(snapshot).encode("utf-8")
        ).hexdigest()
        runs = receipt.get("runs")
        if (
            receipt.get("schema") != "ProofLaunchOpenSourceSocialCollectionRunV2"
            or receipt.get("status") != "completed"
            or receipt.get("derived_signal_filter_passed") is not True
            or receipt.get("training_admitted") is not False
            or receipt.get("strategy_mutation_executed") is not False
            or receipt.get("external_publish_executed") is not False
            or receipt.get("creative_signal_snapshot_sha256")
            != snapshot_content_sha256
            or receipt.get("captured_at") != snapshot.get("captured_at")
            or receipt.get("normalized_signal_count")
            != len(snapshot.get("signals", []))
            or not isinstance(runs, list)
            or not runs
            or any(
                not isinstance(item, Mapping)
                or item.get("status") != "completed"
                or item.get("captcha_or_auth_bypass_attempted") is not False
                or item.get("raw_content_training_admitted") is not False
                for item in runs
            )
            or supplied_receipt_sha256 != computed_receipt_sha256
            or not _SHA256.fullmatch(str(receipt.get("plan_sha256", "")))
        ):
            raise ProductionRuntimeError(
                "creative signal collection receipt failed provenance binding"
            )
        result.update(
            {
                "field_data_class": launch.creative_signal_data_class,
                "collection_receipt_artifact_sha256": receipt_digest,
                "collection_receipt_sha256": computed_receipt_sha256,
                "collection_plan_sha256": receipt["plan_sha256"],
                "collection_run_count": len(runs),
                "collection_status": "completed",
                "collection_training_admitted": False,
                "collection_external_publish_executed": False,
            }
        )
    return result


def _learning_context_document(
    store: SubmissionStore,
    launch: ProductionLaunchRequest,
) -> dict[str, object]:
    digest = launch.learning_context_sha256
    if digest is None:
        return compile_project_learning_context([])
    record = store.artifacts.head(digest)
    if record.media_type != "application/json":
        raise ProductionRuntimeError("learning context must use application/json")
    raw = store.artifacts.resolve_server_path(digest).read_bytes()
    try:
        value = json.loads(raw.decode("utf-8"))
        return validate_project_learning_context(value)
    except (UnicodeDecodeError, json.JSONDecodeError, LearningMemoryError) as error:
        raise ProductionRuntimeError(
            f"project learning context safety gate failed: {error}"
        ) from error


def _strategy_memory_resolution_context_document(
    store: SubmissionStore,
    launch: ProductionLaunchRequest,
) -> dict[str, object]:
    digest = launch.strategy_memory_resolution_context_sha256
    if digest is None:
        return compile_strategy_memory_resolution_context([])
    record = store.artifacts.head(digest)
    if record.media_type != "application/json":
        raise ProductionRuntimeError(
            "strategy memory resolution context must use application/json"
        )
    raw = store.artifacts.resolve_server_path(digest).read_bytes()
    try:
        value = json.loads(raw.decode("utf-8"))
        return validate_strategy_memory_resolution_context(value)
    except (UnicodeDecodeError, json.JSONDecodeError, LearningMemoryError) as error:
        raise ProductionRuntimeError(
            f"strategy memory resolution context safety gate failed: {error}"
        ) from error


def _effect_readiness_document(
    *,
    run_id: str,
    strategy_plan_sha256: str,
    observations: list[Mapping[str, object]] | None = None,
) -> bytes:
    observed = list(observations or [])
    production_observed = bool(observed)
    capability_status = {
        "strategy": "mechanical",
        "copy": "mechanical",
        "image": "mechanical",
        "video": "planned",
        "audio": "planned",
        "schedule": "mechanical",
        "seo_geo": "planned",
        "analytics": "production_observed" if production_observed else "planned",
    }
    blockers = [
        "no frozen named incumbent baseline set has been human-rated",
        "fewer than 30 blind candidate-baseline pairs exist per key scenario",
        "no candidate has a human win rate >=0.60 with Wilson lower 95 strictly >0.50",
        "the five core failure classes do not yet each have 50 adjudicated cases",
        "video and audio deliverables are planned but not generated or evaluated",
        "no model judge has >=100 human labels with both TPR and TNR >0.80",
    ]
    if not production_observed:
        blockers.insert(
            -1,
            "no production-observed outcome is bound to the preregistered experiment",
        )
    return _pretty_json_bytes(
        {
            "schema": "ProofLaunchEffectReadinessV1",
            "run_id": run_id,
            "strategy_plan_sha256": strategy_plan_sha256,
            "capability_status": capability_status,
            "evidence_levels_present": [
                "planned",
                "mechanical",
                *(["production_observed"] if production_observed else []),
            ],
            "promotion_passed": False,
            "four_a_effect_claim_eligible": False,
            "human_blind_evaluation_completed": False,
            "production_outcome_observation_completed": production_observed,
            "production_observation_count": len(observed),
            "production_observation_sha256": [
                item["observation_sha256"] for item in observed
            ],
            "blockers": blockers,
            "promotion_rule": (
                "Mechanical success is necessary but never sufficient for a 4A effect "
                "claim; promotion requires the frozen human-blind and production evidence "
                "gates in config/gtm_effect_gate_v1.json."
            ),
            "truth_boundary": (
                "This readiness receipt records planned and mechanical evidence only. "
                "It does not claim comparative creative preference, causal lift, revenue, "
                "Top-1 status, or 4A-level production effect."
            ),
        }
    )


@dataclass(frozen=True)
class ProcessResult:
    processed: bool
    run_id: str | None = None
    phase: str | None = None
    status: str | None = None


SupervisorFactory = Callable[[Callable[[str, CampaignState, dict[str, Any]], None]], Supervisor]


class AgencyRunWorker:
    """Single-owner worker that executes the real two-phase Supervisor.

    SQLite controls leases and public events. The Supervisor's own state file
    and evidence ledger remain the authoritative execution checkpoint.
    """

    def __init__(
        self,
        store: SubmissionStore,
        *,
        worker_id: str = "prooflaunch-worker-1",
        supervisor_factory: SupervisorFactory | None = None,
        lease_seconds: int = 300,
    ) -> None:
        if not _SAFE_ID.fullmatch(worker_id):
            raise ProductionRuntimeError("worker_id contains unsafe characters")
        self.store = store
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds
        self.supervisor_factory = supervisor_factory or self._default_supervisor
        self.runs_root = self.store.root / "runs"
        self.runs_root.mkdir(mode=0o700, exist_ok=True)
        self.runs_root.chmod(0o700)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @staticmethod
    def _default_supervisor(event_sink) -> Supervisor:
        return build_supervisor(
            audience=LexicalAudiencePulse(),
            seed=202607,
            event_sink=event_sink,
        )

    def start(self, *, poll_interval: float = 0.25) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self.serve,
            kwargs={"poll_interval": poll_interval},
            name=self.worker_id,
            daemon=True,
        )
        self._thread.start()

    def stop(self, *, timeout: float = 10.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            if self._thread.is_alive():
                raise TimeoutError("Agent worker did not stop within the bounded grace period")

    def serve(self, *, poll_interval: float = 0.25) -> None:
        while not self._stop.is_set():
            result = self.process_one()
            if not result.processed:
                self._stop.wait(poll_interval)

    def process_one(self) -> ProcessResult:
        job = self.store.claim_next_job(
            self.worker_id,
            lease_seconds=self.lease_seconds,
        )
        if job is None:
            return ProcessResult(False)
        try:
            if job.kind == "prepare":
                status, result = self._prepare(job)
            elif job.kind == "release":
                status, result = self._release(job)
            else:
                raise ProductionRuntimeError(f"unsupported job phase: {job.kind}")
            self.store.finish_job(
                job.job_id,
                worker_id=self.worker_id,
                lease_token=job.lease_token or "",
                succeeded=True,
                result=result,
            )
            return ProcessResult(True, job.run_id, job.kind, status)
        except Exception as error:
            try:
                self.store.finish_job(
                    job.job_id,
                    worker_id=self.worker_id,
                    lease_token=job.lease_token or "",
                    succeeded=False,
                    error=f"{type(error).__name__}: {error}",
                )
            finally:
                self._fail_run_if_active(job.run_id, error)
            return ProcessResult(True, job.run_id, job.kind, "failed")

    def _prepare(self, job: JobRecord) -> tuple[str, dict[str, Any]]:
        run = self.store.get_run(job.run_id)
        launch = ProductionLaunchRequest(**dict(run.request))
        strategy_documents = _strategy_documents(
            launch,
            run_id=job.run_id,
            compiled_at=run.created_at,
            signal_intelligence=_signal_intelligence_document(self.store, launch),
            learning_context=_learning_context_document(self.store, launch),
            strategy_memory_resolution_context=(
                _strategy_memory_resolution_context_document(self.store, launch)
            ),
        )
        if run.status == "awaiting_release":
            state, relative = self._find_prepared_state(job.run_id)
            self._ensure_strategy_artifacts(
                self._server_path(relative), strategy_documents
            )
            return run.status, self._state_result(state, relative)
        if run.status == "queued":
            run = self.store.transition_run(
                job.run_id,
                expected_status="queued",
                new_status="running",
                details={"phase": "prepare", "attempt": job.attempts},
            )
        if run.status != "running":
            raise ConflictError(f"prepare cannot run from {run.status}")

        product_image = self.store.artifacts.resolve_server_path(
            launch.product_image_sha256
        )
        campaign_request = CampaignRequest(
            product_name=launch.product_name,
            product_image=str(product_image),
            specification_text=launch.specification_text,
            market=launch.market,
            platform=launch.platform,
            goal=launch.goal,
            target_emotion=launch.target_emotion,
        )
        supervisor = self.supervisor_factory(self._event_sink(job.run_id))
        try:
            state, relative = self._find_prepared_state(
                job.run_id,
                request=campaign_request,
                supervisor=supervisor,
            )
            self._ensure_strategy_artifacts(
                self._server_path(relative), strategy_documents
            )
        except KeyError:
            relative = f"runs/{job.run_id}/prepare-{job.attempts:03d}"
            output = self._server_path(relative)
            output.mkdir(parents=True, mode=0o700, exist_ok=False)
            output.chmod(0o700)
            self._ensure_strategy_artifacts(output, strategy_documents)
            state = supervisor.prepare(
                campaign_request,
                str(output),
                run_id=job.run_id,
            )

        if state.stage is Stage.BLOCKED:
            self.store.transition_run(
                job.run_id,
                expected_status="running",
                new_status="blocked",
                details={"phase": "prepare", "reason": state.blocked_reason or "blocked"},
            )
            return "blocked", self._state_result(state, relative)
        if state.stage is not Stage.AWAITING_RELEASE or not state.prepared_preview_digest:
            raise ProductionRuntimeError("Supervisor did not stop at awaiting_release")
        self.store.append_event(
            job.run_id,
            "prepare_completed",
            {
                "preview_digest": state.prepared_preview_digest,
                "repair_count": state.repair_count,
                "attempt": job.attempts,
                "strategy_plan_sha256": hashlib.sha256(
                    strategy_documents["gtm-strategy.json"]
                ).hexdigest(),
            },
        )
        self.store.transition_run(
            job.run_id,
            expected_status="running",
            new_status="awaiting_release",
            details={
                "phase": "prepare",
                "preview_digest": state.prepared_preview_digest,
                "output_relative": relative,
            },
        )
        return "awaiting_release", self._state_result(state, relative)

    @staticmethod
    def _ensure_strategy_artifacts(
        output: Path,
        documents: Mapping[str, bytes],
    ) -> None:
        if set(documents) != set(_STRATEGY_ARTIFACT_NAMES):
            raise ProductionRuntimeError("strategy artifact set is incomplete")
        for name in _STRATEGY_ARTIFACT_NAMES:
            candidate = output / name
            if candidate.is_symlink():
                raise ProductionRuntimeError("strategy artifact cannot be a symlink")
            expected = documents[name]
            if candidate.exists():
                if not candidate.is_file() or candidate.read_bytes() != expected:
                    raise ProductionRuntimeError(
                        f"strategy artifact integrity failed: {name}"
                    )
                continue
            atomic_write_bytes(candidate, expected)
            candidate.chmod(0o600)

    def _release(self, job: JobRecord) -> tuple[str, dict[str, Any]]:
        run = self.store.get_run(job.run_id)
        if run.status in _TERMINAL_STATUSES:
            state, relative = self._find_latest_state(job.run_id)
            return run.status, self._state_result(state, relative)
        if run.status != "running":
            raise ConflictError(f"release cannot run from {run.status}")
        approval_raw = job.payload.get("approval")
        output_relative = job.payload.get("output_relative")
        if not isinstance(approval_raw, Mapping) or not isinstance(output_relative, str):
            raise ProductionRuntimeError("release job payload is incomplete")
        approval = ReleaseApproval.from_serializable(dict(approval_raw))
        if approval.kind is not ReleaseApprovalKind.HUMAN:
            raise ProductionRuntimeError("production release requires a human approval kind")
        output = self._server_path(output_relative)
        persisted = self._load_state(output)
        if persisted.stage is Stage.DELIVER:
            if (
                persisted.release_approval != approval
                or not persisted.exports
                or not all(Path(item).is_file() for item in persisted.exports)
                or not EvidenceLedger.verify(output / "evidence-ledger.jsonl")
            ):
                raise ProductionRuntimeError(
                    "delivered Supervisor checkpoint failed release reconciliation"
                )
            state = persisted
        elif persisted.stage is Stage.BLOCKED:
            if persisted.release_approval != approval:
                raise ProductionRuntimeError(
                    "blocked Supervisor checkpoint belongs to another decision"
                )
            state = persisted
        else:
            supervisor = self.supervisor_factory(self._event_sink(job.run_id))
            state = supervisor.release(output, approval)
        if state.stage is Stage.DELIVER:
            target = "bundle_ready"
        elif approval.decision is ReleaseDecision.REJECT:
            target = "rejected"
        elif state.stage is Stage.BLOCKED:
            target = "blocked"
        else:
            raise ProductionRuntimeError("release ended outside a permitted terminal state")
        self.store.transition_run(
            job.run_id,
            expected_status="running",
            new_status=target,
            details={
                "phase": "release",
                "approval_id": approval.approval_id,
                "output_relative": output_relative,
            },
        )
        return target, self._state_result(state, output_relative)

    def _event_sink(self, run_id: str):
        def sink(kind: str, state: CampaignState, payload: dict[str, Any]) -> None:
            public = {
                key: value
                for key, value in payload.items()
                if key in _PUBLIC_EVENT_FIELDS
                and isinstance(value, (str, int, float, bool, type(None)))
            }
            public["stage"] = state.stage.value
            self.store.append_event(run_id, f"supervisor_{kind}", public)

        return sink

    def _find_prepared_state(
        self,
        run_id: str,
        *,
        request: CampaignRequest | None = None,
        supervisor: Supervisor | None = None,
    ) -> tuple[CampaignState, str]:
        run_root = self._server_path(f"runs/{run_id}")
        if not run_root.is_dir():
            raise KeyError("no prior prepare attempt")
        for candidate in sorted(run_root.glob("prepare-*"), reverse=True):
            if candidate.is_symlink() or not candidate.is_dir():
                continue
            relative = candidate.relative_to(self.store.root).as_posix()
            if request is not None and supervisor is not None:
                try:
                    state = supervisor.prepare(request, str(candidate), run_id=run_id)
                except (FileExistsError, WorkflowBlocked, ValueError):
                    continue
            else:
                state = self._load_state(candidate)
                if not EvidenceLedger.verify(candidate / "evidence-ledger.jsonl"):
                    continue
            if state.run_id == run_id and state.stage is Stage.AWAITING_RELEASE:
                return state, relative
        raise KeyError("no valid prepared attempt")

    def _find_latest_state(self, run_id: str) -> tuple[CampaignState, str]:
        run_root = self._server_path(f"runs/{run_id}")
        for candidate in sorted(run_root.glob("prepare-*"), reverse=True):
            if candidate.is_symlink() or not candidate.is_dir():
                continue
            try:
                state = self._load_state(candidate)
            except ProductionRuntimeError:
                continue
            if state.run_id == run_id and EvidenceLedger.verify(
                candidate / "evidence-ledger.jsonl"
            ):
                return state, candidate.relative_to(self.store.root).as_posix()
        raise ProductionRuntimeError("run has no verifiable campaign state")

    @staticmethod
    def _load_state(root: Path) -> CampaignState:
        try:
            raw = json.loads((root / "campaign-state.json").read_text(encoding="utf-8"))
            return CampaignState.from_serializable(raw)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
            raise ProductionRuntimeError("campaign state is unreadable") from error

    def _server_path(self, relative: str) -> Path:
        if not isinstance(relative, str) or not relative or "\\" in relative:
            raise ProductionRuntimeError("server-relative path is invalid")
        raw = Path(relative)
        if raw.is_absolute() or ".." in raw.parts or "." in raw.parts:
            raise ProductionRuntimeError("server-relative path escaped its root")
        candidate = self.store.root.joinpath(*raw.parts)
        try:
            candidate.resolve(strict=False).relative_to(self.store.root)
        except ValueError as error:
            raise ProductionRuntimeError("server-relative path escaped its root") from error
        current = self.store.root
        for part in raw.parts:
            current = current / part
            if current.exists() and current.is_symlink():
                raise ProductionRuntimeError("server-relative path traverses a symlink")
        return candidate

    @staticmethod
    def _state_result(state: CampaignState, relative: str) -> dict[str, Any]:
        return {
            "stage": state.stage.value,
            "output_relative": relative,
            "preview_digest": state.prepared_preview_digest,
            "repair_count": state.repair_count,
            "export_count": len(state.exports),
        }

    def _fail_run_if_active(self, run_id: str, error: Exception) -> None:
        try:
            run = self.store.get_run(run_id)
            if run.status not in _TERMINAL_STATUSES:
                self.store.transition_run(
                    run_id,
                    expected_status=run.status,
                    new_status="failed",
                    details={"error_type": type(error).__name__, "phase": "worker"},
                )
        except (KeyError, ConflictError):
            return


class ProductionAgencyService:
    """Application service used by HTTP without exposing server file paths."""

    def __init__(
        self,
        store: SubmissionStore,
        *,
        worker: AgencyRunWorker | None = None,
    ) -> None:
        self.store = store
        self.worker = worker or AgencyRunWorker(store)

    def create_run(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        launch = ProductionLaunchRequest.from_payload(payload)
        artifact = self.store.artifacts.head(launch.product_image_sha256)
        if artifact.media_type != "image/png":
            raise ProductionRuntimeError("the production slice currently accepts PNG only")
        if launch.creative_signal_snapshot_sha256 is not None:
            _signal_intelligence_document(self.store, launch)
        learning_context = self.project_learning_context(
            launch.org_id,
            launch.project_id,
        )
        learning_context_bytes = _pretty_json_bytes(learning_context)
        learning_context_sha256 = hashlib.sha256(learning_context_bytes).hexdigest()
        self.store.artifacts.put(
            io.BytesIO(learning_context_bytes),
            expected_sha256=learning_context_sha256,
            media_type="application/json",
        )
        resolution_context = self.project_strategy_memory_resolution_context(
            launch.org_id,
            launch.project_id,
        )
        resolution_context_bytes = _pretty_json_bytes(resolution_context)
        resolution_context_sha256 = hashlib.sha256(
            resolution_context_bytes
        ).hexdigest()
        self.store.artifacts.put(
            io.BytesIO(resolution_context_bytes),
            expected_sha256=resolution_context_sha256,
            media_type="application/json",
        )
        launch = replace(
            launch,
            learning_context_sha256=learning_context_sha256,
            strategy_memory_resolution_context_sha256=(
                resolution_context_sha256
            ),
        )
        run = self.store.create_run(launch.run_id, asdict(launch), status="queued")
        self.store.link_artifact(
            run.run_id,
            launch.product_image_sha256,
            role="product_image",
        )
        if launch.creative_signal_snapshot_sha256 is not None:
            self.store.link_artifact(
                run.run_id,
                launch.creative_signal_snapshot_sha256,
                role="creative_signal_snapshot",
            )
        if launch.creative_signal_collection_receipt_sha256 is not None:
            self.store.link_artifact(
                run.run_id,
                launch.creative_signal_collection_receipt_sha256,
                role="creative_signal_collection_receipt",
            )
        self.store.link_artifact(
            run.run_id,
            learning_context_sha256,
            role="approved_learning_context",
        )
        self.store.link_artifact(
            run.run_id,
            resolution_context_sha256,
            role="approved_strategy_memory_resolutions",
        )
        self.store.enqueue_job(
            f"prepare:{run.run_id}",
            run.run_id,
            kind="prepare",
            payload={},
        )
        return self.snapshot(run.run_id)

    def project_learning_context(
        self,
        org_id: str,
        project_id: str,
    ) -> dict[str, object]:
        """Compile native memory plus explicitly approved portable imports.

        Pending or rejected capsules are never exposed to a campaign run. The
        native-only path remains byte-for-byte compatible with the original
        learning context compiler.
        """

        native = compile_project_learning_context(
            [
                asdict(item)
                for item in self.store.list_learning_memories(org_id, project_id)
            ]
        )
        approved = self.store.list_memory_capsule_imports(
            org_id,
            project_id,
            status="approved",
        )
        if not approved:
            return native
        try:
            return merge_project_learning_contexts(
                [native]
                + [dict(record.capsule["context"]) for record in approved]
            )
        except (KeyError, TypeError, MemoryCapsuleError) as error:
            raise ProductionRuntimeError(
                f"approved portable learning context is invalid: {error}"
            ) from error

    def project_strategy_memory_resolution_context(
        self,
        org_id: str,
        project_id: str,
    ) -> dict[str, object]:
        try:
            return compile_strategy_memory_resolution_context(
                [
                    dict(item.payload)
                    for item in self.store.list_strategy_memory_resolutions(
                        org_id,
                        project_id,
                    )
                ]
            )
        except LearningMemoryError as error:
            raise ProductionRuntimeError(
                f"approved strategy memory resolution context is invalid: {error}"
            ) from error

    def resolve_strategy_memory_conflict(
        self,
        run_id: str,
        *,
        authenticated_resolver: str,
        base_decision_sha256: str,
        channel: str,
        winner_memory_id: str,
        reason: str,
    ) -> dict[str, object]:
        """Resolve a frozen conflict for future runs without editing this run."""

        if not all(
            isinstance(item, str) and item.strip()
            for item in (
                authenticated_resolver,
                base_decision_sha256,
                channel,
                winner_memory_id,
                reason,
            )
        ):
            raise ProductionRuntimeError(
                "strategy memory resolution fields must be non-empty strings"
            )
        normalized_channel = re.sub(r"\s+", " ", channel.strip()).casefold()
        normalized_reason = re.sub(r"\s+", " ", reason.strip())
        normalized_resolver = authenticated_resolver.strip()
        run = self.store.get_run(run_id)
        preview = self.preview(run_id)
        strategy = preview.get("gtm_strategy")
        decision = (
            strategy.get("strategy_memory_decision")
            if isinstance(strategy, Mapping)
            else None
        )
        if not isinstance(decision, Mapping):
            raise ConflictError("run has no frozen strategy memory decision")
        try:
            governed = validate_strategy_memory_decision(decision)
        except LearningMemoryError as error:
            raise ProductionRuntimeError(str(error)) from error
        if governed["decision_sha256"] != base_decision_sha256:
            raise ConflictError("resolution is not bound to this frozen decision")
        if governed["status"] != "blocked_conflicting_human_memories":
            raise ConflictError("run has no unresolved strategy memory conflict")

        for existing in self.store.list_strategy_memory_resolutions(
            str(run.request["org_id"]),
            str(run.request["project_id"]),
        ):
            if (
                existing.base_decision_sha256 == base_decision_sha256
                and existing.channel == normalized_channel
            ):
                if (
                    existing.winner_memory_id == winner_memory_id
                    and existing.resolved_by == normalized_resolver
                    and existing.reason == normalized_reason
                ):
                    return {
                        **asdict(existing),
                        "applies_to_source_run": False,
                        "available_to_future_runs": True,
                    }
                raise ConflictError(
                    "a different immutable resolution already exists for this conflict"
                )

        resolved_at = datetime.now(timezone.utc)
        resolved_at_text = (
            resolved_at.isoformat(timespec="microseconds").replace("+00:00", "Z")
        )
        try:
            payload = strategy_memory_resolution_payload(
                governed,
                source_run_id=run_id,
                channel=normalized_channel,
                winner_memory_id=winner_memory_id,
                resolved_by=normalized_resolver,
                reason=normalized_reason,
                resolved_at=resolved_at_text,
            )
        except LearningMemoryError as error:
            raise ProductionRuntimeError(str(error)) from error
        record = self.store.record_strategy_memory_resolution(
            resolution_id=f"strategy-resolution-{payload['resolution_sha256'][:24]}",
            org_id=str(run.request["org_id"]),
            project_id=str(run.request["project_id"]),
            source_run_id=run_id,
            base_decision_sha256=str(payload["base_decision_sha256"]),
            channel=str(payload["channel"]),
            winner_memory_id=str(payload["winner_memory_id"]),
            resolved_by=str(payload["resolved_by"]),
            reason=str(payload["reason"]),
            payload=payload,
            resolved_at=resolved_at,
        )
        return {
            **asdict(record),
            "applies_to_source_run": False,
            "available_to_future_runs": True,
        }

    def strategy_memory_resolutions(
        self,
        org_id: str,
        project_id: str,
    ) -> dict[str, object]:
        context = self.project_strategy_memory_resolution_context(
            org_id,
            project_id,
        )
        return {
            **context,
            "org_id": org_id,
            "project_id": project_id,
            "future_runs_only": True,
        }

    def export_memory_capsule(
        self,
        *,
        org_id: str,
        project_id: str,
        signing_secret: bytes,
        ttl_seconds: int = 86_400,
    ) -> dict[str, object]:
        try:
            return issue_memory_capsule(
                self.project_learning_context(org_id, project_id),
                tenant_id=org_id,
                project_id=project_id,
                signing_secret=signing_secret,
                ttl_seconds=ttl_seconds,
            )
        except MemoryCapsuleError as error:
            raise ProductionRuntimeError(str(error)) from error

    def import_memory_capsule(
        self,
        capsule: object,
        *,
        authenticated_tenant: str,
        signing_secret: bytes,
        expected_project_id: str | None = None,
    ) -> dict[str, object]:
        try:
            verified = verify_memory_capsule(
                capsule,
                signing_secret=signing_secret,
                expected_tenant_id=authenticated_tenant,
                expected_project_id=expected_project_id,
            )
        except MemoryCapsuleError as error:
            raise ProductionRuntimeError(str(error)) from error
        record = self.store.stage_memory_capsule_import(
            verified,
            org_id=authenticated_tenant,
            project_id=str(verified["project_id"]),
        )
        return asdict(record)

    def review_memory_capsule(
        self,
        capsule_id: str,
        *,
        authenticated_tenant: str,
        authenticated_reviewer: str,
        decision: str,
        reason: str,
    ) -> dict[str, object]:
        try:
            record = self.store.review_memory_capsule_import(
                capsule_id,
                org_id=authenticated_tenant,
                decision=decision,
                reviewed_by=authenticated_reviewer,
                reason=reason,
            )
        except ValueError as error:
            raise ProductionRuntimeError(str(error)) from error
        return asdict(record)

    def memory_capsule_imports(
        self,
        org_id: str,
        project_id: str,
    ) -> dict[str, object]:
        records = self.store.list_memory_capsule_imports(org_id, project_id)
        return {
            "schema": "ProofLaunchMemoryCapsuleImportCollectionV1",
            "org_id": org_id,
            "project_id": project_id,
            "import_count": len(records),
            "imports": [asdict(record) for record in records],
            "pending_imports_applied": False,
            "human_review_required": True,
            "automatic_strategy_mutation_executed": False,
            "automatic_external_action_executed": False,
        }

    @staticmethod
    def _verified_execution_receipt(
        store: SubmissionStore,
        sha256: str,
        *,
        campaign_id: str,
        capability_id: str,
        artifact_sha256: str,
    ) -> dict[str, Any]:
        record = store.artifacts.head(sha256)
        if record.media_type != "application/json" or record.byte_length > 1_000_000:
            raise ProductionRuntimeError(
                "execution receipt must be a bounded application/json artifact"
            )
        path = store.artifacts.resolve_server_path(sha256)
        try:
            receipt = json.loads(path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ProductionRuntimeError("execution receipt is not valid JSON") from error
        if not isinstance(receipt, Mapping):
            raise ProductionRuntimeError("execution receipt must be a JSON object")
        required_matches = {
            "schema": "ProofLaunchMultimodalExecutionReceiptV1",
            "campaign_id": campaign_id,
            "capability_id": capability_id,
            "artifact_sha256": artifact_sha256,
        }
        if any(receipt.get(key) != value for key, value in required_matches.items()):
            raise ProductionRuntimeError(
                "execution receipt identity disagrees with the deliverable"
            )
        for field in ("model_id", "model_revision", "accelerator", "source_kind"):
            if not isinstance(receipt.get(field), str) or not receipt[field].strip():
                raise ProductionRuntimeError(
                    f"execution receipt {field} must be a non-empty string"
                )
        if receipt["source_kind"] not in {
            "local_model_inference",
            "amd_radeon_local_inference",
            "provider_api_generation",
            "provider_gpu_inference",
        }:
            raise ProductionRuntimeError("execution receipt source_kind is unsupported")
        executed_at = receipt.get("executed_at")
        if not isinstance(executed_at, str):
            raise ProductionRuntimeError("execution receipt executed_at is required")
        try:
            parsed = datetime.fromisoformat(executed_at.replace("Z", "+00:00"))
        except ValueError as error:
            raise ProductionRuntimeError(
                "execution receipt executed_at must be ISO-8601"
            ) from error
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ProductionRuntimeError(
                "execution receipt executed_at must include a timezone"
            )
        if type(receipt.get("external_api_calls")) is not int or receipt[
            "external_api_calls"
        ] < 0:
            raise ProductionRuntimeError(
                "execution receipt external_api_calls must be a non-negative integer"
            )
        for field in (
            "local_model_inference_observed",
            "radeon_execution_observed",
            "production_effect_proven",
            "four_a_quality_proven",
        ):
            if type(receipt.get(field)) is not bool:
                raise ProductionRuntimeError(
                    f"execution receipt {field} must be boolean"
                )
        if receipt["production_effect_proven"] or receipt["four_a_quality_proven"]:
            raise ProductionRuntimeError(
                "execution receipts cannot self-attest effect or 4A quality"
            )
        return dict(receipt)

    @staticmethod
    def _validate_multimodal_signature(path: Path, capability_id: str) -> str:
        with path.open("rb") as handle:
            header = handle.read(32)
        if capability_id == "video_generation":
            if len(header) < 12 or header[4:8] != b"ftyp":
                raise ProductionRuntimeError(
                    "video deliverable signature is not an MP4 family file"
                )
            return "video/mp4"
        if capability_id == "audio_generation":
            if not (header.startswith(b"RIFF") and header[8:12] == b"WAVE"):
                raise ProductionRuntimeError(
                    "audio deliverable signature is not a RIFF/WAVE file"
                )
            return "audio/wav"
        raise ProductionRuntimeError("unsupported multimodal capability")

    def register_multimodal_deliverable(
        self,
        run_id: str,
        payload: Mapping[str, Any],
        *,
        authenticated_tenant: str,
        authenticated_operator: str,
    ) -> dict[str, Any]:
        run = self.store.require_run_tenant(run_id, authenticated_tenant)
        approval = self.store.get_approval(run_id)
        if run.status != "bundle_ready" or approval is None or approval.decision != "approve":
            raise ConflictError(
                "multimodal registration requires a delivered, human-approved run"
            )
        string_fields = (
            "registration_id",
            "capability_id",
            "artifact_sha256",
            "execution_receipt_sha256",
            "campaign_id",
            "rights_basis",
            "rights_locator",
        )
        if any(not isinstance(payload.get(field), str) for field in string_fields):
            raise ProductionRuntimeError(
                "multimodal registration identity and provenance fields must be strings"
            )
        campaign_id = str(run.request.get("campaign_id"))
        if payload["campaign_id"] != campaign_id:
            raise ProductionRuntimeError(
                "multimodal registration campaign_id disagrees with the run"
            )
        capability_id = payload["capability_id"]
        artifact_sha256 = payload["artifact_sha256"]
        execution_receipt_sha256 = payload["execution_receipt_sha256"]
        if payload.get("rights_confirmed") is not True:
            raise ProductionRuntimeError(
                "multimodal registration requires explicit rights confirmation"
            )
        if payload["rights_basis"] not in {
            "owned",
            "licensed",
            "original_generated_from_owned_inputs",
        }:
            raise ProductionRuntimeError("multimodal rights_basis is unsupported")
        artifact = self.store.require_tenant_artifact(
            authenticated_tenant, artifact_sha256
        )
        receipt_artifact = self.store.require_tenant_artifact(
            authenticated_tenant, execution_receipt_sha256
        )
        expected_media_type = self._validate_multimodal_signature(
            self.store.artifacts.resolve_server_path(artifact.sha256),
            capability_id,
        )
        if artifact.media_type != expected_media_type:
            raise ProductionRuntimeError(
                "multimodal artifact media type disagrees with its signature"
            )
        if receipt_artifact.media_type != "application/json":
            raise ProductionRuntimeError("execution receipt media type is invalid")
        receipt = self._verified_execution_receipt(
            self.store,
            execution_receipt_sha256,
            campaign_id=campaign_id,
            capability_id=capability_id,
            artifact_sha256=artifact_sha256,
        )
        record = self.store.record_multimodal_deliverable(
            registration_id=payload["registration_id"],
            run_id=run_id,
            capability_id=capability_id,
            artifact_sha256=artifact_sha256,
            execution_receipt_sha256=execution_receipt_sha256,
            media_type=expected_media_type,
            campaign_id=campaign_id,
            model_id=receipt["model_id"],
            model_revision=receipt["model_revision"],
            accelerator=receipt["accelerator"],
            rights_basis=payload["rights_basis"],
            rights_locator=payload["rights_locator"],
            registered_by=authenticated_operator,
            payload={
                "schema": "ProofLaunchRunBoundMultimodalDeliverableV1",
                "rights_confirmed": True,
                "source_kind": receipt["source_kind"],
                "local_model_inference_observed": receipt[
                    "local_model_inference_observed"
                ],
                "radeon_execution_observed": receipt["radeon_execution_observed"],
                "external_api_calls": receipt["external_api_calls"],
                "generated_deliverable_observed": True,
                "named_human_quality_observed": False,
                "external_publish_executed": False,
                "production_effect_proven": False,
                "four_a_quality_proven": False,
            },
        )
        result = asdict(record)
        result["schema"] = "ProofLaunchRunBoundMultimodalDeliverableV1"
        result["generated_deliverable_observed"] = True
        result["named_human_quality_observed"] = False
        result["external_publish_executed"] = False
        result["production_effect_proven"] = False
        result["four_a_quality_proven"] = False
        return result

    def review_multimodal_deliverable(
        self,
        run_id: str,
        registration_id: str,
        payload: Mapping[str, Any],
        *,
        authenticated_tenant: str,
        authenticated_reviewer: str,
    ) -> dict[str, Any]:
        self.store.require_run_tenant(run_id, authenticated_tenant)
        registrations = {
            item.registration_id: item
            for item in self.store.list_multimodal_deliverables(run_id)
        }
        if registration_id not in registrations:
            raise KeyError("unknown multimodal deliverable")
        review_id = payload.get("review_id")
        decision = payload.get("decision")
        reason = payload.get("reason")
        rubric_id = payload.get("rubric_id")
        criteria = payload.get("criteria")
        if not all(isinstance(value, str) for value in (
            review_id, decision, reason, rubric_id
        )) or not isinstance(criteria, Mapping):
            raise ProductionRuntimeError(
                "review_id, decision, reason, rubric_id and criteria are required"
            )
        required_criteria = (
            "playback_completed",
            "brief_alignment_passed",
            "brand_safety_passed",
            "rights_rechecked",
        )
        if any(type(criteria.get(field)) is not bool for field in required_criteria):
            raise ProductionRuntimeError("multimodal review criteria must be boolean")
        if decision == "pass" and not all(criteria[field] for field in required_criteria):
            raise ProductionRuntimeError(
                "a passing multimodal review requires every frozen criterion to pass"
            )
        record = self.store.record_multimodal_deliverable_review(
            review_id=review_id,
            registration_id=registration_id,
            run_id=run_id,
            decision=decision,
            reviewer=authenticated_reviewer,
            reason=reason,
            payload={
                "schema": "ProofLaunchMultimodalDeliverableReviewV1",
                "rubric_id": rubric_id,
                "criteria": dict(criteria),
                "reviewer_is_named": True,
                "external_publish_executed": False,
                "production_effect_proven": False,
                "four_a_preference_proven": False,
            },
        )
        result = asdict(record)
        result["schema"] = "ProofLaunchMultimodalDeliverableReviewV1"
        result["named_human_quality_observed"] = record.decision == "pass"
        result["external_publish_executed"] = False
        result["production_effect_proven"] = False
        result["four_a_preference_proven"] = False
        return result

    @staticmethod
    def _verified_capability_execution_receipt(
        store: SubmissionStore,
        sha256: str,
        *,
        campaign_id: str,
        capability_id: str,
        artifact_role: str,
        artifact_sha256: str,
    ) -> dict[str, Any]:
        record = store.artifacts.head(sha256)
        if record.media_type != "application/json" or record.byte_length > 1_000_000:
            raise ProductionRuntimeError(
                "capability execution receipt must be bounded application/json"
            )
        try:
            receipt = json.loads(
                store.artifacts.resolve_server_path(sha256).read_text(encoding="utf-8")
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ProductionRuntimeError(
                "capability execution receipt is not valid JSON"
            ) from error
        required_matches = {
            "schema": "ProofLaunchCapabilityExecutionReceiptV1",
            "campaign_id": campaign_id,
            "capability_id": capability_id,
            "artifact_role": artifact_role,
            "artifact_sha256": artifact_sha256,
        }
        if not isinstance(receipt, Mapping) or any(
            receipt.get(key) != value for key, value in required_matches.items()
        ):
            raise ProductionRuntimeError(
                "capability execution receipt identity disagrees with the deliverable"
            )
        for field in ("model_id", "model_revision", "accelerator", "source_kind"):
            if not isinstance(receipt.get(field), str) or not receipt[field].strip():
                raise ProductionRuntimeError(
                    f"capability execution receipt {field} must be a non-empty string"
                )
        if receipt["source_kind"] not in {
            "deterministic_compiler",
            "local_model_inference",
            "provider_api_generation",
            "operator_authored",
        }:
            raise ProductionRuntimeError(
                "capability execution receipt source_kind is unsupported"
            )
        executed_at = receipt.get("executed_at")
        if not isinstance(executed_at, str):
            raise ProductionRuntimeError(
                "capability execution receipt executed_at is required"
            )
        try:
            parsed = datetime.fromisoformat(executed_at.replace("Z", "+00:00"))
        except ValueError as error:
            raise ProductionRuntimeError(
                "capability execution receipt executed_at must be ISO-8601"
            ) from error
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ProductionRuntimeError(
                "capability execution receipt executed_at must include a timezone"
            )
        if type(receipt.get("external_api_calls")) is not int or receipt[
            "external_api_calls"
        ] < 0:
            raise ProductionRuntimeError(
                "capability execution receipt external_api_calls must be non-negative"
            )
        for field in (
            "local_model_inference_observed",
            "radeon_execution_observed",
            "production_effect_proven",
            "four_a_quality_proven",
        ):
            if type(receipt.get(field)) is not bool:
                raise ProductionRuntimeError(
                    f"capability execution receipt {field} must be boolean"
                )
        if receipt["production_effect_proven"] or receipt["four_a_quality_proven"]:
            raise ProductionRuntimeError(
                "capability execution receipts cannot self-attest effect or 4A quality"
            )
        return dict(receipt)

    def register_capability_deliverable(
        self,
        run_id: str,
        payload: Mapping[str, Any],
        *,
        authenticated_tenant: str,
        authenticated_operator: str,
    ) -> dict[str, Any]:
        run = self.store.require_run_tenant(run_id, authenticated_tenant)
        approval = self.store.get_approval(run_id)
        if run.status != "bundle_ready" or approval is None or approval.decision != "approve":
            raise ConflictError(
                "capability registration requires a delivered, human-approved run"
            )
        string_fields = (
            "registration_id", "capability_id", "artifact_role", "artifact_sha256",
            "execution_receipt_sha256", "campaign_id", "rights_basis",
            "rights_locator",
        )
        if any(not isinstance(payload.get(field), str) for field in string_fields):
            raise ProductionRuntimeError(
                "capability registration identity and provenance fields must be strings"
            )
        campaign_id = str(run.request.get("campaign_id"))
        capability_id = payload["capability_id"]
        artifact_role = payload["artifact_role"]
        if payload["campaign_id"] != campaign_id:
            raise ProductionRuntimeError(
                "capability registration campaign_id disagrees with the run"
            )
        if _CAPABILITY_DELIVERABLE_ARTIFACTS.get(capability_id) != artifact_role:
            raise ProductionRuntimeError(
                "capability registration artifact_role is not allowed for the capability"
            )
        if payload.get("rights_confirmed") is not True:
            raise ProductionRuntimeError(
                "capability registration requires explicit rights confirmation"
            )
        if payload["rights_basis"] not in {
            "owned", "licensed", "original_generated_from_owned_inputs",
        }:
            raise ProductionRuntimeError("capability rights_basis is unsupported")
        artifact = self.store.require_tenant_artifact(
            authenticated_tenant, payload["artifact_sha256"]
        )
        receipt_artifact = self.store.require_tenant_artifact(
            authenticated_tenant, payload["execution_receipt_sha256"]
        )
        if artifact.media_type != "application/json" or artifact.byte_length > 5_000_000:
            raise ProductionRuntimeError(
                "capability deliverable must be bounded application/json"
            )
        try:
            document = json.loads(
                self.store.artifacts.resolve_server_path(artifact.sha256).read_text(
                    encoding="utf-8"
                )
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ProductionRuntimeError(
                "capability deliverable is not valid JSON"
            ) from error
        if not isinstance(document, Mapping):
            raise ProductionRuntimeError("capability deliverable must be a JSON object")
        state, _ = self.worker._find_latest_state(run_id)
        run_documents = self._validated_strategy_documents(run, state)
        expected_document = run_documents.get(artifact_role)
        if expected_document is None or hashlib.sha256(expected_document).hexdigest() != (
            artifact.sha256
        ):
            raise ProductionRuntimeError(
                "capability deliverable bytes disagree with the delivered run artifact"
            )
        if receipt_artifact.media_type != "application/json":
            raise ProductionRuntimeError(
                "capability execution receipt media type is invalid"
            )
        receipt = self._verified_capability_execution_receipt(
            self.store,
            payload["execution_receipt_sha256"],
            campaign_id=campaign_id,
            capability_id=capability_id,
            artifact_role=artifact_role,
            artifact_sha256=artifact.sha256,
        )
        record = self.store.record_capability_deliverable(
            registration_id=payload["registration_id"],
            run_id=run_id,
            capability_id=capability_id,
            artifact_role=artifact_role,
            artifact_sha256=artifact.sha256,
            execution_receipt_sha256=receipt_artifact.sha256,
            media_type="application/json",
            campaign_id=campaign_id,
            model_id=receipt["model_id"],
            model_revision=receipt["model_revision"],
            accelerator=receipt["accelerator"],
            rights_basis=payload["rights_basis"],
            rights_locator=payload["rights_locator"],
            registered_by=authenticated_operator,
            payload={
                "schema": "ProofLaunchRunBoundCapabilityDeliverableV1",
                "artifact_role": artifact_role,
                "document_schema": document.get("schema"),
                "rights_confirmed": True,
                "source_kind": receipt["source_kind"],
                "local_model_inference_observed": receipt[
                    "local_model_inference_observed"
                ],
                "radeon_execution_observed": receipt["radeon_execution_observed"],
                "external_api_calls": receipt["external_api_calls"],
                "generated_deliverable_observed": True,
                "named_human_quality_observed": False,
                "external_publish_executed": False,
                "production_effect_proven": False,
                "four_a_quality_proven": False,
            },
        )
        result = asdict(record)
        result.update(
            {
                "schema": "ProofLaunchRunBoundCapabilityDeliverableV1",
                "generated_deliverable_observed": True,
                "named_human_quality_observed": False,
                "external_publish_executed": False,
                "production_effect_proven": False,
                "four_a_quality_proven": False,
            }
        )
        return result

    def review_capability_deliverable(
        self,
        run_id: str,
        registration_id: str,
        payload: Mapping[str, Any],
        *,
        authenticated_tenant: str,
        authenticated_reviewer: str,
    ) -> dict[str, Any]:
        self.store.require_run_tenant(run_id, authenticated_tenant)
        registrations = {
            item.registration_id: item
            for item in self.store.list_capability_deliverables(run_id)
        }
        if registration_id not in registrations:
            raise KeyError("unknown capability deliverable")
        review_id = payload.get("review_id")
        decision = payload.get("decision")
        reason = payload.get("reason")
        rubric_id = payload.get("rubric_id")
        criteria = payload.get("criteria")
        if not all(isinstance(value, str) for value in (
            review_id, decision, reason, rubric_id
        )) or not isinstance(criteria, Mapping):
            raise ProductionRuntimeError(
                "review_id, decision, reason, rubric_id and criteria are required"
            )
        required_criteria = (
            "completeness_passed", "traceability_passed",
            "brand_safety_passed", "rights_rechecked",
        )
        if any(type(criteria.get(field)) is not bool for field in required_criteria):
            raise ProductionRuntimeError("capability review criteria must be boolean")
        if decision == "pass" and not all(criteria[field] for field in required_criteria):
            raise ProductionRuntimeError(
                "a passing capability review requires every frozen criterion to pass"
            )
        record = self.store.record_capability_deliverable_review(
            review_id=review_id,
            registration_id=registration_id,
            run_id=run_id,
            decision=decision,
            reviewer=authenticated_reviewer,
            reason=reason,
            payload={
                "schema": "ProofLaunchCapabilityDeliverableReviewV1",
                "rubric_id": rubric_id,
                "criteria": dict(criteria),
                "reviewer_is_named": True,
                "external_publish_executed": False,
                "production_effect_proven": False,
                "four_a_preference_proven": False,
            },
        )
        result = asdict(record)
        result.update(
            {
                "schema": "ProofLaunchCapabilityDeliverableReviewV1",
                "named_human_quality_observed": record.decision == "pass",
                "external_publish_executed": False,
                "production_effect_proven": False,
                "four_a_preference_proven": False,
            }
        )
        return result

    def snapshot(self, run_id: str) -> dict[str, Any]:
        run = self.store.get_run(run_id)
        events = self.store.events_after(run_id)
        return {
            "schema": "ProofLaunchProductionRunStatusV1",
            "run_id": run.run_id,
            "request_digest": run.request_sha256,
            "campaign_id": run.request.get("campaign_id"),
            "status": run.status,
            "version": run.version,
            "event_count": len(events),
            "human_release_required": True,
            "external_release_executed": False,
        }

    def preview(self, run_id: str) -> dict[str, Any]:
        run = self.store.get_run(run_id)
        if run.status == "awaiting_release":
            state, _ = self.worker._find_prepared_state(run_id)
        elif run.status == "bundle_ready":
            state, _ = self.worker._find_latest_state(run_id)
        else:
            raise ConflictError(
                "preview is available only at awaiting_release or after delivery"
            )
        strategy_documents = self._validated_strategy_documents(run, state)
        strategy_plan = json.loads(
            strategy_documents["gtm-strategy.json"].decode("utf-8")
        )
        brief_intelligence = json.loads(
            strategy_documents["brief-intelligence.json"].decode("utf-8")
        )
        product_evidence_register = json.loads(
            strategy_documents["product-evidence-register.json"].decode("utf-8")
        )
        channel_portfolio = json.loads(
            strategy_documents["channel-portfolio.json"].decode("utf-8")
        )
        breakout_growth_loop = json.loads(
            strategy_documents["breakout-growth-loop.json"].decode("utf-8")
        )
        text_challenger = json.loads(
            strategy_documents["text-creative-challenger-plan.json"].decode("utf-8")
        )
        industry_gtm_profile = json.loads(
            strategy_documents["industry-gtm-profile.json"].decode("utf-8")
        )
        content_calendar = json.loads(
            strategy_documents["content-calendar.json"].decode("utf-8")
        )
        operating_kernels = {
            "creative_strategy": json.loads(
                strategy_documents["creative-strategy-kernel.json"].decode("utf-8")
            ),
            "editorial_quality": json.loads(
                strategy_documents["editorial-quality-receipt.json"].decode("utf-8")
            ),
            "multimodal_direction": json.loads(
                strategy_documents["multimodal-direction-receipt.json"].decode("utf-8")
            ),
            "distribution_operations": json.loads(
                strategy_documents["distribution-operations.json"].decode("utf-8")
            ),
            "revenue_journey": json.loads(
                strategy_documents["revenue-journey-operations.json"].decode("utf-8")
            ),
            "mechanism_abstraction": json.loads(
                strategy_documents["mechanism-abstraction-register.json"].decode("utf-8")
            ),
            "promotion_governance": json.loads(
                strategy_documents["promotion-governance.json"].decode("utf-8")
            ),
        }
        workspace_document_names = (
            "big-idea-and-message-hierarchy.json",
            "channel-copy.json",
            "landing-page-draft.json",
            "lifecycle-email-draft.json",
            "seo-geo-faq-drafts.json",
            "video-production-brief.json",
            "audio-production-brief.json",
            "analytics-plan.json",
            "content-calendar.json",
        )
        workspace_documents = {
            name: strategy_documents[name] for name in workspace_document_names
        }
        campaign_workspace = {
            "schema": "ProofLaunchCampaignWorkspacePublicV1",
            "artifact_set_sha256": _named_artifact_set_sha256(workspace_documents),
            "artifact_count": len(workspace_documents),
            "big_idea": json.loads(
                strategy_documents["big-idea-and-message-hierarchy.json"].decode("utf-8")
            ),
            "channel_copy": json.loads(
                strategy_documents["channel-copy.json"].decode("utf-8")
            ),
            "landing_page": json.loads(
                strategy_documents["landing-page-draft.json"].decode("utf-8")
            ),
            "lifecycle_email": json.loads(
                strategy_documents["lifecycle-email-draft.json"].decode("utf-8")
            ),
            "seo_geo": json.loads(
                strategy_documents["seo-geo-faq-drafts.json"].decode("utf-8")
            ),
            "video_brief": json.loads(
                strategy_documents["video-production-brief.json"].decode("utf-8")
            ),
            "audio_brief": json.loads(
                strategy_documents["audio-production-brief.json"].decode("utf-8")
            ),
            "analytics": json.loads(
                strategy_documents["analytics-plan.json"].decode("utf-8")
            ),
            "content_calendar": content_calendar,
            "human_release_required": True,
            "automatic_publish_enabled": False,
            "automatic_send_enabled": False,
            "automatic_spend_enabled": False,
            "external_activation_executed": False,
            "truth_boundary": (
                "These are source-bound campaign drafts from one validated run. "
                "They are not published assets, measured outcomes, or 4A preference evidence."
            ),
        }
        return {
            "schema": "ProofLaunchReleasePreviewPublicV1",
            "run_id": run_id,
            "preview_digest": state.prepared_preview_digest,
            "repair_count": state.repair_count,
            "claims": [asdict(item) for item in state.claims],
            "briefs": [asdict(item) for item in state.briefs],
            "findings": [
                {**asdict(item), "severity": item.severity.value}
                for item in state.findings
            ],
            "assets": [
                {
                    "asset_id": item.id,
                    "width": int(item.metadata.get("canvas_size", [0, 0])[0]),
                    "height": int(item.metadata.get("canvas_size", [0, 0])[1]),
                    "preview_url": f"/v1/runs/{run_id}/preview/{item.id}/creative",
                    "creative_url": f"/v1/runs/{run_id}/preview/{item.id}/creative",
                }
                for item in state.assets
            ],
            "gtm_strategy": {
                "plan_status": strategy_plan["plan_status"],
                "strategy_sha256": strategy_plan["strategy_sha256"],
                "claim_assurance": strategy_plan["claim_assurance"],
                "brief_intelligence": brief_intelligence,
                "product_evidence_register": product_evidence_register,
                "growth_tensions": strategy_plan["strategy"]["growth_tensions"],
                "primary_channel": strategy_plan["strategy"]["primary_channel"],
                "secondary_channel": strategy_plan["strategy"]["secondary_channel"],
                "seven_day_item_count": 7,
                "channel_portfolio": channel_portfolio,
                "breakout_growth_loop": breakout_growth_loop,
                "text_creative_challenger": {
                    "content_sha256": text_challenger["content_sha256"],
                    "territory_count": text_challenger["territory_count"],
                    "territory_ids": [
                        item["territory_id"] for item in text_challenger["territories"]
                    ],
                    "official_first_required": text_challenger[
                        "official_first_required"
                    ],
                    "maximum_model_calls": text_challenger["maximum_model_calls"],
                    "execution_policy": text_challenger["execution_policy"],
                    "execution_status": text_challenger["execution_status"],
                    "creative_alpha_plan": text_challenger[
                        "creative_alpha_plan"
                    ],
                    "winner_selected": text_challenger["winner_selected"],
                    "blind_review_completed": text_challenger[
                        "blind_review_completed"
                    ],
                    "external_publish_executed": text_challenger[
                        "external_publish_executed"
                    ],
                    "truth_boundary": text_challenger["truth_boundary"],
                },
                "industry_gtm_profile": industry_gtm_profile,
                "content_calendar": content_calendar,
                "operating_kernels": operating_kernels,
                "adaptive_capability_plan": strategy_plan[
                    "adaptive_capability_plan"
                ],
                "strategy_memory_decision": strategy_plan[
                    "strategy_memory_decision"
                ],
                "strategy_memory_application": strategy_plan[
                    "strategy_memory_application"
                ],
                "automated_publish_allowed": False,
                "external_publish_executed": False,
            },
            "campaign_workspace": campaign_workspace,
            "external_release_executed": False,
        }

    def gtm_cockpit(self, run_id: str) -> dict[str, Any]:
        """Aggregate the full GTM lifecycle into one decision-oriented surface.

        The cockpit never creates a second source of truth. It derives every
        field from the immutable launch request, validated preview, approval,
        aggregate observations, unit economics, and human-promoted memory.
        """

        run = self.store.get_run(run_id)
        request = run.request
        launch = ProductionLaunchRequest(**dict(request))
        inherited_learning = _learning_context_document(self.store, launch)
        public_status = "delivered" if run.status == "bundle_ready" else run.status
        preview: Mapping[str, Any] | None = None
        if run.status in {"awaiting_release", "bundle_ready"}:
            preview = self.preview(run_id)

        strategy = preview.get("gtm_strategy") if isinstance(preview, Mapping) else None
        workspace = (
            preview.get("campaign_workspace") if isinstance(preview, Mapping) else None
        )
        strategy = strategy if isinstance(strategy, Mapping) else {}
        workspace = workspace if isinstance(workspace, Mapping) else {}
        portfolio = strategy.get("channel_portfolio")
        portfolio = portfolio if isinstance(portfolio, Mapping) else {}
        calendar = strategy.get("content_calendar")
        calendar = calendar if isinstance(calendar, Mapping) else {}
        brief_intelligence = strategy.get("brief_intelligence")
        brief_intelligence = (
            brief_intelligence if isinstance(brief_intelligence, Mapping) else {}
        )
        product_evidence_register = strategy.get("product_evidence_register")
        product_evidence_register = (
            product_evidence_register
            if isinstance(product_evidence_register, Mapping)
            else {}
        )
        memory_application = strategy.get("strategy_memory_application")
        memory_application = (
            memory_application if isinstance(memory_application, Mapping) else {}
        )
        memory_decision = strategy.get("strategy_memory_decision")
        memory_decision = memory_decision if isinstance(memory_decision, Mapping) else {}
        adaptive_plan = strategy.get("adaptive_capability_plan")
        adaptive_plan = adaptive_plan if isinstance(adaptive_plan, Mapping) else {}
        adaptive_context = adaptive_plan.get("compiled_context")
        adaptive_context = (
            adaptive_context if isinstance(adaptive_context, Mapping) else {}
        )
        text_challenger = strategy.get("text_creative_challenger")
        text_challenger = (
            text_challenger if isinstance(text_challenger, Mapping) else {}
        )
        creative_alpha = text_challenger.get("creative_alpha_plan")
        creative_alpha = (
            creative_alpha if isinstance(creative_alpha, Mapping) else {}
        )
        market_language = creative_alpha.get("market_language_contract")
        market_language = (
            market_language if isinstance(market_language, Mapping) else {}
        )
        market_language_context = market_language.get("context")
        market_language_context = (
            market_language_context
            if isinstance(market_language_context, Mapping)
            else {}
        )
        team_capability = creative_alpha.get("gtm_team_capability_contract")
        team_capability = (
            team_capability if isinstance(team_capability, Mapping) else {}
        )
        active_team = team_capability.get("active_virtual_team")
        active_team = active_team if isinstance(active_team, Mapping) else {}
        adaptive_lane_states = adaptive_context.get("lane_states")
        adaptive_lane_states = (
            adaptive_lane_states if isinstance(adaptive_lane_states, Mapping) else {}
        )
        future_resolutions = [
            item
            for item in self.store.list_strategy_memory_resolutions(
                str(request.get("org_id")),
                str(request.get("project_id")),
            )
            if item.base_decision_sha256 == memory_decision.get("decision_sha256")
        ]
        frozen_conflict_channels = sorted(
            str(item.get("channel"))
            for item in memory_decision.get("conflicts", [])
            if isinstance(item, Mapping) and item.get("channel") is not None
        )
        future_resolution_channels = sorted(
            {item.channel for item in future_resolutions}
        )
        future_resolution_remaining_channels = sorted(
            set(frozen_conflict_channels) - set(future_resolution_channels)
        )
        future_resolution_complete = bool(frozen_conflict_channels) and not (
            future_resolution_remaining_channels
        )

        observations: Mapping[str, Any] = {
            "observation_count": 0,
            "latest_next_cycle_decision": None,
        }
        publication_receipts: Mapping[str, Any] = {
            "receipt_count": 0,
            "platform_delivery_verified_count": 0,
        }
        economics: Mapping[str, Any] = {
            "economics_count": 0,
            "positive_feedback_observation_count": 0,
            "latest_next_cycle_decision": None,
        }
        memories: Mapping[str, Any] = {"memory_count": 0}
        if run.status == "bundle_ready":
            publication_receipts = self.manual_publication_receipts(run_id)
            observations = self.effect_observations(run_id)
            economics = self.revenue_economics(run_id)
            memories = self.learning_memories_for_run(run_id)

        approval = self.store.get_approval(run_id)
        next_actions: list[dict[str, str]] = []
        if run.status in {"queued", "running", "auditing", "repairing"}:
            next_actions.append(
                {
                    "id": "monitor_governed_agent",
                    "priority": "now",
                    "owner": "campaign_operator",
                    "action": "Monitor the observable trajectory until the Agent reaches review or a bounded blocker.",
                    "reason": "The current Graph/Loop has not yet produced an approval-bound workspace.",
                }
            )
        elif run.status == "awaiting_release":
            if not product_evidence_register.get(
                "all_claims_public_release_eligible", False
            ):
                next_actions.append(
                    {
                        "id": "resolve_product_claim_release_scope",
                        "priority": "now",
                        "owner": "named_claim_approver",
                        "action": "Review every claim source and record a named approver plus exact public release scope.",
                        "reason": "The current pack is draft-reviewable but at least one outward claim is not public-release eligible.",
                    }
                )
            next_actions.extend(
                (
                    {
                        "id": "review_campaign_workspace",
                        "priority": "now",
                        "owner": "owner_reviewer",
                        "action": "Review the nine source-bound Campaign Workspace artifacts and the exact preview digest.",
                        "reason": "No activation, send, spend, or delivery may proceed without a content-bound human decision.",
                    },
                    {
                        "id": "approve_or_reject_release",
                        "priority": "next",
                        "owner": "owner_reviewer",
                        "action": "Approve or reject the immutable preview with a named reason.",
                        "reason": "The Agent has reached its consequential-action boundary.",
                    },
                )
            )
        elif run.status == "bundle_ready":
            if not product_evidence_register.get(
                "all_claims_public_release_eligible", False
            ):
                if int(publication_receipts.get("receipt_count", 0)) > 0:
                    next_actions.append(
                        {
                            "id": "remediate_publication_scope_breach",
                            "priority": "now",
                            "owner": "campaign_owner_and_claim_approver",
                            "action": "Pause further distribution; review the observed publication against every claim source, then record correction, takedown, or a newly authorized exact release scope.",
                            "reason": "A manual publication receipt exists while at least one outward claim remains draft-only or lacks a named public-release approver. Recording the receipt preserves evidence but does not cure the scope breach.",
                        }
                    )
                else:
                    next_actions.append(
                        {
                            "id": "resolve_product_claim_release_scope",
                            "priority": "now",
                            "owner": "named_claim_approver",
                            "action": "Review every claim source and record a named approver plus exact public release scope before activation.",
                            "reason": "Internal delivery does not upgrade an owner attestation into public-release authority.",
                        }
                    )
            elif int(publication_receipts.get("receipt_count", 0)) == 0:
                next_actions.extend(
                    (
                        {
                            "id": "human_controlled_activation",
                            "priority": "now",
                            "owner": "campaign_operator",
                            "action": "Execute only the approved channel treatment through a separately authorized human-controlled channel workflow.",
                            "reason": "The internal bundle is delivered, but this Agent intentionally holds no external publishing authority.",
                        },
                        {
                            "id": "record_preregistered_outcome",
                            "priority": "next",
                            "owner": "growth_analyst",
                            "action": "Record the candidate and comparable baseline aggregates against the preregistered experiment.",
                            "reason": "No effect or revenue conclusion is eligible without observed outcome data.",
                        },
                    )
                )
            elif int(observations.get("observation_count", 0)) == 0:
                next_actions.append(
                    {
                        "id": "record_preregistered_outcome",
                        "priority": "now",
                        "owner": "growth_analyst",
                        "action": "Record the candidate and comparable baseline aggregates against the preregistered experiment.",
                        "reason": "A candidate publication is operator-attested, but no effect or revenue conclusion is eligible without observed aggregate outcomes.",
                    }
                )
            elif int(economics.get("economics_count", 0)) == 0:
                next_actions.append(
                    {
                        "id": "reconcile_unit_economics",
                        "priority": "now",
                        "owner": "finance_reviewer",
                        "action": "Reconcile closed revenue, refunds, chargebacks, fulfillment, model, and operator costs for the latest observation.",
                        "reason": "Engagement or pipeline alone cannot establish a positive revenue loop.",
                    }
                )
            elif int(economics.get("positive_feedback_observation_count", 0)) > 0 and int(
                memories.get("memory_count", 0)
            ) == 0:
                next_actions.append(
                    {
                        "id": "human_promote_learning",
                        "priority": "now",
                        "owner": "owner_reviewer",
                        "action": "Review and promote only the aggregate positive-learning record into project memory.",
                        "reason": "Cross-run adaptation remains human-gated even after positive contribution evidence.",
                    }
                )
            else:
                next_actions.append(
                    {
                        "id": "decide_next_cycle",
                        "priority": "now",
                        "owner": "gtm_owner",
                        "action": "Use the latest effect and contribution decisions to continue, repair, stop, or design the next bounded experiment.",
                        "reason": "The next cycle must follow observed economics and guardrails rather than vanity metrics.",
                    }
                )
        else:
            next_actions.append(
                {
                    "id": "inspect_terminal_trace",
                    "priority": "now",
                    "owner": "campaign_operator",
                    "action": "Inspect the hash-chained trajectory and correct the located blocker before creating a new run.",
                    "reason": f"The run is terminal with status {public_status} and has no automatic recovery authority.",
                }
            )

        if (
            memory_application.get("status")
            == "blocked_pending_named_human_resolution"
            and future_resolution_complete
        ):
            next_actions.insert(
                0,
                {
                    "id": "create_run_with_frozen_memory_resolution",
                    "priority": "now",
                    "owner": "gtm_owner",
                    "action": (
                        "Create a new governed run to freeze and evaluate the named "
                        "conflict resolution against the same operating context."
                    ),
                    "reason": (
                        "The resolution is recorded for future runs; this source run "
                        "remains byte-immutable and blocked from retroactive application."
                    ),
                },
            )
        elif memory_application.get("status") == (
            "blocked_pending_named_human_resolution"
        ):
            next_actions.insert(
                0,
                {
                    "id": "resolve_strategy_memory_conflict",
                    "priority": "now",
                    "owner": "named_gtm_owner",
                    "action": (
                        "Review the frozen conflicting aggregate learnings and record "
                        "one named resolution for a later run."
                    ),
                    "reason": (
                        "The current run remains immutable and no strategy memory can "
                        "be selected while any eligible channel conflict is unresolved."
                    ),
                },
            )

        selected_focus = portfolio.get("focus_channels")
        if not isinstance(selected_focus, list):
            selected_focus = []
        selected_tests = portfolio.get("test_channels")
        if not isinstance(selected_tests, list):
            selected_tests = []
        capability_effect_matrix = _compile_capability_effect_matrix(
            strategy=strategy,
            workspace=workspace,
            portfolio=portfolio,
            calendar=calendar,
            inherited_memory_count=int(inherited_learning["memory_count"]),
            multimodal_deliverables=self.store.list_multimodal_deliverables(run_id),
            multimodal_reviews=self.store.list_multimodal_deliverable_reviews(run_id),
            capability_deliverables=self.store.list_capability_deliverables(run_id),
            capability_reviews=self.store.list_capability_deliverable_reviews(run_id),
        )
        cockpit: dict[str, Any] = {
            "schema": "ProofLaunchGTMCockpitV1",
            "run_id": run_id,
            "run_status": public_status,
            "campaign_id": request.get("campaign_id"),
            "product_name": request.get("product_name"),
            "operating_context": {
                "industry": request.get("industry"),
                "product_category": request.get("product_category"),
                "product_surface": request.get("product_surface"),
                "distribution_platform": request.get("platform"),
                "audience_role": request.get("audience_role"),
                "business_model": request.get("business_model"),
                "lifecycle": request.get("lifecycle"),
                "budget": request.get("budget"),
                "industry_risk": request.get("industry_risk"),
                "company_scale": request.get("company_scale"),
                "brand_reach": request.get("brand_reach"),
                "owned_audience_strength": request.get(
                    "owned_audience_strength"
                ),
                "community_access": request.get("community_access"),
                "partner_access": request.get("partner_access"),
                "content_capacity": request.get("content_capacity"),
                "sales_motion": request.get("sales_motion"),
                "market": request.get("market"),
                "audience": request.get("audience_name"),
                "goal": request.get("goal"),
                "offer": request.get("offer"),
            },
            "goal_diagnosis": {
                "input_contract_valid": True,
                "brief_intelligence_sha256": brief_intelligence.get(
                    "content_sha256"
                ),
                "primary_growth_tension_id": brief_intelligence.get(
                    "primary_growth_tension_id"
                ),
                "critical_question_count": brief_intelligence.get(
                    "critical_question_count"
                ),
                "critical_questions": brief_intelligence.get(
                    "critical_questions", []
                ),
                "goal_challenged": (
                    brief_intelligence.get("goal_feasibility", {}).get("challenged")
                    if isinstance(brief_intelligence.get("goal_feasibility"), Mapping)
                    else None
                ),
                "product_evidence_register_sha256": product_evidence_register.get(
                    "content_sha256"
                ),
                "public_release_eligible_claim_count": product_evidence_register.get(
                    "public_release_eligible_count"
                ),
                "product_claim_count": product_evidence_register.get("claim_count"),
                "all_claims_public_release_eligible": product_evidence_register.get(
                    "all_claims_public_release_eligible"
                ),
                "zero_media_spend": request.get("budget") == BudgetTier.ZERO.value,
                "human_release_required": request.get("human_release_required") is True,
                "high_regulation_specialist_bound": (
                    request.get("industry_risk") != IndustryRisk.HIGH_REGULATION.value
                    or bool(request.get("specialist_approved_by"))
                ),
                "recommendation": (
                    "proceed_through_current_bounded_gate"
                    if run.status not in {"blocked", "failed", "rejected", "cancelled"}
                    else "repair_or_stop_before_new_execution"
                ),
            },
            "strategy_and_channels": {
                "available": bool(strategy),
                "strategy_sha256": strategy.get("strategy_sha256"),
                "claim_assurance": strategy.get("claim_assurance"),
                "primary_channel": strategy.get("primary_channel"),
                "secondary_channel": strategy.get("secondary_channel"),
                "focus_channels": selected_focus,
                "test_channels": selected_tests,
                "decision_confidence": portfolio.get("decision_confidence"),
                "focus_margin_points": portfolio.get("focus_margin_points"),
                "authorized_platform_signal_input_used": portfolio.get(
                    "authorized_platform_signal_input_used", False
                ),
                "reallocation_mode": (
                    portfolio.get("reallocation_policy", {}).get("mode")
                    if isinstance(portfolio.get("reallocation_policy"), Mapping)
                    else None
                ),
                "paid_channel_activated": False,
                "adaptive_capability_plan_sha256": adaptive_plan.get(
                    "content_sha256"
                ),
                "adaptive_context_id": adaptive_context.get("context_id"),
                "adaptive_lane_states": dict(adaptive_lane_states),
                "adaptive_focus_lanes": sorted(
                    lane
                    for lane, state in adaptive_lane_states.items()
                    if state == "FOCUS"
                ),
                "adaptive_test_lanes": sorted(
                    lane
                    for lane, state in adaptive_lane_states.items()
                    if state == "TEST"
                ),
                "adaptive_distribution_aggregation": adaptive_plan.get(
                    "distribution_aggregation"
                ),
                "adaptive_hardware_and_provider_in_plan_identity": adaptive_plan.get(
                    "hardware_and_provider_in_plan_identity"
                ),
                "adaptive_human_release_required": adaptive_plan.get(
                    "human_release_required"
                ),
                "adaptive_automatic_external_actions": adaptive_context.get(
                    "automatic_external_actions"
                ),
                "creative_alpha_plan_sha256": creative_alpha.get(
                    "content_sha256"
                ),
                "creative_alpha_growth_case_status": creative_alpha.get(
                    "growth_case_radar_status"
                ),
                "creative_alpha_style_ids": [
                    str(item.get("style_id"))
                    for item in creative_alpha.get("style_portfolio", [])
                    if isinstance(item, Mapping) and item.get("style_id")
                ],
                "creative_alpha_platform_grammar_count": len(
                    creative_alpha.get("platform_grammars", {})
                )
                if isinstance(creative_alpha.get("platform_grammars"), Mapping)
                else 0,
                "creative_alpha_external_actions": creative_alpha.get(
                    "external_action_count"
                ),
                "creative_alpha_human_release_required": creative_alpha.get(
                    "human_release_required"
                ),
                "market_language_contract_sha256": market_language.get(
                    "content_sha256"
                ),
                "market_language_signature_sha256": market_language.get(
                    "language_signature_sha256"
                ),
                "market_language_reference_family": market_language_context.get(
                    "resolved_reference_family"
                ),
                "market_language_primary_role": market_language_context.get(
                    "resolved_primary_role"
                ),
                "market_language_external_actions": market_language.get(
                    "external_action_count"
                ),
                "gtm_team_capability_contract_sha256": team_capability.get(
                    "content_sha256"
                ),
                "gtm_team_full_role_count": team_capability.get(
                    "full_skill_registry", {}
                ).get("role_count"),
                "gtm_team_full_atomic_skill_count": team_capability.get(
                    "full_skill_registry", {}
                ).get("atomic_skill_count"),
                "gtm_team_active_role_ids": [
                    str(item.get("role_id"))
                    for item in active_team.get("roles", [])
                    if isinstance(item, Mapping) and item.get("role_id")
                ],
                "gtm_team_automatic_external_actions": team_capability.get(
                    "automatic_external_action_count"
                ),
            },
            "campaign_workspace": {
                "available": bool(workspace),
                "artifact_set_sha256": workspace.get("artifact_set_sha256"),
                "artifact_count": workspace.get("artifact_count", 0),
                "big_idea_available": isinstance(workspace.get("big_idea"), Mapping),
                "channel_copy_available": isinstance(
                    workspace.get("channel_copy"), Mapping
                ),
                "landing_available": isinstance(workspace.get("landing_page"), Mapping),
                "email_available": isinstance(workspace.get("lifecycle_email"), Mapping),
                "seo_geo_available": isinstance(workspace.get("seo_geo"), Mapping),
                "video_brief_available": isinstance(workspace.get("video_brief"), Mapping),
                "audio_brief_available": isinstance(workspace.get("audio_brief"), Mapping),
                "analytics_available": isinstance(workspace.get("analytics"), Mapping),
                "schedule_slot_count": len(calendar.get("slots", []))
                if isinstance(calendar.get("slots"), list)
                else 0,
                "external_activation_executed": False,
            },
            "capability_effect_matrix": capability_effect_matrix,
            "effect_and_revenue": {
                "manual_publication_receipt_count": publication_receipts.get(
                    "receipt_count", 0
                ),
                "platform_delivery_verified_count": publication_receipts.get(
                    "platform_delivery_verified_count", 0
                ),
                "observation_count": observations.get("observation_count", 0),
                "latest_effect_decision": observations.get(
                    "latest_next_cycle_decision"
                ),
                "economics_count": economics.get("economics_count", 0),
                "positive_feedback_observation_count": economics.get(
                    "positive_feedback_observation_count", 0
                ),
                "latest_revenue_decision": economics.get(
                    "latest_next_cycle_decision"
                ),
                "human_promoted_memory_count": memories.get("memory_count", 0),
                "pipeline_counted_as_revenue": False,
                "causal_revenue_claim_allowed": False,
            },
            "cross_device_memory": {
                "context_sha256": inherited_learning["context_sha256"],
                "inherited_memory_count": inherited_learning["memory_count"],
                "latest_next_cycle_decision": inherited_learning[
                    "latest_next_cycle_decision"
                ],
                "decision_sha256": strategy.get(
                    "strategy_memory_decision", {}
                ).get("decision_sha256")
                if isinstance(strategy.get("strategy_memory_decision"), Mapping)
                else None,
                "application_status": strategy.get(
                    "strategy_memory_decision", {}
                ).get("status")
                if isinstance(strategy.get("strategy_memory_decision"), Mapping)
                else "not_yet_compiled",
                "eligible_memory_count": strategy.get(
                    "strategy_memory_decision", {}
                ).get("eligible_memory_count", 0)
                if isinstance(strategy.get("strategy_memory_decision"), Mapping)
                else 0,
                "conflict_count": strategy.get(
                    "strategy_memory_decision", {}
                ).get("conflict_count", 0)
                if isinstance(strategy.get("strategy_memory_decision"), Mapping)
                else 0,
                "conflicts": strategy.get(
                    "strategy_memory_decision", {}
                ).get("conflicts", [])
                if isinstance(strategy.get("strategy_memory_decision"), Mapping)
                else [],
                "recommended_directives": strategy.get(
                    "strategy_memory_decision", {}
                ).get("recommended_directives", [])
                if isinstance(strategy.get("strategy_memory_decision"), Mapping)
                else [],
                "application_sha256": memory_application.get(
                    "application_sha256"
                ),
                "effective_application_status": memory_application.get(
                    "status", "not_yet_compiled"
                ),
                "resolved_conflict_count": memory_application.get(
                    "resolved_conflict_count", 0
                ),
                "unresolved_conflict_channels": memory_application.get(
                    "unresolved_conflict_channels", []
                ),
                "selected_directives": memory_application.get(
                    "selected_directives", []
                ),
                "resolution_context_sha256": memory_application.get(
                    "resolution_context_sha256"
                ),
                "future_resolution_recorded": bool(future_resolutions),
                "future_resolution_complete": future_resolution_complete,
                "future_resolution_count": len(future_resolutions),
                "future_resolution_remaining_channels": (
                    future_resolution_remaining_channels
                ),
                "future_resolution_sha256": [
                    item.resolution_sha256 for item in future_resolutions
                ],
                "future_resolution_winner_memory_ids": [
                    item.winner_memory_id for item in future_resolutions
                ],
                "source_run_mutated": False,
                "human_application_required": True,
                "human_promoted_only": inherited_learning["human_promoted_only"],
                "frozen_at_run_creation": True,
                "automatic_strategy_mutation_executed": False,
                "automatic_schedule_mutation_executed": False,
                "automatic_budget_activation_executed": False,
            },
            "human_boundary": {
                "approval_recorded": approval is not None,
                "approval_decision": approval.decision if approval is not None else None,
                "automatic_publish_enabled": False,
                "automatic_send_enabled": False,
                "automatic_spend_enabled": False,
                "automatic_strategy_mutation_enabled": False,
            },
            "next_best_actions": next_actions,
            "four_a_effect_claim_eligible": False,
            "top1_claim_eligible": False,
            "truth_boundary": (
                "The cockpit summarizes one governed run and its observed aggregate evidence. "
                "It does not prove publication, incremental lift, causal revenue, annual breakout, "
                "4A preference, or Top-1 standing."
            ),
        }
        unsigned = dict(cockpit)
        cockpit["content_sha256"] = hashlib.sha256(
            canonical_json(unsigned).encode("utf-8")
        ).hexdigest()
        return cockpit

    def preview_asset(self, run_id: str, asset_id: str, role: str) -> Path:
        if role not in {"creative", "product_layer", "background"}:
            raise KeyError("unknown preview role")
        run = self.store.get_run(run_id)
        if run.status not in {"awaiting_release", "running", "bundle_ready"}:
            raise ConflictError("preview asset is unavailable in this state")
        state, _ = self.worker._find_latest_state(run_id)
        asset = next((item for item in state.assets if item.id == asset_id), None)
        if asset is None:
            raise KeyError("unknown preview asset")
        paths = dict(state.release_file_paths(asset))
        candidate = Path(paths[role]).resolve(strict=True)
        try:
            candidate.relative_to(state.output_path.resolve(strict=True))
        except ValueError as error:
            raise ProductionRuntimeError("preview asset escaped the campaign directory") from error
        if candidate.is_symlink() or not candidate.is_file():
            raise ProductionRuntimeError("preview asset is not a regular file")
        return candidate

    def queue_release(
        self,
        run_id: str,
        *,
        decision: str,
        reason: str,
        authenticated_approver: str,
    ) -> dict[str, Any]:
        run = self.store.get_run(run_id)
        if run.status not in {"awaiting_release", "running"}:
            raise ConflictError("run is not at a release boundary")
        state, output_relative = self.worker._find_prepared_state(run_id)
        strategy_documents = self._validated_strategy_documents(run, state)
        strategy_plan_sha256 = hashlib.sha256(
            strategy_documents["gtm-strategy.json"]
        ).hexdigest()
        gtm_artifact_set_sha256 = _artifact_set_sha256(strategy_documents)
        production_preview_sha256 = hashlib.sha256(
            canonical_json(
                {
                    "campaign_preview_sha256": state.prepared_preview_digest,
                    "strategy_plan_sha256": strategy_plan_sha256,
                    "gtm_artifact_set_sha256": gtm_artifact_set_sha256,
                }
            ).encode("utf-8")
        ).hexdigest()
        try:
            decision_enum = ReleaseDecision(decision)
        except ValueError as error:
            raise ProductionRuntimeError("decision must be approve or reject") from error
        existing = self.store.get_approval(run_id)
        if existing is None:
            approval = ReleaseApproval.create(
                run_id=run_id,
                preview_digest=state.prepared_preview_digest or "",
                decision=decision_enum,
                approver=authenticated_approver,
                reason=reason,
                kind=ReleaseApprovalKind.HUMAN,
            )
            self.store.record_approval(
                run_id,
                approval_id=approval.approval_id,
                preview_sha256=approval.preview_digest,
                decision=approval.decision.value,
                approver=approval.approver,
                reason=approval.reason,
                decided_at=datetime.fromisoformat(approval.issued_at),
                payload={
                    **approval.serializable(),
                    "strategy_plan_sha256": strategy_plan_sha256,
                    "gtm_artifact_set_sha256": gtm_artifact_set_sha256,
                    "production_preview_sha256": production_preview_sha256,
                    "strategy_plan_status": "draft_pending_human_release",
                },
            )
        else:
            approval = ReleaseApproval.from_serializable(dict(existing.payload))
            if (
                approval.decision is not decision_enum
                or approval.approver != authenticated_approver
                or approval.reason != reason.strip()
                or existing.payload.get("strategy_plan_sha256")
                != strategy_plan_sha256
                or existing.payload.get("gtm_artifact_set_sha256")
                != gtm_artifact_set_sha256
                or existing.payload.get("production_preview_sha256")
                != production_preview_sha256
            ):
                raise ConflictError("a different immutable release decision already exists")
        if run.status == "awaiting_release":
            self.store.transition_run(
                run_id,
                expected_status="awaiting_release",
                new_status="running",
                details={"phase": "release", "approval_id": approval.approval_id},
            )
        self.store.enqueue_job(
            f"release:{approval.approval_id}",
            run_id,
            kind="release",
            payload={
                "approval": approval.serializable(),
                "output_relative": output_relative,
            },
        )
        return self.snapshot(run_id)

    def record_effect_observation(
        self,
        run_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        """Bind one aggregate observation to the approved experiment.

        Observations are append-only hash-chain events. They may recommend a
        bounded next-cycle action, but they never edit the approved strategy or
        trigger an external release.
        """

        run = self.store.get_run(run_id)
        if run.status != "bundle_ready":
            raise ConflictError(
                "effect observation requires a delivered, human-approved run"
            )
        approval = self.store.get_approval(run_id)
        if approval is None or approval.decision != "approve":
            raise ConflictError("effect observation requires an approved release")
        state, _ = self.worker._find_latest_state(run_id)
        strategy_documents = self._validated_strategy_documents(run, state)
        strategy_plan_sha256 = hashlib.sha256(
            strategy_documents["gtm-strategy.json"]
        ).hexdigest()
        experiment = json.loads(
            strategy_documents["experiment.json"].decode("utf-8")
        )
        minimum_samples = {
            str(item["metric"]): int(item["minimum_sample"])
            for item in experiment["metrics"]
        }
        try:
            observation = compile_effect_observation(
                payload,
                expected_experiment_id=str(
                    experiment["attribution"]["experiment_id"]
                ),
                expected_strategy_plan_sha256=strategy_plan_sha256,
                registered_minimum_samples=minimum_samples,
                zero_budget=run.request.get("budget") == BudgetTier.ZERO.value,
            )
        except EffectFeedbackError as error:
            raise ProductionRuntimeError(
                f"effect observation safety gate failed: {error}"
            ) from error
        for event in self.store.events_after(run_id):
            if event.event_type != "effect_observation_recorded":
                continue
            existing = event.payload.get("observation")
            if not isinstance(existing, Mapping):
                raise ProductionRuntimeError("effect observation event is malformed")
            if existing.get("observation_id") != observation["observation_id"]:
                continue
            if (
                existing.get("input_sha256")
                != observation["input_sha256"]
            ):
                raise ConflictError(
                    "observation ID was reused with different aggregate results"
                )
            return dict(existing)
        self.store.append_event(
            run_id,
            "effect_observation_recorded",
            {
                "observation_id": observation["observation_id"],
                "observation_sha256": observation["observation_sha256"],
                "next_cycle_decision": observation["next_cycle_decision"],
                "observation": observation,
            },
        )
        return observation

    def effect_observations(self, run_id: str) -> dict[str, object]:
        run = self.store.get_run(run_id)
        if run.status != "bundle_ready":
            raise ConflictError(
                "effect observations require a delivered, human-approved run"
            )
        state, _ = self.worker._find_latest_state(run_id)
        strategy_documents = self._validated_strategy_documents(run, state)
        strategy_plan_sha256 = hashlib.sha256(
            strategy_documents["gtm-strategy.json"]
        ).hexdigest()
        experiment = json.loads(
            strategy_documents["experiment.json"].decode("utf-8")
        )
        observations: list[Mapping[str, object]] = []
        for event in self.store.events_after(run_id):
            if event.event_type != "effect_observation_recorded":
                continue
            observation = event.payload.get("observation")
            if not isinstance(observation, Mapping):
                raise ProductionRuntimeError("effect observation event is malformed")
            observations.append(observation)
        return {
            "schema": "ProofLaunchEffectObservationCollectionV1",
            "run_id": run_id,
            "experiment_id": experiment["attribution"]["experiment_id"],
            "strategy_plan_sha256": strategy_plan_sha256,
            "registered_metrics": experiment["metrics"],
            "budget_contract": run.request.get("budget"),
            "observation_count": len(observations),
            "observations": observations,
            "latest_next_cycle_decision": (
                observations[-1]["next_cycle_decision"] if observations else None
            ),
            "automatic_strategy_mutation_executed": False,
            "automatic_external_publish_executed": False,
        }

    def production_observation_field_kit(
        self,
        run_id: str,
    ) -> tuple[bytes, str, str]:
        """Return a deterministic credential-free kit bound to an approved run."""

        run = self.store.get_run(run_id)
        if run.status != "bundle_ready":
            raise ConflictError(
                "production observation kit requires a delivered, human-approved run"
            )
        approval = self.store.get_approval(run_id)
        if approval is None or approval.decision != "approve":
            raise ConflictError(
                "production observation kit requires an approved release"
            )
        state, _ = self.worker._find_latest_state(run_id)
        strategy_documents = self._validated_strategy_documents(run, state)
        strategy_plan_sha256 = hashlib.sha256(
            strategy_documents["gtm-strategy.json"]
        ).hexdigest()
        experiment = json.loads(
            strategy_documents["experiment.json"].decode("utf-8")
        )
        try:
            body, _ = compile_production_observation_field_kit(
                run_id=run_id,
                campaign_id=str(run.request["campaign_id"]),
                product_name=str(run.request["product_name"]),
                experiment=experiment,
                strategy_plan_sha256=strategy_plan_sha256,
                budget_contract=str(run.request.get("budget", "")),
                generated_at=run.created_at,
            )
        except ProductionObservationKitError as error:
            raise ProductionRuntimeError(
                f"production observation kit safety gate failed: {error}"
            ) from error
        digest = hashlib.sha256(body).hexdigest()
        return body, digest, f"{run_id}-production-observation-kit.zip"

    def record_manual_publication_receipt(
        self,
        run_id: str,
        payload: Mapping[str, object],
        *,
        authenticated_operator: str,
    ) -> dict[str, object]:
        """Record, but never perform, one human-controlled candidate publication."""

        run = self.store.get_run(run_id)
        if run.status != "bundle_ready":
            raise ConflictError(
                "publication receipt requires a delivered, human-approved run"
            )
        approval = self.store.get_approval(run_id)
        if approval is None or approval.decision != "approve":
            raise ConflictError("publication receipt requires an approved release")
        state, _ = self.worker._find_latest_state(run_id)
        documents = self._validated_strategy_documents(run, state)
        strategy_plan_sha256 = hashlib.sha256(
            documents["gtm-strategy.json"]
        ).hexdigest()
        strategy_plan = json.loads(documents["gtm-strategy.json"].decode("utf-8"))
        experiment = json.loads(documents["experiment.json"].decode("utf-8"))
        attribution = experiment.get("attribution")
        if not isinstance(attribution, Mapping):
            raise ProductionRuntimeError("experiment attribution is malformed")
        attribution_plan = compile_aggregate_attribution_plan(
            run_id=run_id,
            campaign_id=str(run.request["campaign_id"]),
            experiment_id=str(attribution["experiment_id"]),
            strategy_plan_sha256=strategy_plan_sha256,
            attribution=attribution,
        )
        arms = attribution_plan.get("arms")
        candidate_tags = arms.get("candidate") if isinstance(arms, Mapping) else None
        if not isinstance(candidate_tags, Mapping):
            raise ProductionRuntimeError("candidate attribution tags are malformed")
        channel = payload.get("channel")
        strategy = strategy_plan.get("strategy")
        if not isinstance(strategy, Mapping):
            raise ProductionRuntimeError("strategy channel contract is malformed")
        allowed_channels = {
            str(strategy.get("primary_channel")),
            str(strategy.get("secondary_channel")),
            "landing_page",
            "lifecycle_email",
            "seo_geo_answer",
            "community_relay",
            "multimodal_production",
        }
        if channel not in allowed_channels:
            raise ProductionRuntimeError("channel is not approved by the strategy workspace")
        workspace_names = (
            "big-idea-and-message-hierarchy.json",
            "channel-copy.json",
            "landing-page-draft.json",
            "lifecycle-email-draft.json",
            "seo-geo-faq-drafts.json",
            "video-production-brief.json",
            "audio-production-brief.json",
            "analytics-plan.json",
            "content-calendar.json",
        )
        allowed_assets = {
            name: hashlib.sha256(documents[name]).hexdigest()
            for name in workspace_names
        }
        try:
            receipt = compile_manual_publication_receipt(
                payload,
                run_id=run_id,
                campaign_id=str(run.request["campaign_id"]),
                experiment_id=str(attribution["experiment_id"]),
                strategy_plan_sha256=strategy_plan_sha256,
                attribution_plan_sha256=str(
                    attribution_plan["attribution_plan_sha256"]
                ),
                candidate_tags={
                    str(key): str(value) for key, value in candidate_tags.items()
                },
                allowed_assets=allowed_assets,
                authenticated_operator=authenticated_operator,
            )
        except ManualPublicationReceiptError as error:
            raise ProductionRuntimeError(
                f"manual publication receipt safety gate failed: {error}"
            ) from error
        for event in self.store.events_after(run_id):
            if event.event_type != "manual_publication_receipt_recorded":
                continue
            existing = event.payload.get("receipt")
            if not isinstance(existing, Mapping):
                raise ProductionRuntimeError("publication receipt event is malformed")
            if existing.get("receipt_id") != receipt["receipt_id"]:
                continue
            if existing.get("content_sha256") != receipt["content_sha256"]:
                raise ConflictError(
                    "publication receipt ID was reused with different evidence"
                )
            return dict(existing)
        self.store.append_event(
            run_id,
            "manual_publication_receipt_recorded",
            {
                "receipt_id": receipt["receipt_id"],
                "publication_receipt_sha256": receipt["content_sha256"],
                "receipt": receipt,
            },
        )
        return receipt

    def manual_publication_receipts(self, run_id: str) -> dict[str, object]:
        run = self.store.get_run(run_id)
        if run.status != "bundle_ready":
            raise ConflictError(
                "publication receipts require a delivered, human-approved run"
            )
        receipts: list[Mapping[str, object]] = []
        for event in self.store.events_after(run_id):
            if event.event_type != "manual_publication_receipt_recorded":
                continue
            receipt = event.payload.get("receipt")
            if not isinstance(receipt, Mapping):
                raise ProductionRuntimeError("publication receipt event is malformed")
            receipts.append(receipt)
        return {
            "schema": "ProofLaunchManualPublicationReceiptCollectionV1",
            "run_id": run_id,
            "receipt_count": len(receipts),
            "receipts": receipts,
            "publication_performed_by_prooflaunch": False,
            "platform_delivery_verified_count": 0,
            "effect_claim_eligible": False,
        }

    def record_revenue_economics(
        self,
        run_id: str,
        observation_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        collection = self.effect_observations(run_id)
        observation = next(
            (
                item
                for item in collection["observations"]
                if item.get("observation_id") == observation_id
            ),
            None,
        )
        if not isinstance(observation, Mapping):
            raise KeyError("unknown effect observation")
        run = self.store.get_run(run_id)
        try:
            economics = compile_revenue_economics(
                payload,
                effect_observation=observation,
                zero_budget=run.request.get("budget") == BudgetTier.ZERO.value,
            )
        except RevenueFeedbackError as error:
            raise ProductionRuntimeError(
                f"revenue economics safety gate failed: {error}"
            ) from error
        for event in self.store.events_after(run_id):
            if event.event_type != "revenue_economics_recorded":
                continue
            existing = event.payload.get("economics")
            if not isinstance(existing, Mapping):
                raise ProductionRuntimeError("revenue economics event is malformed")
            if existing.get("economics_id") != economics["economics_id"]:
                continue
            if existing.get("input_sha256") != economics["input_sha256"]:
                raise ConflictError(
                    "economics ID was reused with different unit-economics results"
                )
            return dict(existing)
        self.store.append_event(
            run_id,
            "revenue_economics_recorded",
            {
                "economics_id": economics["economics_id"],
                "economics_sha256": economics["economics_sha256"],
                "effect_observation_id": observation_id,
                "next_cycle_decision": economics["next_cycle_decision"],
                "economics": economics,
            },
        )
        return economics

    def revenue_economics(self, run_id: str) -> dict[str, object]:
        collection = self.effect_observations(run_id)
        rows: list[Mapping[str, object]] = []
        for event in self.store.events_after(run_id):
            if event.event_type != "revenue_economics_recorded":
                continue
            economics = event.payload.get("economics")
            if not isinstance(economics, Mapping):
                raise ProductionRuntimeError("revenue economics event is malformed")
            rows.append(economics)
        return {
            "schema": "ProofLaunchRevenueEconomicsCollectionV1",
            "run_id": run_id,
            "experiment_id": collection["experiment_id"],
            "strategy_plan_sha256": collection["strategy_plan_sha256"],
            "budget_contract": collection["budget_contract"],
            "economics_count": len(rows),
            "economics": rows,
            "positive_feedback_observation_count": sum(
                item.get("revenue_positive_feedback_ready") is True for item in rows
            ),
            "latest_next_cycle_decision": (
                rows[-1]["next_cycle_decision"] if rows else None
            ),
            "pipeline_counted_as_revenue": False,
            "causal_revenue_claim_allowed": False,
            "automatic_budget_activation_executed": False,
            "automatic_strategy_mutation_executed": False,
            "automatic_external_publish_executed": False,
        }

    def promote_effect_observation(
        self,
        run_id: str,
        observation_id: str,
        *,
        reason: str,
        authenticated_approver: str,
    ) -> dict[str, object]:
        collection = self.effect_observations(run_id)
        observation = next(
            (
                item
                for item in collection["observations"]
                if item.get("observation_id") == observation_id
            ),
            None,
        )
        if not isinstance(observation, Mapping):
            raise KeyError("unknown effect observation")
        matching_economics = [
            item
            for item in self.revenue_economics(run_id)["economics"]
            if item.get("effect_observation_id") == observation_id
        ]
        if len(matching_economics) > 1:
            raise ProductionRuntimeError(
                "multiple unit-economics records are bound to one effect observation"
            )
        run = self.store.get_run(run_id)
        try:
            payload = promoted_memory_payload(
                observation,
                revenue_economics=(
                    matching_economics[0] if matching_economics else None
                ),
                applicability_context={
                    "industry": run.request["industry"],
                    "business_model": run.request["business_model"],
                    "lifecycle": run.request["lifecycle"],
                    "budget": run.request["budget"],
                    "industry_risk": run.request["industry_risk"],
                    "market": run.request["market"],
                },
            )
        except LearningMemoryError as error:
            raise ProductionRuntimeError(
                f"learning memory promotion gate failed: {error}"
            ) from error
        normalized_reason = reason.strip()
        if not normalized_reason:
            raise ProductionRuntimeError("learning promotion reason is required")
        for existing in self.store.list_learning_memories(
            str(run.request["org_id"]), str(run.request["project_id"])
        ):
            if (
                existing.source_run_id == run_id
                and existing.observation_id == observation_id
            ):
                if (
                    existing.approved_by != authenticated_approver
                    or existing.reason != normalized_reason
                    or dict(existing.payload) != payload
                ):
                    raise ConflictError(
                        "a different immutable learning promotion already exists"
                    )
                return asdict(existing)
        memory_id = f"learning-{str(observation['observation_sha256'])[:24]}"
        record = self.store.record_learning_memory(
            memory_id=memory_id,
            org_id=str(run.request["org_id"]),
            project_id=str(run.request["project_id"]),
            source_run_id=run_id,
            observation_id=observation_id,
            approved_by=authenticated_approver,
            reason=normalized_reason,
            payload=payload,
        )
        return asdict(record)

    def learning_memories_for_run(self, run_id: str) -> dict[str, object]:
        run = self.store.get_run(run_id)
        records = self.store.list_learning_memories(
            str(run.request["org_id"]), str(run.request["project_id"])
        )
        return {
            "schema": "ProofLaunchProjectLearningMemoryCollectionV1",
            "run_id": run_id,
            "org_id": run.request["org_id"],
            "project_id": run.request["project_id"],
            "memory_count": len(records),
            "memories": [asdict(item) for item in records],
            "human_promoted_only": True,
            "automatic_strategy_mutation_executed": False,
        }

    def bundle_path(self, run_id: str) -> Path:
        run = self.store.get_run(run_id)
        if run.status != "bundle_ready":
            raise ConflictError("bundle requires a delivered, human-approved run")
        state, _ = self.worker._find_latest_state(run_id)
        if state.stage is not Stage.DELIVER or state.release_approval is None:
            raise ProductionRuntimeError("delivered runtime state is incomplete")
        if state.release_approval.kind is not ReleaseApprovalKind.HUMAN:
            raise ProductionRuntimeError("production bundle lacks human approval")
        campaign_pack = state.output_path / "campaign-pack.zip"
        if campaign_pack.is_symlink() or not campaign_pack.is_file():
            raise ProductionRuntimeError("campaign bundle is missing")
        approval = self.store.get_approval(run_id)
        if approval is None or approval.approval_id != state.release_approval.approval_id:
            raise ProductionRuntimeError("durable approval and campaign state disagree")
        strategy_documents = self._validated_strategy_documents(run, state)
        approved_strategy_sha256 = hashlib.sha256(
            strategy_documents["gtm-strategy.json"]
        ).hexdigest()
        approved_gtm_artifact_set_sha256 = _artifact_set_sha256(strategy_documents)
        if approval.payload.get("strategy_plan_sha256") != approved_strategy_sha256:
            raise ProductionRuntimeError(
                "durable human approval is not bound to the strategy draft"
            )
        if (
            approval.payload.get("gtm_artifact_set_sha256")
            != approved_gtm_artifact_set_sha256
        ):
            raise ProductionRuntimeError(
                "durable human approval is not bound to the complete GTM artifact set"
            )
        production_preview_sha256 = hashlib.sha256(
            canonical_json(
                {
                    "campaign_preview_sha256": state.prepared_preview_digest,
                    "strategy_plan_sha256": approved_strategy_sha256,
                    "gtm_artifact_set_sha256": approved_gtm_artifact_set_sha256,
                }
            ).encode("utf-8")
        ).hexdigest()
        if (
            approval.payload.get("production_preview_sha256")
            != production_preview_sha256
        ):
            raise ProductionRuntimeError(
                "durable human approval is not bound to the production preview"
            )
        release_job = self.store.get_job(f"release:{approval.approval_id}")
        if release_job.status != "succeeded":
            raise ConflictError("production bundle waits for the durable release job")
        if not self.store.verify_event_chain(run_id):
            raise ProductionRuntimeError("durable run event chain failed verification")
        campaign_ledger = state.output_path / "evidence-ledger.jsonl"
        if not EvidenceLedger.verify(campaign_ledger):
            raise ProductionRuntimeError("campaign evidence ledger failed verification")

        run = self.store.get_run(run_id)
        store_events = self.store.events_after(run_id)
        public_state = self._public_campaign_state(state, run)
        public_campaign_events = self._public_campaign_ledger(campaign_ledger, state)
        effect_observation_collection = self.effect_observations(run_id)
        effect_observations = list(effect_observation_collection["observations"])
        revenue_economics_collection = self.revenue_economics(run_id)
        effect_readiness = _effect_readiness_document(
            run_id=run_id,
            strategy_plan_sha256=approved_strategy_sha256,
            observations=effect_observations,
        )
        members: dict[str, bytes] = {
            "request.json": self._pretty_json(dict(run.request)),
            "run.json": self._pretty_json(self.snapshot(run_id)),
            "events.jsonl": "".join(
                canonical_json(
                    {
                        "event_id": item.event_id,
                        "sequence": item.sequence,
                        "type": item.event_type,
                        "payload": dict(item.payload),
                        "occurred_at": item.occurred_at,
                        "previous_hash": item.previous_hash,
                        "event_hash": item.event_hash,
                    }
                )
                + "\n"
                for item in store_events
            ).encode("utf-8"),
            "approval.json": self._pretty_json(dict(approval.payload)),
            "campaign-state.json": self._pretty_json(public_state),
            "campaign-evidence-ledger.jsonl": public_campaign_events,
            "campaign-pack.zip": campaign_pack.read_bytes(),
            **strategy_documents,
            "effect-observations.json": self._pretty_json(
                effect_observation_collection
            ),
            "effect-readiness.json": effect_readiness,
            "revenue-economics.json": self._pretty_json(
                revenue_economics_collection
            ),
        }
        manifest = {
            "schema": "ProofLaunchProductionBundleV1",
            "run_id": run_id,
            "status": "delivered",
            "approval_id": approval.approval_id,
            "approval_kind": "human",
            "preview_digest": state.prepared_preview_digest,
            "store_event_chain_verified": True,
            "campaign_ledger_verified_before_redaction": True,
            "source_campaign_ledger_sha256": hashlib.sha256(
                campaign_ledger.read_bytes()
            ).hexdigest(),
            "bundled_campaign_ledger_is_redacted_view": True,
            "external_release_executed": False,
            "strategy_artifacts_are_drafts": True,
            "gtm_artifact_set_sha256": approved_gtm_artifact_set_sha256,
            "effect_promotion_passed": False,
            "revenue_positive_feedback_observation_count": (
                revenue_economics_collection[
                    "positive_feedback_observation_count"
                ]
            ),
            "causal_revenue_claim_allowed": False,
            "effect_readiness_sha256": hashlib.sha256(effect_readiness).hexdigest(),
            "strategy_artifact_sha256": {
                name: hashlib.sha256(strategy_documents[name]).hexdigest()
                for name in _STRATEGY_ARTIFACT_NAMES
            },
            "members": [
                {
                    "name": name,
                    "bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
                for name, payload in sorted(members.items())
            ],
            "truth_boundary": (
                "This bundle proves the local deterministic Agent execution, content-"
                "bound human approval and artifact integrity. It does not prove Radeon "
                "model inference, external publication, causal lift or revenue. The GTM "
                "strategy files remain owner-attested drafts and are not independently "
                "verified results."
            ),
        }
        members["bundle-manifest.json"] = self._pretty_json(manifest)
        output = io.BytesIO()
        with zipfile.ZipFile(
            output,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as archive:
            for name, payload in sorted(members.items()):
                info = zipfile.ZipInfo(name, date_time=(2026, 8, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                archive.writestr(info, payload)
        bundle = state.output_path / "production-bundle.zip"
        atomic_write_bytes(bundle, output.getvalue())
        return bundle

    @staticmethod
    def _pretty_json(payload: Mapping[str, Any]) -> bytes:
        return _pretty_json_bytes(payload)

    def _validated_strategy_documents(
        self,
        run,
        state: CampaignState,
    ) -> dict[str, bytes]:
        launch = ProductionLaunchRequest(**dict(run.request))
        expected = _strategy_documents(
            launch,
            run_id=run.run_id,
            compiled_at=run.created_at,
            signal_intelligence=_signal_intelligence_document(self.store, launch),
            learning_context=_learning_context_document(self.store, launch),
            strategy_memory_resolution_context=(
                _strategy_memory_resolution_context_document(self.store, launch)
            ),
        )
        observed: dict[str, bytes] = {}
        for name in _STRATEGY_ARTIFACT_NAMES:
            candidate = state.output_path / name
            if candidate.is_symlink() or not candidate.is_file():
                raise ProductionRuntimeError(f"strategy artifact is missing: {name}")
            payload = candidate.read_bytes()
            if payload != expected[name]:
                raise ProductionRuntimeError(
                    f"strategy artifact integrity failed: {name}"
                )
            observed[name] = payload
        return observed

    def _public_campaign_state(
        self,
        state: CampaignState,
        run,
    ) -> dict[str, Any]:
        payload = state.serializable()
        payload["output_dir"] = "campaign/"
        payload["request"]["product_image"] = (
            f"cas://sha256/{run.request['product_image_sha256']}"
        )
        return self._redact_paths(payload, state.output_path)

    def _public_campaign_ledger(
        self,
        ledger_path: Path,
        state: CampaignState,
    ) -> bytes:
        rows = []
        for line in ledger_path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            source_event_hash = row.pop("event_hash")
            source_previous_hash = row.pop("previous_hash")
            public = self._redact_paths(row, state.output_path)
            public["source_event_hash"] = source_event_hash
            public["source_previous_hash"] = source_previous_hash
            public["redacted_view"] = True
            rows.append(canonical_json(public))
        return ("\n".join(rows) + "\n").encode("utf-8")

    def _redact_paths(self, value: Any, output_root: Path) -> Any:
        if isinstance(value, Mapping):
            return {str(key): self._redact_paths(item, output_root) for key, item in value.items()}
        if isinstance(value, list):
            return [self._redact_paths(item, output_root) for item in value]
        if isinstance(value, tuple):
            return [self._redact_paths(item, output_root) for item in value]
        if not isinstance(value, str):
            return value
        candidate = Path(value)
        if not candidate.is_absolute():
            return value
        try:
            relative = candidate.resolve(strict=False).relative_to(output_root.resolve())
            return f"campaign/{relative.as_posix()}"
        except ValueError:
            pass
        try:
            relative = candidate.resolve(strict=False).relative_to(self.store.root)
            if "cas" in relative.parts:
                return "server-private://content-addressed-input"
            return f"server-private://{relative.as_posix()}"
        except ValueError:
            return "redacted://absolute-path"


__all__ = [
    "AgencyRunWorker",
    "ProcessResult",
    "ProductionAgencyService",
    "ProductionLaunchRequest",
    "ProductionRuntimeError",
]
