from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from typing import Mapping


class StrategyContractError(ValueError):
    """Raised when a strategy cannot be compiled without inventing evidence."""


class BusinessModel(str, Enum):
    B2B = "b2b"
    B2C = "b2c"


class LifecycleStage(str, Enum):
    PRE_PMF = "pre_pmf"
    LAUNCH = "launch"
    GROWTH = "growth"
    MATURE = "mature"


class BudgetTier(str, Enum):
    ZERO = "zero"
    SMALL = "small"
    SCALED = "scaled"


class IndustryRisk(str, Enum):
    STANDARD = "standard"
    HIGH_REGULATION = "high_regulation"


class CompanyScale(str, Enum):
    SOLO = "solo"
    STARTUP = "startup"
    SCALEUP = "scaleup"
    ENTERPRISE = "enterprise"


class DistributionStrength(str, Enum):
    NONE = "none"
    EMERGING = "emerging"
    ESTABLISHED = "established"
    STRONG = "strong"


class ContentCapacity(str, Enum):
    LEAN = "lean"
    STANDARD = "standard"
    STUDIO = "studio"


class SalesMotion(str, Enum):
    SELF_SERVE = "self_serve"
    SALES_LED = "sales_led"
    HYBRID = "hybrid"


class ProductSurface(str, Enum):
    WEB_APP = "web_app"
    MOBILE_APP = "mobile_app"
    WEB_AGENT = "web_agent"
    DESKTOP_APP = "desktop_app"
    API = "api"
    PHYSICAL_PRODUCT = "physical_product"
    SERVICE = "service"
    HYBRID = "hybrid"


class EvidenceRights(str, Enum):
    OWNED = "owned"
    LICENSED = "licensed"
    PUBLIC_PERMISSION = "public_permission"
    RESTRICTED = "restricted"


class Channel(str, Enum):
    COMMUNITY_LISTENING = "community_listening"
    CREATOR_COMMUNITY = "creator_community"
    CUSTOMER_EVIDENCE = "customer_evidence"
    CUSTOMER_EMAIL = "customer_email"
    FOUNDER_CONVERSATIONS = "founder_conversations"
    LINKEDIN_ORGANIC = "linkedin_organic"
    OWNED_SOCIAL = "owned_social"
    PARTNER_COMMUNITIES = "partner_communities"
    SEARCH_EDUCATION = "search_education"
    SHORT_VIDEO_ORGANIC = "short_video_organic"
    PAID_SEARCH = "paid_search"
    PAID_SOCIAL = "paid_social"

    @property
    def paid(self) -> bool:
        return self in {Channel.PAID_SEARCH, Channel.PAID_SOCIAL}


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_UNSUPPORTED_OUTCOME_LANGUAGE = (
    "guaranteed",
    "guarantee",
    "will go viral",
    "will drive revenue",
    "revenue guaranteed",
    "guaranteed roi",
    "保证爆款",
    "必然爆款",
    "保证营收",
    "必然营收",
)


def _parse_time(value: str, *, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise StrategyContractError(f"{field_name} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise StrategyContractError(f"{field_name} must include a timezone")
    return parsed


def _required(value: str, *, field_name: str) -> None:
    if not value or not value.strip():
        raise StrategyContractError(f"{field_name} is required")


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return normalized[:64] or "campaign"


def _action_clause(value: str) -> str:
    """Turn an operator objective into a grammatical CTA action clause.

    Objectives are user-authored and frequently arrive with terminal punctuation
    or sentence case.  The strategy may preserve their meaning, but it must not
    produce doubled punctuation or constructions such as ``whether to Earn``.
    Acronyms such as ROI remain untouched.
    """

    clause = re.sub(r"[.!?。！？]+$", "", value.strip())
    if len(clause) >= 2 and clause[0].isupper() and clause[1].islower():
        clause = clause[0].lower() + clause[1:]
    return clause


def _cta_action_clause(objective: str, offer: str) -> str:
    objective_clause = _action_clause(objective)
    if len(objective_clause) <= 96:
        return objective_clause
    offer_clause = _action_clause(offer)
    tail = re.split(r"\s+and\s+", offer_clause)[-1].strip()
    if (
        len(tail) <= 80
        and re.match(
            r"^(?:apply|book|choose|download|join|open|register|request|reserve|schedule|share|start|subscribe|try)\b",
            tail,
            re.IGNORECASE,
        )
    ):
        return tail
    if len(offer_clause) <= 96:
        return offer_clause
    return "take the next evidence-backed step"


@dataclass(frozen=True)
class BrandConstitution:
    brand_name: str
    purpose: str
    customer_promise: str
    voice_principles: tuple[str, ...]
    prohibited_tactics: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name, value in (
            ("brand_name", self.brand_name),
            ("purpose", self.purpose),
            ("customer_promise", self.customer_promise),
        ):
            _required(value, field_name=field_name)
        if not self.voice_principles or any(
            not item.strip() for item in self.voice_principles
        ):
            raise StrategyContractError("voice_principles must be explicit")


@dataclass(frozen=True)
class AudienceICP:
    audience_id: str
    name: str
    business_model: BusinessModel
    core_problem: str
    desired_outcome: str
    buying_context: str

    def __post_init__(self) -> None:
        for field_name, value in (
            ("audience_id", self.audience_id),
            ("name", self.name),
            ("core_problem", self.core_problem),
            ("desired_outcome", self.desired_outcome),
            ("buying_context", self.buying_context),
        ):
            _required(value, field_name=field_name)


@dataclass(frozen=True)
class ClaimEvidence:
    claim_id: str
    text: str
    evidence_uri: str
    evidence_sha256: str
    rights: EvidenceRights
    rights_reference: str
    valid_from: str
    valid_until: str | None
    approved_by: str | None
    specialist_approved_by: str | None = None
    claim_type: str = "feature"
    assurance_status: str = "owner_attested"
    release_scope: str = "draft_only"

    def __post_init__(self) -> None:
        for field_name, value in (
            ("claim_id", self.claim_id),
            ("text", self.text),
            ("evidence_uri", self.evidence_uri),
        ):
            _required(value, field_name=field_name)
        if not _SHA256.fullmatch(self.evidence_sha256):
            raise StrategyContractError(
                "evidence_sha256 must be a lowercase SHA-256 digest"
            )
        if self.rights in {
            EvidenceRights.LICENSED,
            EvidenceRights.PUBLIC_PERMISSION,
        }:
            _required(self.rights_reference, field_name="rights_reference")
        if self.claim_type not in {
            "feature",
            "performance",
            "customer_result",
            "operational_capability",
        }:
            raise StrategyContractError("claim_type is unsupported")
        if self.assurance_status not in {"owner_attested", "verified"}:
            raise StrategyContractError("assurance_status is unsupported")
        _required(self.release_scope, field_name="release_scope")
        starts = _parse_time(self.valid_from, field_name="valid_from")
        if self.valid_until is not None:
            ends = _parse_time(self.valid_until, field_name="valid_until")
            if ends <= starts:
                raise StrategyContractError("valid_until must follow valid_from")

    def blockers(self, *, at: str, risk: IndustryRisk) -> tuple[str, ...]:
        now = _parse_time(at, field_name="at")
        starts = _parse_time(self.valid_from, field_name="valid_from")
        reasons: list[str] = []
        if now < starts:
            reasons.append("evidence_not_yet_valid")
        if self.valid_until is not None and now >= _parse_time(
            self.valid_until, field_name="valid_until"
        ):
            reasons.append("evidence_expired")
        if self.rights == EvidenceRights.RESTRICTED:
            reasons.append("evidence_rights_restricted")
        if not self.approved_by or not self.approved_by.strip():
            reasons.append("claim_not_approved")
        if risk == IndustryRisk.HIGH_REGULATION and (
            not self.specialist_approved_by
            or not self.specialist_approved_by.strip()
        ):
            reasons.append("specialist_approval_required")
        lowered = self.text.casefold()
        if any(term in lowered for term in _UNSUPPORTED_OUTCOME_LANGUAGE):
            reasons.append("unsupported_outcome_guarantee")
        return tuple(reasons)


@dataclass(frozen=True)
class CampaignStrategyInput:
    org_id: str
    project_id: str
    campaign_id: str
    owner: str
    industry: str
    lifecycle: LifecycleStage
    budget: BudgetTier
    industry_risk: IndustryRisk
    brand: BrandConstitution
    audience: AudienceICP
    objective: str
    offer: str
    landing_url: str
    claims: tuple[ClaimEvidence, ...]
    company_scale: CompanyScale = CompanyScale.STARTUP
    brand_reach: DistributionStrength = DistributionStrength.EMERGING
    owned_audience_strength: DistributionStrength = DistributionStrength.EMERGING
    community_access: DistributionStrength = DistributionStrength.EMERGING
    partner_access: DistributionStrength = DistributionStrength.EMERGING
    content_capacity: ContentCapacity = ContentCapacity.STANDARD
    sales_motion: SalesMotion = SalesMotion.HYBRID
    product_category: str = "owner_category_unspecified"
    product_surface: ProductSurface = ProductSurface.WEB_APP
    distribution_platform: str = "owner_platform_unspecified"
    audience_role: str = "owner_role_unspecified"
    schedule_timezone: str = "UTC"

    def __post_init__(self) -> None:
        for field_name, value in (
            ("org_id", self.org_id),
            ("project_id", self.project_id),
            ("campaign_id", self.campaign_id),
            ("owner", self.owner),
            ("industry", self.industry),
            ("objective", self.objective),
            ("offer", self.offer),
            ("landing_url", self.landing_url),
            ("product_category", self.product_category),
            ("distribution_platform", self.distribution_platform),
            ("audience_role", self.audience_role),
            ("schedule_timezone", self.schedule_timezone),
        ):
            _required(value, field_name=field_name)
        if not self.landing_url.startswith(("https://", "http://")):
            raise StrategyContractError("landing_url must be HTTP(S)")
        if not self.claims:
            raise StrategyContractError("at least one evidenced claim is required")
        claim_ids = [claim.claim_id for claim in self.claims]
        if len(claim_ids) != len(set(claim_ids)):
            raise StrategyContractError("claim_id values must be unique")


@dataclass(frozen=True)
class ChannelConstraint:
    channel: Channel
    allowed_actions: tuple[str, ...]
    prohibited_actions: tuple[str, ...]
    human_release_required: bool = True
    automated_publish_allowed: bool = False


@dataclass(frozen=True)
class DailyContentTheme:
    day: int
    theme: str
    channel: Channel
    intended_learning: str
    release_mode: str = "human_review_then_manual_publish"


@dataclass(frozen=True)
class AttributionPlan:
    experiment_id: str
    utm_source: str
    utm_medium: str
    utm_campaign: str
    utm_content: str
    interpretation: str = "observational attribution; not a causal revenue claim"


@dataclass(frozen=True)
class MetricRegistration:
    metric: str
    direction: str
    measurement_window_days: int
    minimum_sample: int
    pre_registered_before_launch: bool = True


@dataclass(frozen=True)
class GrowthTension:
    """The one stage-defining conflict every downstream asset must inherit."""

    tension_id: str
    audience: str
    problem: str
    business_constraint: str
    evidence_ids: tuple[str, ...]
    falsifier: str
    primary_outcome_metric: str

    def __post_init__(self) -> None:
        for field_name, value in (
            ("tension_id", self.tension_id),
            ("audience", self.audience),
            ("problem", self.problem),
            ("business_constraint", self.business_constraint),
            ("falsifier", self.falsifier),
            ("primary_outcome_metric", self.primary_outcome_metric),
        ):
            _required(value, field_name=field_name)
        if not self.evidence_ids or any(not item.strip() for item in self.evidence_ids):
            raise StrategyContractError("growth tension requires evidence IDs")
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise StrategyContractError("growth tension evidence IDs must be unique")


@dataclass(frozen=True)
class GTMStrategy:
    strategy_id: str
    primary_channel: Channel
    secondary_channel: Channel
    hero_hypothesis: str
    proof: str
    proof_claim_id: str
    proof_evidence_uri: str
    proof_evidence_sha256: str
    objection: str
    call_to_action: str
    seven_day_content: tuple[DailyContentTheme, ...]
    channel_constraints: tuple[ChannelConstraint, ...]
    seo_geo_question_intents: tuple[str, ...]
    attribution: AttributionPlan
    metrics: tuple[MetricRegistration, ...]
    growth_tensions: tuple[GrowthTension, ...]
    stop_rules: tuple[str, ...]
    rights_and_safety_notes: tuple[str, ...]
    causal_outcome_claim_allowed: bool = False

    def __post_init__(self) -> None:
        if self.primary_channel == self.secondary_channel:
            raise StrategyContractError("primary and secondary channels must differ")
        if len(self.seven_day_content) != 7:
            raise StrategyContractError("strategy requires exactly seven content days")
        if tuple(item.day for item in self.seven_day_content) != tuple(range(1, 8)):
            raise StrategyContractError("content days must be contiguous from 1 to 7")
        if any(item.automated_publish_allowed for item in self.channel_constraints):
            raise StrategyContractError("automated publishing is outside this contract")
        if self.causal_outcome_claim_allowed:
            raise StrategyContractError("strategy cannot pre-claim causal outcomes")
        if len(self.growth_tensions) != 1:
            raise StrategyContractError("strategy requires exactly one growth tension")
        primary_metrics = {item.metric for item in self.metrics}
        if self.growth_tensions[0].primary_outcome_metric not in primary_metrics:
            raise StrategyContractError(
                "growth tension primary metric must be pre-registered"
            )


_ORGANIC_CHANNELS: dict[tuple[BusinessModel, LifecycleStage], tuple[Channel, Channel]] = {
    (BusinessModel.B2B, LifecycleStage.PRE_PMF): (
        Channel.FOUNDER_CONVERSATIONS,
        Channel.COMMUNITY_LISTENING,
    ),
    (BusinessModel.B2B, LifecycleStage.LAUNCH): (
        Channel.LINKEDIN_ORGANIC,
        Channel.PARTNER_COMMUNITIES,
    ),
    (BusinessModel.B2B, LifecycleStage.GROWTH): (
        Channel.SEARCH_EDUCATION,
        Channel.CUSTOMER_EVIDENCE,
    ),
    (BusinessModel.B2B, LifecycleStage.MATURE): (
        Channel.CUSTOMER_EVIDENCE,
        Channel.CUSTOMER_EMAIL,
    ),
    (BusinessModel.B2C, LifecycleStage.PRE_PMF): (
        Channel.COMMUNITY_LISTENING,
        Channel.OWNED_SOCIAL,
    ),
    (BusinessModel.B2C, LifecycleStage.LAUNCH): (
        Channel.SHORT_VIDEO_ORGANIC,
        Channel.CREATOR_COMMUNITY,
    ),
    (BusinessModel.B2C, LifecycleStage.GROWTH): (
        Channel.SEARCH_EDUCATION,
        Channel.SHORT_VIDEO_ORGANIC,
    ),
    (BusinessModel.B2C, LifecycleStage.MATURE): (
        Channel.CUSTOMER_EVIDENCE,
        Channel.OWNED_SOCIAL,
    ),
}


_SIGNAL_CHANNELS: dict[str, tuple[Channel, ...]] = {
    "youtube": (Channel.SHORT_VIDEO_ORGANIC, Channel.SEARCH_EDUCATION),
    "vimeo": (Channel.SHORT_VIDEO_ORGANIC,),
    "tiktok": (Channel.SHORT_VIDEO_ORGANIC, Channel.CREATOR_COMMUNITY),
    "instagram": (Channel.OWNED_SOCIAL, Channel.CREATOR_COMMUNITY),
    "facebook": (Channel.OWNED_SOCIAL, Channel.CUSTOMER_EVIDENCE),
    "threads": (Channel.OWNED_SOCIAL, Channel.COMMUNITY_LISTENING),
    "x": (Channel.OWNED_SOCIAL, Channel.COMMUNITY_LISTENING),
    "twitter": (Channel.OWNED_SOCIAL, Channel.COMMUNITY_LISTENING),
    "bluesky": (Channel.OWNED_SOCIAL, Channel.COMMUNITY_LISTENING),
    "linkedin": (Channel.LINKEDIN_ORGANIC, Channel.CUSTOMER_EVIDENCE),
    "reddit": (Channel.COMMUNITY_LISTENING, Channel.SEARCH_EDUCATION),
    "discord": (Channel.COMMUNITY_LISTENING, Channel.PARTNER_COMMUNITIES),
    "slack": (Channel.PARTNER_COMMUNITIES, Channel.COMMUNITY_LISTENING),
    "google": (Channel.SEARCH_EDUCATION,),
    "bing": (Channel.SEARCH_EDUCATION,),
    "search": (Channel.SEARCH_EDUCATION,),
}


def score_channel_opportunities(
    request: CampaignStrategyInput,
    *,
    signal_platform_counts: Mapping[str, int] | None = None,
) -> dict[Channel, tuple[int, tuple[str, ...]]]:
    """Score the next channel focus from durable distribution advantages.

    This is a deterministic decision surface, not a forecast. It combines the
    frozen business/lifecycle prior with assets the company can actually deploy:
    owned reach, community and partner access, content capacity, sales motion,
    and bounded aggregate platform signals. No score authorizes activation.
    """

    organic_primary, organic_secondary = _ORGANIC_CHANNELS[
        (request.audience.business_model, request.lifecycle)
    ]
    base = {channel: 30 for channel in Channel}
    base[organic_primary] = 76
    base[organic_secondary] = 68
    preferred_paid = (
        Channel.PAID_SEARCH
        if request.audience.business_model is BusinessModel.B2B
        else Channel.PAID_SOCIAL
    )
    if request.budget is BudgetTier.SCALED:
        base[preferred_paid] = 82
    elif request.budget is BudgetTier.SMALL:
        base[preferred_paid] = 24

    components: dict[Channel, list[tuple[str, int]]] = {
        channel: [("business_lifecycle_prior", base[channel])] for channel in Channel
    }

    def add(channels: tuple[Channel, ...], code: str, value: int) -> None:
        for channel in channels:
            components[channel].append((code, value))

    if request.company_scale is CompanyScale.SOLO:
        add((Channel.FOUNDER_CONVERSATIONS,), "company_scale_solo", 16)
        add((Channel.SEARCH_EDUCATION, Channel.COMMUNITY_LISTENING), "company_scale_solo", 7)
        add((Channel.CUSTOMER_EMAIL, Channel.PARTNER_COMMUNITIES), "company_scale_solo", -8)
    elif request.company_scale is CompanyScale.SCALEUP:
        add((Channel.CUSTOMER_EVIDENCE, Channel.SEARCH_EDUCATION), "company_scale_scaleup", 10)
        add((Channel.PARTNER_COMMUNITIES, Channel.CUSTOMER_EMAIL), "company_scale_scaleup", 6)
    elif request.company_scale is CompanyScale.ENTERPRISE:
        add((Channel.CUSTOMER_EVIDENCE,), "company_scale_enterprise", 18)
        add((Channel.CUSTOMER_EMAIL,), "company_scale_enterprise", 14)
        add((Channel.PARTNER_COMMUNITIES,), "company_scale_enterprise", 10)
        add((Channel.FOUNDER_CONVERSATIONS,), "company_scale_enterprise", -12)

    if request.brand_reach is DistributionStrength.NONE:
        add((Channel.COMMUNITY_LISTENING, Channel.SEARCH_EDUCATION), "brand_reach_none", 8)
        add((Channel.OWNED_SOCIAL, Channel.CUSTOMER_EMAIL), "brand_reach_none", -12)
    elif request.brand_reach is DistributionStrength.ESTABLISHED:
        add((Channel.OWNED_SOCIAL, Channel.CUSTOMER_EVIDENCE), "brand_reach_established", 10)
        add((Channel.CUSTOMER_EMAIL,), "brand_reach_established", 6)
    elif request.brand_reach is DistributionStrength.STRONG:
        add((Channel.OWNED_SOCIAL,), "brand_reach_strong", 18)
        add((Channel.CUSTOMER_EVIDENCE,), "brand_reach_strong", 12)
        add((Channel.CUSTOMER_EMAIL, Channel.PARTNER_COMMUNITIES), "brand_reach_strong", 10)

    if request.owned_audience_strength is DistributionStrength.NONE:
        add((Channel.SEARCH_EDUCATION, Channel.COMMUNITY_LISTENING), "owned_audience_none", 8)
        add((Channel.CUSTOMER_EMAIL, Channel.OWNED_SOCIAL), "owned_audience_none", -14)
    elif request.owned_audience_strength is DistributionStrength.ESTABLISHED:
        add((Channel.CUSTOMER_EMAIL, Channel.OWNED_SOCIAL), "owned_audience_established", 12)
        add((Channel.CUSTOMER_EVIDENCE,), "owned_audience_established", 6)
    elif request.owned_audience_strength is DistributionStrength.STRONG:
        add((Channel.CUSTOMER_EMAIL, Channel.OWNED_SOCIAL), "owned_audience_strong", 20)
        add((Channel.CUSTOMER_EVIDENCE,), "owned_audience_strong", 10)

    if request.community_access is DistributionStrength.NONE:
        add((Channel.COMMUNITY_LISTENING, Channel.CREATOR_COMMUNITY), "community_access_none", -12)
    elif request.community_access is DistributionStrength.ESTABLISHED:
        add((Channel.COMMUNITY_LISTENING, Channel.CREATOR_COMMUNITY), "community_access_established", 12)
        add((Channel.PARTNER_COMMUNITIES,), "community_access_established", 6)
    elif request.community_access is DistributionStrength.STRONG:
        add((Channel.COMMUNITY_LISTENING, Channel.CREATOR_COMMUNITY), "community_access_strong", 20)
        add((Channel.PARTNER_COMMUNITIES,), "community_access_strong", 12)

    if request.partner_access is DistributionStrength.NONE:
        add((Channel.PARTNER_COMMUNITIES,), "partner_access_none", -16)
    elif request.partner_access is DistributionStrength.ESTABLISHED:
        add((Channel.PARTNER_COMMUNITIES,), "partner_access_established", 14)
    elif request.partner_access is DistributionStrength.STRONG:
        add((Channel.PARTNER_COMMUNITIES,), "partner_access_strong", 24)
        add((Channel.CUSTOMER_EVIDENCE,), "partner_access_strong", 6)

    if request.content_capacity is ContentCapacity.LEAN:
        add((Channel.SEARCH_EDUCATION, Channel.FOUNDER_CONVERSATIONS, Channel.CUSTOMER_EMAIL), "content_capacity_lean", 7)
        add((Channel.SHORT_VIDEO_ORGANIC, Channel.OWNED_SOCIAL), "content_capacity_lean", -12)
    elif request.content_capacity is ContentCapacity.STUDIO:
        add((Channel.SHORT_VIDEO_ORGANIC,), "content_capacity_studio", 18)
        add((Channel.OWNED_SOCIAL,), "content_capacity_studio", 12)
        add((Channel.CREATOR_COMMUNITY,), "content_capacity_studio", 10)

    if request.sales_motion is SalesMotion.SELF_SERVE:
        add((Channel.SEARCH_EDUCATION, Channel.SHORT_VIDEO_ORGANIC), "sales_motion_self_serve", 12)
        add((Channel.OWNED_SOCIAL,), "sales_motion_self_serve", 8)
    elif request.sales_motion is SalesMotion.SALES_LED:
        add((Channel.LINKEDIN_ORGANIC,), "sales_motion_sales_led", 14)
        add((Channel.FOUNDER_CONVERSATIONS,), "sales_motion_sales_led", 12)
        add((Channel.PARTNER_COMMUNITIES,), "sales_motion_sales_led", 10)
        add((Channel.CUSTOMER_EVIDENCE,), "sales_motion_sales_led", 8)

    counts = _normalized_signal_platform_counts(signal_platform_counts)
    signal_total = sum(counts.values())
    if signal_total:
        allocations = {channel: 0.0 for channel in Channel}
        for platform, count in counts.items():
            matched: set[Channel] = set()
            for token, channels in _SIGNAL_CHANNELS.items():
                if token in platform:
                    matched.update(channels)
            for channel in matched:
                allocations[channel] += count / signal_total / max(1, len(matched))
        for channel, share in allocations.items():
            boost = min(40, round(80 * share))
            if boost:
                components[channel].append(("authorized_platform_signal_fit", boost))

    scored: dict[Channel, tuple[int, tuple[str, ...]]] = {}
    for channel, values in components.items():
        if request.budget is BudgetTier.ZERO and channel.paid:
            scored[channel] = (0, ("zero_budget_paid_channel_hard_exclusion",))
            continue
        total = max(0, min(100, sum(value for _, value in values)))
        reasons = tuple(f"{code}:{value:+d}" for code, value in values)
        scored[channel] = (total, reasons)
    return scored


def rank_channel_opportunities(
    request: CampaignStrategyInput,
    *,
    signal_platform_counts: Mapping[str, int] | None = None,
) -> tuple[Channel, ...]:
    scores = score_channel_opportunities(
        request, signal_platform_counts=signal_platform_counts
    )
    return tuple(
        sorted(Channel, key=lambda channel: (-scores[channel][0], channel.value))
    )


def _normalized_signal_platform_counts(
    signal_platform_counts: Mapping[str, int] | None,
) -> dict[str, int]:
    return {
        str(platform).strip().casefold(): int(count)
        for platform, count in (signal_platform_counts or {}).items()
        if str(platform).strip() and type(count) is int and count > 0
    }


class StrategyCompiler:
    """Deterministic strategy compiler for an evidence-bound seven-day GTM loop.

    It selects channels and experiments; it does not publish, buy media, send
    bulk outreach, or assert that an experiment caused revenue.
    """

    def compile(
        self,
        request: CampaignStrategyInput,
        *,
        at: str,
        signal_platform_counts: Mapping[str, int] | None = None,
    ) -> GTMStrategy:
        _parse_time(at, field_name="at")
        ungrounded_fields = {
            "customer_promise": request.brand.customer_promise,
            "objective": request.objective,
            "offer": request.offer,
        }
        for field_name, value in ungrounded_fields.items():
            lowered = value.casefold()
            if any(term in lowered for term in _UNSUPPORTED_OUTCOME_LANGUAGE):
                raise StrategyContractError(
                    f"{field_name} contains an unsupported outcome guarantee"
                )
        blocked: dict[str, tuple[str, ...]] = {}
        for claim in request.claims:
            reasons = claim.blockers(at=at, risk=request.industry_risk)
            if reasons:
                blocked[claim.claim_id] = reasons
        if blocked:
            detail = "; ".join(
                f"{claim_id}:{','.join(reasons)}"
                for claim_id, reasons in sorted(blocked.items())
            )
            raise StrategyContractError(f"claim safety gate failed: {detail}")

        primary, secondary = self._channels(
            request, signal_platform_counts=signal_platform_counts
        )
        proof_claim = sorted(request.claims, key=lambda item: item.claim_id)[0]
        # All strategy-relevant inputs participate in identity. Replacing the
        # evidence under an unchanged claim ID therefore creates a new
        # experiment instead of silently reusing attribution.
        identity: object = asdict(request)
        normalized_signal_counts = _normalized_signal_platform_counts(
            signal_platform_counts
        )
        if normalized_signal_counts:
            identity = {
                "request": identity,
                "authorized_platform_signal_counts": dict(
                    sorted(normalized_signal_counts.items())
                ),
            }
        digest = hashlib.sha256(
            json.dumps(identity, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()
        strategy_id = f"strategy-{digest[:16]}"
        experiment_id = f"exp-{digest[16:32]}"

        hero = (
            f"Hypothesis: {request.brand.brand_name} can help {request.audience.name} pursue "
            f"this outcome—{request.audience.desired_outcome.rstrip('?. ')}—while addressing "
            f"this problem—{request.audience.core_problem.rstrip('?. ')}. Test that premise through "
            f"this next step—{request.offer.rstrip('?. ')}—before scaling."
        )
        content = self._content(request, primary, secondary, proof_claim)
        constraints = tuple(
            self._constraint(
                channel,
                zero_budget=request.budget == BudgetTier.ZERO,
                brand_prohibited=request.brand.prohibited_tactics,
            )
            for channel in (primary, secondary)
        )
        minimum_sample = 25 if request.budget == BudgetTier.ZERO else 100
        metrics = (
            MetricRegistration("qualified_action_rate", "increase", 7, minimum_sample),
            MetricRegistration("evidence_engagement_rate", "increase", 7, minimum_sample),
            MetricRegistration("unsubscribe_or_complaint_rate", "not_increase", 7, 1),
        )
        if request.budget is BudgetTier.ZERO:
            business_constraint = (
                "No paid media: earn qualified action through product utility, evidence, "
                "founder expertise, communities or partners."
            )
        elif request.lifecycle is LifecycleStage.PRE_PMF:
            business_constraint = (
                "Do not scale distribution before one painful problem and reachable audience "
                "are supported by observed behavior."
            )
        elif request.lifecycle is LifecycleStage.MATURE:
            business_constraint = (
                "Increase qualified action without weakening brand trust, margin or retention."
            )
        else:
            business_constraint = (
                "Spend only behind a manually approved signal after the organic evidence spine "
                "and measurement contract are frozen."
            )
        growth_tension = GrowthTension(
            tension_id=f"tension-{digest[32:48]}",
            audience=request.audience.name,
            problem=request.audience.core_problem,
            business_constraint=business_constraint,
            evidence_ids=tuple(sorted(claim.claim_id for claim in request.claims)),
            falsifier=(
                f"At the pre-registered sample floor of {minimum_sample}, qualified_action_rate "
                "does not improve against a frozen same-channel baseline, or no valid baseline "
                "can be produced."
            ),
            primary_outcome_metric="qualified_action_rate",
        )
        stop_rules = [
            "stop immediately on a rights, privacy, safety, or channel-policy breach",
            "stop the losing variant after the pre-registered window; do not cherry-pick",
            "stop after two failed repair cycles and require a named human decision",
            "do not infer revenue causality from UTM attribution alone",
        ]
        if request.industry_risk == IndustryRisk.HIGH_REGULATION:
            stop_rules.append(
                "stop immediately if specialist approval expires or the approved wording changes"
            )

        notes = [
            "only owner-approved, rights-cleared, currently valid claims may ship",
            "all outputs remain drafts until named human release",
            "viral reach and revenue are outcomes to measure, never guarantees",
        ]
        if request.budget == BudgetTier.ZERO:
            notes.append(
                "zero-budget mode prohibits paid media, spam, and automated publishing"
            )

        return GTMStrategy(
            strategy_id=strategy_id,
            primary_channel=primary,
            secondary_channel=secondary,
            hero_hypothesis=hero,
            proof=proof_claim.text,
            proof_claim_id=proof_claim.claim_id,
            proof_evidence_uri=proof_claim.evidence_uri,
            proof_evidence_sha256=proof_claim.evidence_sha256,
            objection=(
                f"What would {request.audience.name} need to inspect before trusting this path?"
            ),
            call_to_action=(
                "Review the evidence, then decide whether to "
                f"{_cta_action_clause(request.objective, request.offer)}."
            ),
            seven_day_content=content,
            channel_constraints=constraints,
            seo_geo_question_intents=self._question_intents(request),
            attribution=AttributionPlan(
                experiment_id=experiment_id,
                utm_source=primary.value,
                utm_medium="paid" if primary.paid else "organic",
                utm_campaign=_slug(request.campaign_id),
                utm_content=f"hero-{digest[:8]}",
            ),
            metrics=metrics,
            growth_tensions=(growth_tension,),
            stop_rules=tuple(stop_rules),
            rights_and_safety_notes=tuple(notes),
        )

    @staticmethod
    def _channels(
        request: CampaignStrategyInput,
        *,
        signal_platform_counts: Mapping[str, int] | None = None,
    ) -> tuple[Channel, Channel]:
        ranked = rank_channel_opportunities(
            request, signal_platform_counts=signal_platform_counts
        )
        eligible = tuple(
            channel
            for channel in ranked
            if not (request.budget is BudgetTier.ZERO and channel.paid)
        )
        if len(eligible) < 2:
            raise StrategyContractError("channel decision produced fewer than two routes")
        return eligible[0], eligible[1]

    @staticmethod
    def _constraint(
        channel: Channel,
        *,
        zero_budget: bool,
        brand_prohibited: tuple[str, ...],
    ) -> ChannelConstraint:
        prohibited = [
            "spam",
            "bulk_unsolicited_outreach",
            "automated_publish",
            "policy_bypass",
        ]
        if zero_budget:
            prohibited.extend(("paid_placement", "media_spend"))
        prohibited.extend(item.strip() for item in brand_prohibited if item.strip())
        return ChannelConstraint(
            channel=channel,
            allowed_actions=("research", "draft", "review", "manual_publish"),
            prohibited_actions=tuple(dict.fromkeys(prohibited)),
        )

    @staticmethod
    def _content(
        request: CampaignStrategyInput,
        primary: Channel,
        secondary: Channel,
        proof: ClaimEvidence,
    ) -> tuple[DailyContentTheme, ...]:
        themes = (
            ("audience problem signal", "which problem language earns qualified response"),
            ("evidence card", f"whether evidence {proof.claim_id} resolves trust friction"),
            ("category misconception", "which objection prevents the next step"),
            ("behind-the-proof explanation", "which proof detail earns deeper engagement"),
            ("audience question answer", "which search question indicates intent"),
            ("human story without outcome inflation", "which context makes the proof relevant"),
            ("weekly evidence recap and decision", "whether to stop, repair, or continue"),
        )
        return tuple(
            DailyContentTheme(
                day=index,
                theme=theme,
                channel=primary if index % 2 else secondary,
                intended_learning=learning,
            )
            for index, (theme, learning) in enumerate(themes, start=1)
        )

    @staticmethod
    def _question_intents(request: CampaignStrategyInput) -> tuple[str, ...]:
        audience = request.audience.name
        problem = request.audience.core_problem.rstrip("?. ")
        offer = request.offer.rstrip("?. ")
        brand = request.brand.brand_name
        return (
            f"How can {audience} address this problem: {problem}?",
            f"What evidence should {audience} inspect before taking this next step: {offer}?",
            f"How does {brand} support its customer promise?",
            f"When should {audience} avoid or defer this offer?",
        )


def strategy_digest(strategy: GTMStrategy) -> str:
    """Return a stable digest suitable for receipts and memory provenance."""

    return hashlib.sha256(
        json.dumps(
            asdict(strategy),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
