from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum
from typing import Any, Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .gtm_channel_portfolio import (
    ChannelPortfolioError,
    compile_channel_portfolio,
    verify_channel_portfolio,
)
from .gtm_breakout_loop import (
    BreakoutLoopError,
    compile_breakout_growth_loop,
    verify_breakout_growth_loop,
)
from .gtm_text_challenger import (
    TextChallengerError,
    build_text_challenger_plan,
    verify_text_challenger_plan,
)
from .gtm_industry_profile import (
    IndustryProfileError,
    bind_industry_profile_strategy,
    compile_industry_gtm_profile,
    verify_industry_gtm_profile,
)
from .gtm_creative_strategy_kernel import (
    CreativeStrategyKernelError,
    compile_creative_strategy_kernel,
    verify_creative_strategy_kernel,
)
from .gtm_editorial_quality import (
    EditorialQualityError,
    compile_editorial_quality_receipt,
    verify_editorial_quality_receipt,
)
from .gtm_multimodal_director import (
    MultimodalDirectorError,
    compile_multimodal_direction_receipt,
    verify_multimodal_direction_receipt,
)
from .gtm_strategy import (
    BudgetTier,
    CampaignStrategyInput,
    Channel,
    ClaimEvidence,
    GTMStrategy,
    IndustryRisk,
)


class ProductionPackError(ValueError):
    """Raised when a production draft is unsafe, ungrounded, or incoherent."""


class TruthStatus(str, Enum):
    DRAFT_ONLY = "draft_only"
    PRODUCTION_BRIEF_ONLY = "production_brief_only"


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_UNSAFE_EFFECT_PATTERNS = (
    re.compile(
        r"(?<!never )(?<!not )\bguarantee(?:d|s)?\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bwill\s+go\s+viral\b", re.IGNORECASE),
    re.compile(r"\bwill\s+drive\s+revenue\b", re.IGNORECASE),
    re.compile(r"\bguaranteed\s+roi\b", re.IGNORECASE),
    re.compile(r"\b4a(?:[- ]grade|[- ]quality)?\b", re.IGNORECASE),
    re.compile(r"\b(?:world|category)[- ]class\b", re.IGNORECASE),
    re.compile(r"\bbest[- ]in[- ]class\b", re.IGNORECASE),
    re.compile(r"\btop\s*1\b", re.IGNORECASE),
    re.compile(r"保证(?:爆款|营收|转化|效果)"),
    re.compile(r"必然(?:爆款|营收|转化|增长)"),
    re.compile(r"全球(?:第一|顶级)"),
)


def _required(value: str, *, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ProductionPackError(f"{field_name} is required")


def _sha(value: str, *, field_name: str) -> None:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ProductionPackError(f"{field_name} must be a lowercase SHA-256 digest")


def _safe_text(value: str, *, field_name: str) -> None:
    _required(value, field_name=field_name)
    if any(pattern.search(value) for pattern in _UNSAFE_EFFECT_PATTERNS):
        raise ProductionPackError(
            f"{field_name} contains an unsupported effect or quality claim"
        )


def _enum(value: Any, expected: type[Enum], *, field_name: str) -> None:
    if not isinstance(value, expected):
        raise ProductionPackError(f"{field_name} must be a {expected.__name__}")


def _string_tuple(
    values: tuple[str, ...],
    *,
    field_name: str,
    minimum: int = 1,
) -> None:
    if not isinstance(values, tuple) or len(values) < minimum:
        raise ProductionPackError(f"{field_name} must contain at least {minimum} items")
    if any(not isinstance(item, str) or not item.strip() for item in values):
        raise ProductionPackError(f"{field_name} must contain only nonblank strings")


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value


def canonical_json(value: Any) -> str:
    """Encode a pack payload deterministically for evidence receipts."""

    return json.dumps(
        _jsonable(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _evidence_label(citation: "EvidenceCitation") -> str:
    return (
        "Verified evidence"
        if citation.assurance_status == "verified"
        else "Owner-attested evidence"
    )


@dataclass(frozen=True)
class EvidenceCitation:
    proof_claim_id: str
    evidence_uri: str
    evidence_sha256: str
    assurance_status: str = "owner_attested"
    release_scope: str = "draft_only"

    def __post_init__(self) -> None:
        _required(self.proof_claim_id, field_name="proof_claim_id")
        _required(self.evidence_uri, field_name="evidence_uri")
        _sha(self.evidence_sha256, field_name="evidence_sha256")
        if self.assurance_status not in {"owner_attested", "verified"}:
            raise ProductionPackError("citation assurance_status is unsupported")
        _required(self.release_scope, field_name="release_scope")


@dataclass(frozen=True)
class BigIdeaDraft:
    hypothesis: str
    organizing_idea: str
    testable_tension: str
    truth_status: TruthStatus = TruthStatus.DRAFT_ONLY

    def __post_init__(self) -> None:
        _enum(self.truth_status, TruthStatus, field_name="truth_status")
        for name, value in (
            ("hypothesis", self.hypothesis),
            ("organizing_idea", self.organizing_idea),
            ("testable_tension", self.testable_tension),
        ):
            _safe_text(value, field_name=name)
        if not self.hypothesis.casefold().startswith("hypothesis:"):
            raise ProductionPackError("big idea must be explicitly labelled as a hypothesis")
        if self.truth_status != TruthStatus.DRAFT_ONLY:
            raise ProductionPackError("big idea may only be represented as a draft")


@dataclass(frozen=True)
class MessageHierarchy:
    hypothesis_led_promise: str
    evidenced_proof: str
    objection_question: str
    call_to_action: str
    citation: EvidenceCitation

    def __post_init__(self) -> None:
        for name, value in (
            ("hypothesis_led_promise", self.hypothesis_led_promise),
            ("evidenced_proof", self.evidenced_proof),
            ("objection_question", self.objection_question),
            ("call_to_action", self.call_to_action),
        ):
            _safe_text(value, field_name=name)
        if "hypothesis" not in self.hypothesis_led_promise.casefold():
            raise ProductionPackError("message promise must remain a hypothesis")
        if not self.objection_question.endswith("?"):
            raise ProductionPackError("objection must remain an open question")


@dataclass(frozen=True)
class ChannelNativeCopy:
    draft_id: str
    channel: Channel
    native_format: str
    hook: str
    body: tuple[str, ...]
    call_to_action: str
    citation: EvidenceCitation
    growth_tension_id: str
    truth_status: TruthStatus = TruthStatus.DRAFT_ONLY
    human_release_required: bool = True
    automated_publish_allowed: bool = False

    def __post_init__(self) -> None:
        _enum(self.channel, Channel, field_name="channel")
        _enum(self.truth_status, TruthStatus, field_name="truth_status")
        if not isinstance(self.human_release_required, bool) or not isinstance(
            self.automated_publish_allowed, bool
        ):
            raise ProductionPackError("release flags must be booleans")
        _required(self.draft_id, field_name="draft_id")
        _required(self.native_format, field_name="native_format")
        _required(self.growth_tension_id, field_name="growth_tension_id")
        _safe_text(self.hook, field_name="hook")
        _string_tuple(self.body, field_name="body")
        for item in self.body:
            _safe_text(item, field_name="body")
        _safe_text(self.call_to_action, field_name="call_to_action")
        if self.truth_status != TruthStatus.DRAFT_ONLY:
            raise ProductionPackError("channel copy may only be represented as a draft")
        if not self.human_release_required or self.automated_publish_allowed:
            raise ProductionPackError("channel copy requires manual human release")

    @property
    def rendered_text(self) -> str:
        return "\n\n".join((self.hook, *self.body, self.call_to_action))


@dataclass(frozen=True)
class ScheduledDraft:
    day: int
    channel: Channel
    source_draft_id: str
    asset_kind: str
    theme: str
    intended_learning: str
    release_mode: str = "human_review_then_manual_publish"

    def __post_init__(self) -> None:
        _enum(self.channel, Channel, field_name="channel")
        if isinstance(self.day, bool) or not isinstance(self.day, int) or self.day not in range(1, 8):
            raise ProductionPackError("schedule day must be between 1 and 7")
        for name, value in (
            ("source_draft_id", self.source_draft_id),
            ("asset_kind", self.asset_kind),
            ("theme", self.theme),
            ("intended_learning", self.intended_learning),
        ):
            _safe_text(value, field_name=name)
        if self.release_mode != "human_review_then_manual_publish":
            raise ProductionPackError("schedule cannot bypass manual release")


@dataclass(frozen=True)
class FAQDraft:
    question: str
    answer_draft: str
    citation: EvidenceCitation
    truth_status: TruthStatus = TruthStatus.DRAFT_ONLY

    def __post_init__(self) -> None:
        _enum(self.truth_status, TruthStatus, field_name="truth_status")
        _safe_text(self.question, field_name="question")
        _safe_text(self.answer_draft, field_name="answer_draft")
        if not self.question.endswith("?"):
            raise ProductionPackError("FAQ question must end with a question mark")
        if self.truth_status != TruthStatus.DRAFT_ONLY:
            raise ProductionPackError("FAQ answer may only be represented as a draft")


@dataclass(frozen=True)
class VideoShot:
    order: int
    function: str
    visual_direction: str
    on_screen_copy: str
    proof_claim_id: str | None = None
    evidence_sha256: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.order, bool) or not isinstance(self.order, int) or self.order < 1:
            raise ProductionPackError("video shot order must be positive")
        if self.function not in {"tension", "proof", "turn", "product_demonstration", "action"}:
            raise ProductionPackError("video shot requires an allowed communication function")
        _safe_text(self.visual_direction, field_name="visual_direction")
        _safe_text(self.on_screen_copy, field_name="on_screen_copy")
        if (self.proof_claim_id is None) != (self.evidence_sha256 is None):
            raise ProductionPackError("proof-bearing video shots need claim ID and digest")
        if self.evidence_sha256 is not None:
            _required(self.proof_claim_id or "", field_name="proof_claim_id")
            _sha(self.evidence_sha256, field_name="evidence_sha256")


@dataclass(frozen=True)
class VideoProductionBrief:
    hook: str
    shot_list: tuple[VideoShot, ...]
    on_screen_copy: tuple[str, ...]
    identity_lock: tuple[str, ...]
    delivery_spec: str
    rights_instructions: tuple[str, ...]
    truth_status: TruthStatus = TruthStatus.PRODUCTION_BRIEF_ONLY

    def __post_init__(self) -> None:
        _enum(self.truth_status, TruthStatus, field_name="truth_status")
        _safe_text(self.hook, field_name="video hook")
        if (
            not isinstance(self.shot_list, tuple)
            or len(self.shot_list) < 4
            or any(not isinstance(shot, VideoShot) for shot in self.shot_list)
        ):
            raise ProductionPackError("video brief requires at least four shots")
        if tuple(shot.order for shot in self.shot_list) != tuple(
            range(1, len(self.shot_list) + 1)
        ):
            raise ProductionPackError("video shots must be contiguous")
        for field_name, values in (
            ("on_screen_copy", self.on_screen_copy),
            ("identity_lock", self.identity_lock),
            ("rights_instructions", self.rights_instructions),
        ):
            _string_tuple(values, field_name=field_name)
            for value in values:
                _safe_text(value, field_name=field_name)
        _required(self.delivery_spec, field_name="delivery_spec")
        if "3840x2160" not in self.delivery_spec or "4K" not in self.delivery_spec:
            raise ProductionPackError("video delivery spec must define 4K dimensions")
        if self.truth_status != TruthStatus.PRODUCTION_BRIEF_ONLY:
            raise ProductionPackError("video cannot be represented as a rendered asset")


@dataclass(frozen=True)
class AudioProductionBrief:
    voice_direction: str
    music_direction: str
    sfx_direction: tuple[str, ...]
    mix_spec: str
    rights_instructions: tuple[str, ...]
    truth_status: TruthStatus = TruthStatus.PRODUCTION_BRIEF_ONLY

    def __post_init__(self) -> None:
        _enum(self.truth_status, TruthStatus, field_name="truth_status")
        for name, value in (
            ("voice_direction", self.voice_direction),
            ("music_direction", self.music_direction),
            ("mix_spec", self.mix_spec),
        ):
            _safe_text(value, field_name=name)
        for field_name, values in (
            ("sfx_direction", self.sfx_direction),
            ("rights_instructions", self.rights_instructions),
        ):
            _string_tuple(values, field_name=field_name)
            for value in values:
                _safe_text(value, field_name=field_name)
        if "48 kHz" not in self.mix_spec or "-14 LUFS" not in self.mix_spec:
            raise ProductionPackError("audio mix spec must define delivery loudness and rate")
        if self.truth_status != TruthStatus.PRODUCTION_BRIEF_ONLY:
            raise ProductionPackError("audio cannot be represented as a rendered asset")


@dataclass(frozen=True)
class AnalyticsPlan:
    experiment_id: str
    tracked_landing_url: str
    interpretation: str
    metrics: tuple[dict[str, Any], ...]
    stop_rules: tuple[str, ...]

    def __post_init__(self) -> None:
        _required(self.experiment_id, field_name="experiment_id")
        if not self.tracked_landing_url.startswith(("https://", "http://")):
            raise ProductionPackError("tracked_landing_url must be HTTP(S)")
        _safe_text(self.interpretation, field_name="interpretation")
        if "not a causal" not in self.interpretation.casefold():
            raise ProductionPackError("analytics interpretation must remain noncausal")
        if not self.metrics or not self.stop_rules:
            raise ProductionPackError("analytics requires metrics and stop rules")
        if not isinstance(self.metrics, tuple) or any(
            not isinstance(metric, dict)
            or not {
                "metric",
                "direction",
                "measurement_window_days",
                "minimum_sample",
                "pre_registered_before_launch",
            }.issubset(metric)
            or metric["pre_registered_before_launch"] is not True
            or not isinstance(metric["measurement_window_days"], int)
            or metric["measurement_window_days"] < 1
            or not isinstance(metric["minimum_sample"], int)
            or metric["minimum_sample"] < 1
            for metric in self.metrics
        ):
            raise ProductionPackError("analytics metrics must be valid pre-registrations")
        _string_tuple(self.stop_rules, field_name="stop_rules")
        for rule in self.stop_rules:
            _safe_text(rule, field_name="stop_rule")


@dataclass(frozen=True)
class ManualReleaseInstructions:
    accountable_owner: str
    ordered_checks: tuple[str, ...]
    publish_mode: str
    specialist_gate_required: bool
    specialist_approvers: tuple[str, ...]
    external_release_performed: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.specialist_gate_required, bool) or not isinstance(
            self.external_release_performed, bool
        ):
            raise ProductionPackError("release gate flags must be booleans")
        _required(self.accountable_owner, field_name="accountable_owner")
        _string_tuple(self.ordered_checks, field_name="ordered_checks", minimum=6)
        _string_tuple(
            self.specialist_approvers,
            field_name="specialist_approvers",
            minimum=1 if self.specialist_gate_required else 0,
        )
        if self.publish_mode != "manual_only":
            raise ProductionPackError("external publish must remain manual")
        if self.specialist_gate_required and not self.specialist_approvers:
            raise ProductionPackError("regulated release requires a specialist approver")
        if not self.specialist_gate_required and self.specialist_approvers:
            raise ProductionPackError("specialist approvers require a specialist gate")
        if self.external_release_performed:
            raise ProductionPackError("pack compilation does not perform external release")


@dataclass(frozen=True)
class GTMProductionPack:
    pack_id: str
    strategy_id: str
    campaign_id: str
    budget: BudgetTier
    industry_risk: IndustryRisk
    source_strategy_sha256: str
    growth_tension: dict[str, Any]
    citation: EvidenceCitation
    big_idea: BigIdeaDraft
    message_hierarchy: MessageHierarchy
    primary_copy: ChannelNativeCopy
    secondary_copy: ChannelNativeCopy
    channel_portfolio: dict[str, Any]
    breakout_growth_loop: dict[str, Any]
    text_creative_challenger_plan: dict[str, Any]
    industry_gtm_profile: dict[str, Any]
    creative_strategy_kernel: dict[str, Any]
    editorial_quality_receipt: dict[str, Any]
    multimodal_direction_receipt: dict[str, Any]
    seven_day_schedule: tuple[ScheduledDraft, ...]
    seo_geo_faqs: tuple[FAQDraft, ...]
    video_brief: VideoProductionBrief
    audio_brief: AudioProductionBrief
    analytics: AnalyticsPlan
    safety_constraints: tuple[str, ...]
    manual_release: ManualReleaseInstructions
    content_sha256: str

    def __post_init__(self) -> None:
        _enum(self.budget, BudgetTier, field_name="budget")
        _enum(self.industry_risk, IndustryRisk, field_name="industry_risk")
        expected_nested = (
            (self.citation, EvidenceCitation, "citation"),
            (self.big_idea, BigIdeaDraft, "big_idea"),
            (self.message_hierarchy, MessageHierarchy, "message_hierarchy"),
            (self.primary_copy, ChannelNativeCopy, "primary_copy"),
            (self.secondary_copy, ChannelNativeCopy, "secondary_copy"),
            (self.video_brief, VideoProductionBrief, "video_brief"),
            (self.audio_brief, AudioProductionBrief, "audio_brief"),
            (self.analytics, AnalyticsPlan, "analytics"),
            (self.manual_release, ManualReleaseInstructions, "manual_release"),
        )
        for value, expected, field_name in expected_nested:
            if not isinstance(value, expected):
                raise ProductionPackError(f"{field_name} must be a {expected.__name__}")
        for name, value in (
            ("pack_id", self.pack_id),
            ("strategy_id", self.strategy_id),
            ("campaign_id", self.campaign_id),
        ):
            _required(value, field_name=name)
        _sha(self.source_strategy_sha256, field_name="source_strategy_sha256")
        _sha(self.content_sha256, field_name="content_sha256")
        if not isinstance(self.growth_tension, dict) or not self.growth_tension.get(
            "tension_id"
        ):
            raise ProductionPackError("pack requires one growth tension binding")
        if self.primary_copy.growth_tension_id != self.growth_tension["tension_id"]:
            raise ProductionPackError("primary copy lost the growth tension binding")
        if self.secondary_copy.growth_tension_id != self.growth_tension["tension_id"]:
            raise ProductionPackError("secondary copy lost the growth tension binding")
        if self.primary_copy.channel == self.secondary_copy.channel:
            raise ProductionPackError("primary and secondary channels must differ")
        if self.primary_copy.rendered_text == self.secondary_copy.rendered_text:
            raise ProductionPackError("channel-native copy cannot be duplicated verbatim")
        try:
            verify_channel_portfolio(self.channel_portfolio)
        except ChannelPortfolioError as error:
            raise ProductionPackError(f"channel portfolio is invalid: {error}") from error
        if self.channel_portfolio.get("strategy_id") != self.strategy_id:
            raise ProductionPackError("channel portfolio strategy identity does not match")
        if self.channel_portfolio.get("campaign_id") != self.campaign_id:
            raise ProductionPackError("channel portfolio campaign identity does not match")
        if self.channel_portfolio.get("source_strategy_sha256") != self.source_strategy_sha256:
            raise ProductionPackError("channel portfolio source strategy digest does not match")
        try:
            verify_breakout_growth_loop(self.breakout_growth_loop)
        except BreakoutLoopError as error:
            raise ProductionPackError(f"breakout growth loop is invalid: {error}") from error
        if self.breakout_growth_loop.get("strategy_id") != self.strategy_id:
            raise ProductionPackError("breakout loop strategy identity does not match")
        if self.breakout_growth_loop.get("campaign_id") != self.campaign_id:
            raise ProductionPackError("breakout loop campaign identity does not match")
        if self.breakout_growth_loop.get("source_strategy_sha256") != self.source_strategy_sha256:
            raise ProductionPackError("breakout loop source strategy digest does not match")
        try:
            verify_text_challenger_plan(self.text_creative_challenger_plan)
        except TextChallengerError as error:
            raise ProductionPackError(f"text creative challenger plan is invalid: {error}") from error
        if self.text_creative_challenger_plan.get("strategy_id") != self.strategy_id:
            raise ProductionPackError("text challenger strategy identity does not match")
        if self.text_creative_challenger_plan.get("campaign_id") != self.campaign_id:
            raise ProductionPackError("text challenger campaign identity does not match")
        if self.text_creative_challenger_plan.get("source_strategy_sha256") != self.source_strategy_sha256:
            raise ProductionPackError("text challenger source strategy digest does not match")
        try:
            verify_industry_gtm_profile(self.industry_gtm_profile)
        except IndustryProfileError as error:
            raise ProductionPackError(f"industry GTM profile is invalid: {error}") from error
        if self.industry_gtm_profile.get("strategy_id") != self.strategy_id:
            raise ProductionPackError("industry profile strategy identity does not match")
        if self.industry_gtm_profile.get("campaign_id") != self.campaign_id:
            raise ProductionPackError("industry profile campaign identity does not match")
        if self.industry_gtm_profile.get("source_strategy_sha256") != self.source_strategy_sha256:
            raise ProductionPackError("industry profile source strategy digest does not match")
        try:
            verify_creative_strategy_kernel(self.creative_strategy_kernel)
        except CreativeStrategyKernelError as error:
            raise ProductionPackError(f"creative strategy kernel is invalid: {error}") from error
        if self.creative_strategy_kernel.get("strategy_id") != self.strategy_id:
            raise ProductionPackError("creative strategy kernel identity does not match")
        if self.creative_strategy_kernel.get("campaign_id") != self.campaign_id:
            raise ProductionPackError("creative strategy kernel campaign identity does not match")
        if self.creative_strategy_kernel.get("source_strategy_sha256") != self.source_strategy_sha256:
            raise ProductionPackError("creative strategy kernel source strategy digest does not match")
        try:
            verify_editorial_quality_receipt(self.editorial_quality_receipt)
        except EditorialQualityError as error:
            raise ProductionPackError(f"editorial quality receipt is invalid: {error}") from error
        if self.editorial_quality_receipt.get("strategy_id") != self.strategy_id:
            raise ProductionPackError("editorial quality strategy identity does not match")
        if self.editorial_quality_receipt.get("campaign_id") != self.campaign_id:
            raise ProductionPackError("editorial quality campaign identity does not match")
        try:
            verify_multimodal_direction_receipt(self.multimodal_direction_receipt)
        except MultimodalDirectorError as error:
            raise ProductionPackError(f"multimodal direction receipt is invalid: {error}") from error
        if self.multimodal_direction_receipt.get("strategy_id") != self.strategy_id:
            raise ProductionPackError("multimodal direction strategy identity does not match")
        if self.multimodal_direction_receipt.get("campaign_id") != self.campaign_id:
            raise ProductionPackError("multimodal direction campaign identity does not match")
        if self.budget == BudgetTier.ZERO and (
            self.primary_copy.channel.paid or self.secondary_copy.channel.paid
        ):
            raise ProductionPackError("zero-budget pack cannot contain paid channels")
        required_safety = {"spam", "automated_publish"}
        if self.budget == BudgetTier.ZERO:
            required_safety.update({"paid_placement", "media_spend"})
        if not required_safety.issubset(set(self.safety_constraints)):
            raise ProductionPackError(
                "pack does not preserve the required budget and release constraints"
            )
        if not isinstance(self.seven_day_schedule, tuple) or any(
            not isinstance(item, ScheduledDraft) for item in self.seven_day_schedule
        ) or len(self.seven_day_schedule) != 7 or tuple(
            item.day for item in self.seven_day_schedule
        ) != tuple(range(1, 8)):
            raise ProductionPackError("pack requires a contiguous seven-day schedule")
        draft_by_channel = {
            self.primary_copy.channel: self.primary_copy.draft_id,
            self.secondary_copy.channel: self.secondary_copy.draft_id,
        }
        for item in self.seven_day_schedule:
            if draft_by_channel.get(item.channel) != item.source_draft_id:
                raise ProductionPackError("schedule must point to its channel-native draft")
        if not isinstance(self.seo_geo_faqs, tuple) or not self.seo_geo_faqs or any(
            not isinstance(item, FAQDraft) for item in self.seo_geo_faqs
        ):
            raise ProductionPackError("pack requires SEO/GEO FAQ drafts")
        citations = (
            self.citation,
            self.message_hierarchy.citation,
            self.primary_copy.citation,
            self.secondary_copy.citation,
            *(item.citation for item in self.seo_geo_faqs),
        )
        if any(item != self.citation for item in citations):
            raise ProductionPackError("every factual draft must share the evidence citation")
        proof_shots = [shot for shot in self.video_brief.shot_list if shot.proof_claim_id]
        if not proof_shots or any(
            shot.proof_claim_id != self.citation.proof_claim_id
            or shot.evidence_sha256 != self.citation.evidence_sha256
            for shot in proof_shots
        ):
            raise ProductionPackError("video proof card must preserve evidence binding")
        if self.industry_risk == IndustryRisk.HIGH_REGULATION and not (
            self.manual_release.specialist_gate_required
            and self.manual_release.specialist_approvers
        ):
            raise ProductionPackError("regulated pack must retain the specialist gate")
        if self.industry_risk == IndustryRisk.STANDARD and (
            self.manual_release.specialist_gate_required
            or self.manual_release.specialist_approvers
        ):
            raise ProductionPackError("standard-risk pack cannot invent a specialist gate")
        if self.content_sha256 != _digest(self.payload_dict()):
            raise ProductionPackError("content_sha256 does not match canonical pack payload")

    def payload_dict(self) -> dict[str, Any]:
        payload = _jsonable(asdict(self))
        payload.pop("content_sha256")
        return payload

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))

    def canonical_json(self) -> str:
        return canonical_json(self.to_dict())

    def verify_digest(self) -> bool:
        return self.content_sha256 == _digest(self.payload_dict())

    def artifact_payloads(self) -> dict[str, dict[str, Any]]:
        """Return ready-to-bundle logical artifacts without duplicating assembly code."""

        landing_page = {
            "schema": "ProofLaunchLandingPageDraftV1",
            "strategy_id": self.strategy_id,
            "campaign_id": self.campaign_id,
            "hero": {
                "headline": self.big_idea.testable_tension,
                "hypothesis": self.message_hierarchy.hypothesis_led_promise,
                "supporting_proof": self.message_hierarchy.evidenced_proof,
                "objection_question": self.message_hierarchy.objection_question,
                "call_to_action": self.message_hierarchy.call_to_action,
            },
            "citation": _jsonable(self.citation),
            "truth_status": TruthStatus.DRAFT_ONLY.value,
            "human_release_required": True,
            "automated_publish_allowed": False,
            "external_publish_executed": False,
        }
        lifecycle_email = {
            "schema": "ProofLaunchLifecycleEmailDraftV1",
            "strategy_id": self.strategy_id,
            "campaign_id": self.campaign_id,
            "subject": "Can the evidence carry the promise?",
            "preheader": self.message_hierarchy.evidenced_proof,
            "body_blocks": [
                self.message_hierarchy.hypothesis_led_promise,
                self.message_hierarchy.evidenced_proof,
                self.message_hierarchy.objection_question,
            ],
            "call_to_action": self.message_hierarchy.call_to_action,
            "citation": _jsonable(self.citation),
            "truth_status": TruthStatus.DRAFT_ONLY.value,
            "human_release_required": True,
            "automated_send_allowed": False,
            "external_send_executed": False,
        }
        return {
            "gtm-production-pack.json": self.to_dict(),
            "big-idea-and-message-hierarchy.json": {
                "strategy_id": self.strategy_id,
                "growth_tension": self.growth_tension,
                "citation": _jsonable(self.citation),
                "big_idea": _jsonable(self.big_idea),
                "message_hierarchy": _jsonable(self.message_hierarchy),
                "creative_strategy_kernel_sha256": self.creative_strategy_kernel[
                    "content_sha256"
                ],
                "creative_territories": self.creative_strategy_kernel[
                    "creative_territories"
                ],
            },
            "channel-copy.json": {
                "primary": {
                    **_jsonable(self.primary_copy),
                    "rendered_text": self.primary_copy.rendered_text,
                },
                "secondary": {
                    **_jsonable(self.secondary_copy),
                    "rendered_text": self.secondary_copy.rendered_text,
                },
                "safety_constraints": list(self.safety_constraints),
            },
            "landing-page-draft.json": landing_page,
            "lifecycle-email-draft.json": lifecycle_email,
            "channel-portfolio.json": self.channel_portfolio,
            "breakout-growth-loop.json": self.breakout_growth_loop,
            "text-creative-challenger-plan.json": self.text_creative_challenger_plan,
            "industry-gtm-profile.json": self.industry_gtm_profile,
            "creative-strategy-kernel.json": self.creative_strategy_kernel,
            "editorial-quality-receipt.json": self.editorial_quality_receipt,
            "multimodal-direction-receipt.json": self.multimodal_direction_receipt,
            "seven-day-schedule.json": {
                "entries": _jsonable(self.seven_day_schedule),
            },
            "seo-geo-faq-drafts.json": {
                "faqs": _jsonable(self.seo_geo_faqs),
            },
            "video-production-brief.json": _jsonable(self.video_brief),
            "audio-production-brief.json": _jsonable(self.audio_brief),
            "analytics-plan.json": _jsonable(self.analytics),
            "manual-release-instructions.json": _jsonable(self.manual_release),
        }

    def to_artifacts(self) -> dict[str, bytes]:
        """Return deterministic UTF-8 JSON members suitable for a ZIP bundle."""

        return {
            name: (canonical_json(payload) + "\n").encode("utf-8")
            for name, payload in self.artifact_payloads().items()
        }


_CHANNEL_FORMAT: dict[Channel, tuple[str, str]] = {
    Channel.COMMUNITY_LISTENING: (
        "moderated community question",
        "Listening prompt",
    ),
    Channel.CREATOR_COMMUNITY: ("creator collaboration brief", "Creator brief"),
    Channel.CUSTOMER_EVIDENCE: ("evidence card", "Evidence review"),
    Channel.CUSTOMER_EMAIL: ("plain-text customer email", "Customer note"),
    Channel.FOUNDER_CONVERSATIONS: (
        "one-to-one founder interview prompt",
        "Founder question",
    ),
    Channel.LINKEDIN_ORGANIC: ("LinkedIn text post", "Decision note"),
    Channel.OWNED_SOCIAL: ("owned social carousel caption", "Swipe-through question"),
    Channel.PARTNER_COMMUNITIES: ("partner community discussion", "Peer review"),
    Channel.SEARCH_EDUCATION: ("search-led explainer", "Evidence explainer"),
    Channel.SHORT_VIDEO_ORGANIC: ("vertical short-video script", "Stop-scroll question"),
    Channel.PAID_SEARCH: ("paid-search draft for manual activation", "Search intent draft"),
    Channel.PAID_SOCIAL: ("paid-social draft for manual activation", "Feed experiment draft"),
}

_CHANNEL_ASSET_KIND: dict[Channel, str] = {
    Channel.COMMUNITY_LISTENING: "moderated_question",
    Channel.CREATOR_COMMUNITY: "creator_collaboration_brief",
    Channel.CUSTOMER_EVIDENCE: "evidence_card",
    Channel.CUSTOMER_EMAIL: "plain_text_email",
    Channel.FOUNDER_CONVERSATIONS: "interview_prompt",
    Channel.LINKEDIN_ORGANIC: "text_post",
    Channel.OWNED_SOCIAL: "carousel_caption",
    Channel.PARTNER_COMMUNITIES: "peer_discussion_prompt",
    Channel.SEARCH_EDUCATION: "search_explainer",
    Channel.SHORT_VIDEO_ORGANIC: "vertical_video_script",
    Channel.PAID_SEARCH: "search_ad_draft",
    Channel.PAID_SOCIAL: "feed_ad_draft",
}


class ProductionPackCompiler:
    """Compile evidence-bound, channel-native drafts from one strategy spine.

    This compiler does not render media, publish content, spend budget, contact
    users, or claim that a draft produced an outcome.
    """

    def compile(
        self,
        request: CampaignStrategyInput,
        strategy: GTMStrategy,
        *,
        signal_platform_counts: Mapping[str, int] | None = None,
        signal_intelligence: Mapping[str, Any] | None = None,
        genome_learning_memory: Mapping[str, Any] | None = None,
        named_capability_distillation: Mapping[str, Any] | None = None,
    ) -> GTMProductionPack:
        claim = self._validate_strategy_spine(request, strategy)
        citation = EvidenceCitation(
            proof_claim_id=claim.claim_id,
            evidence_uri=claim.evidence_uri,
            evidence_sha256=claim.evidence_sha256,
            assurance_status=claim.assurance_status,
            release_scope=claim.release_scope,
        )
        source_strategy_sha256 = _digest(strategy)
        pack_id = f"pack-{_digest({'strategy': source_strategy_sha256})[:16]}"

        try:
            industry_gtm_profile = bind_industry_profile_strategy(
                compile_industry_gtm_profile(
                    request,
                    source_strategy_sha256=source_strategy_sha256,
                ),
                strategy_id=strategy.strategy_id,
            )
        except IndustryProfileError as error:
            raise ProductionPackError(f"industry GTM profile safety gate failed: {error}") from error

        try:
            creative_strategy_kernel = compile_creative_strategy_kernel(request, strategy)
        except CreativeStrategyKernelError as error:
            raise ProductionPackError(
                f"creative strategy kernel safety gate failed: {error}"
            ) from error

        big_idea = BigIdeaDraft(
            hypothesis=strategy.hero_hypothesis,
            organizing_idea=(
                f"Make the decision inspectable: place {_evidence_label(citation).casefold()} "
                f"{claim.claim_id} "
                "before the ask, then invite the audience to challenge it. "
                f"The zero-budget operating hypothesis is: {industry_gtm_profile['zero_budget_growth_engine']}"
            ),
            testable_tension=(
                f"Can {strategy.growth_tensions[0].audience} resolve "
                f"{strategy.growth_tensions[0].problem.rstrip('?. ')} under this constraint: "
                f"{strategy.growth_tensions[0].business_constraint.rstrip('?. ')}?"
            ),
        )
        hierarchy = MessageHierarchy(
            hypothesis_led_promise=strategy.hero_hypothesis,
            evidenced_proof=strategy.proof,
            objection_question=strategy.objection,
            call_to_action=strategy.call_to_action,
            citation=citation,
        )
        primary_copy = self._channel_copy(
            request, strategy, strategy.primary_channel, citation, role="primary"
        )
        secondary_copy = self._channel_copy(
            request, strategy, strategy.secondary_channel, citation, role="secondary"
        )
        channel_portfolio = compile_channel_portfolio(
            request,
            strategy,
            signal_platform_counts=signal_platform_counts,
        )
        breakout_growth_loop = compile_breakout_growth_loop(
            request,
            strategy,
            source_strategy_sha256=source_strategy_sha256,
        )
        baseline_copy_sha256 = _digest(
            {
                "primary": _jsonable(primary_copy),
                "secondary": _jsonable(secondary_copy),
            }
        )
        text_creative_challenger_plan = build_text_challenger_plan(
            request,
            strategy,
            source_strategy_sha256=source_strategy_sha256,
            baseline_copy_sha256=baseline_copy_sha256,
            primary_native_format=primary_copy.native_format,
            secondary_native_format=secondary_copy.native_format,
            breakout_growth_loop=breakout_growth_loop,
            signal_intelligence=signal_intelligence,
            genome_learning_memory=genome_learning_memory,
            named_capability_distillation=named_capability_distillation,
        )
        copies = {
            primary_copy.channel: primary_copy,
            secondary_copy.channel: secondary_copy,
        }
        schedule = tuple(
            ScheduledDraft(
                day=item.day,
                channel=item.channel,
                source_draft_id=copies[item.channel].draft_id,
                asset_kind=_CHANNEL_ASSET_KIND[item.channel],
                theme=item.theme,
                intended_learning=item.intended_learning,
            )
            for item in strategy.seven_day_content
        )
        faqs = tuple(
            FAQDraft(
                question=question,
                answer_draft=self._faq_answer(index, strategy.proof),
                citation=citation,
            )
            for index, question in enumerate(strategy.seo_geo_question_intents)
        )
        video = self._video_brief(request, strategy, citation)
        audio = self._audio_brief(request)
        try:
            editorial_quality_receipt = compile_editorial_quality_receipt(
                request,
                strategy,
                primary_copy=_jsonable(primary_copy),
                secondary_copy=_jsonable(secondary_copy),
                video_hook=video.hook,
                long_form_blocks=(
                    big_idea.organizing_idea,
                    hierarchy.hypothesis_led_promise,
                    hierarchy.evidenced_proof,
                    hierarchy.objection_question,
                    hierarchy.call_to_action,
                ),
            )
        except EditorialQualityError as error:
            raise ProductionPackError(
                f"editorial quality safety gate failed: {error}"
            ) from error
        try:
            multimodal_direction_receipt = compile_multimodal_direction_receipt(
                strategy_id=strategy.strategy_id,
                campaign_id=request.campaign_id,
                brand_name=request.brand.brand_name,
                claim_id=citation.proof_claim_id,
                evidence_sha256=citation.evidence_sha256,
                customer_promise=request.brand.customer_promise,
                call_to_action=strategy.call_to_action,
                creative_strategy_kernel=creative_strategy_kernel,
                video_brief=_jsonable(video),
                audio_brief=_jsonable(audio),
            )
        except MultimodalDirectorError as error:
            raise ProductionPackError(
                f"multimodal direction safety gate failed: {error}"
            ) from error
        analytics = AnalyticsPlan(
            experiment_id=strategy.attribution.experiment_id,
            tracked_landing_url=self._tracked_url(request.landing_url, strategy),
            interpretation=strategy.attribution.interpretation,
            metrics=tuple(asdict(metric) for metric in strategy.metrics),
            stop_rules=strategy.stop_rules,
        )
        relevant_channels = {strategy.primary_channel, strategy.secondary_channel}
        safety_constraints = tuple(
            sorted(
                {
                    action
                    for constraint in strategy.channel_constraints
                    if constraint.channel in relevant_channels
                    for action in constraint.prohibited_actions
                }
                | {
                    str(action)
                    for action in industry_gtm_profile["creative_constraints"]
                }
            )
        )
        specialist_approvers = tuple(
            sorted(
                {
                    item.specialist_approved_by
                    for item in request.claims
                    if item.specialist_approved_by
                }
            )
        )
        regulated = request.industry_risk == IndustryRisk.HIGH_REGULATION
        release = ManualReleaseInstructions(
            accountable_owner=request.owner,
            ordered_checks=(
                "re-open every cited source and match the visible claim to its digest",
                "confirm evidence rights and validity still permit this exact use",
                "compare all draft wording with the brand constitution",
                "review accessibility, identity, privacy, and channel policy",
                "verify UTM values and the pre-registered measurement window",
                "confirm no outcome, rendered-media, or external-release claim was added",
                (
                    "record a named human confirmation of the inferred industry archetype and business-model fit"
                    if industry_gtm_profile["human_classification_confirmation_required"]
                    else "confirm the compiled industry buying motion and conversion unit still match the offer"
                ),
                (
                    "obtain named specialist sign-off on the final unchanged wording"
                    if regulated
                    else "record the accountable owner's final accept or reject decision"
                ),
                "publish manually only after every prior check passes",
            ),
            publish_mode="manual_only",
            specialist_gate_required=regulated,
            specialist_approvers=specialist_approvers if regulated else (),
        )
        payload: dict[str, Any] = {
            "pack_id": pack_id,
            "strategy_id": strategy.strategy_id,
            "campaign_id": request.campaign_id,
            "budget": request.budget,
            "industry_risk": request.industry_risk,
            "source_strategy_sha256": source_strategy_sha256,
            "growth_tension": _jsonable(strategy.growth_tensions[0]),
            "citation": citation,
            "big_idea": big_idea,
            "message_hierarchy": hierarchy,
            "primary_copy": primary_copy,
            "secondary_copy": secondary_copy,
            "channel_portfolio": channel_portfolio,
            "breakout_growth_loop": breakout_growth_loop,
            "text_creative_challenger_plan": text_creative_challenger_plan,
            "industry_gtm_profile": industry_gtm_profile,
            "creative_strategy_kernel": creative_strategy_kernel,
            "editorial_quality_receipt": editorial_quality_receipt,
            "multimodal_direction_receipt": multimodal_direction_receipt,
            "seven_day_schedule": schedule,
            "seo_geo_faqs": faqs,
            "video_brief": video,
            "audio_brief": audio,
            "analytics": analytics,
            "safety_constraints": safety_constraints,
            "manual_release": release,
        }
        self._scan_output(payload)
        return GTMProductionPack(**payload, content_sha256=_digest(payload))

    @staticmethod
    def _validate_strategy_spine(
        request: CampaignStrategyInput,
        strategy: GTMStrategy,
    ) -> ClaimEvidence:
        _required(strategy.strategy_id, field_name="strategy_id")
        claims = {item.claim_id: item for item in request.claims}
        claim = claims.get(strategy.proof_claim_id)
        if claim is None:
            raise ProductionPackError("strategy proof_claim_id is absent from the request")
        if (
            strategy.proof != claim.text
            or strategy.proof_evidence_uri != claim.evidence_uri
            or strategy.proof_evidence_sha256 != claim.evidence_sha256
        ):
            raise ProductionPackError("strategy proof does not match its evidence-bound claim")
        if strategy.primary_channel == strategy.secondary_channel:
            raise ProductionPackError("strategy channels must differ")
        if request.budget == BudgetTier.ZERO and (
            strategy.primary_channel.paid or strategy.secondary_channel.paid
        ):
            raise ProductionPackError("zero-budget strategy cannot contain paid channels")
        constraint_channels = {item.channel for item in strategy.channel_constraints}
        if not {strategy.primary_channel, strategy.secondary_channel}.issubset(
            constraint_channels
        ):
            raise ProductionPackError("strategy is missing a channel safety constraint")
        if any(
            item.automated_publish_allowed
            for item in strategy.channel_constraints
            if item.channel in {strategy.primary_channel, strategy.secondary_channel}
        ):
            raise ProductionPackError("strategy cannot enable automated publishing")
        if request.industry_risk == IndustryRisk.HIGH_REGULATION and not (
            claim.specialist_approved_by and claim.specialist_approved_by.strip()
        ):
            raise ProductionPackError("regulated proof requires named specialist approval")
        ProductionPackCompiler._scan_output(strategy)
        return claim

    @staticmethod
    def _channel_copy(
        request: CampaignStrategyInput,
        strategy: GTMStrategy,
        channel: Channel,
        citation: EvidenceCitation,
        *,
        role: str,
    ) -> ChannelNativeCopy:
        native_format, prefix = _CHANNEL_FORMAT[channel]
        if role == "primary":
            hook = (
                f"{prefix}: what proof would help {request.audience.name} decide "
                "whether the next step is worth taking?"
            )
            body = (
                strategy.hero_hypothesis,
                f"{_evidence_label(citation)} [{citation.proof_claim_id}]: {strategy.proof}",
                f"Open objection: {strategy.objection}",
            )
            cta = strategy.call_to_action
        else:
            hook = (
                f"{prefix}: challenge the evidence before accepting the promise."
            )
            body = (
                f"Evidence card [{citation.proof_claim_id}]: {strategy.proof}",
                "Decision context to test: "
                f"{request.audience.buying_context.strip().rstrip('.')}.",
                "Draft status: inspect the cited source and surface the strongest unresolved question.",
            )
            cta = "Inspect the cited evidence, then share the strongest unresolved objection."
        return ChannelNativeCopy(
            draft_id=f"copy-{role}-{channel.value}",
            channel=channel,
            native_format=native_format,
            hook=hook,
            body=body,
            call_to_action=cta,
            citation=citation,
            growth_tension_id=strategy.growth_tensions[0].tension_id,
        )

    @staticmethod
    def _faq_answer(index: int, proof: str) -> str:
        leads = (
            "Start with the currently cited evidence",
            "Require a source-bound proof rather than an outcome promise",
            "For this draft, the cited support is",
            "A cautious answer begins with the evidence and its limits",
        )
        lead = leads[index % len(leads)]
        return f"{lead}: {proof} Review the cited source and validity before deciding."

    @staticmethod
    def _video_brief(
        request: CampaignStrategyInput,
        strategy: GTMStrategy,
        citation: EvidenceCitation,
    ) -> VideoProductionBrief:
        proof_card = f"{_evidence_label(citation)} [{citation.proof_claim_id}]: {strategy.proof}"
        shots = (
            VideoShot(
                1,
                "tension",
                "Open on an owner-supplied product surface in a split-frame tension against the unresolved decision; do not invent logo, packaging, or product UI.",
                strategy.hero_hypothesis,
            ),
            VideoShot(
                2,
                "product_demonstration",
                "Frame the audience decision as an on-screen question, using no stock testimonial.",
                "What proof would make the next step easier to evaluate?",
            ),
            VideoShot(
                3,
                "proof",
                "Show a legible evidence card and persistent source marker.",
                proof_card,
                citation.proof_claim_id,
                citation.evidence_sha256,
            ),
            VideoShot(
                4,
                "turn",
                "Hold on the unresolved objection with sufficient reading time.",
                strategy.objection,
            ),
            VideoShot(
                5,
                "action",
                "Close with a manual next-step card and no simulated engagement metrics.",
                strategy.call_to_action,
            ),
        )
        return VideoProductionBrief(
            hook=strategy.hero_hypothesis,
            shot_list=shots,
            on_screen_copy=tuple(shot.on_screen_copy for shot in shots),
            identity_lock=(
                f"preserve the exact brand spelling: {request.brand.brand_name}",
                "use only owner-supplied logo, product UI, people, and packaging assets",
                "reject identity drift, invented UI, synthetic testimonials, and altered proof text",
            ),
            delivery_spec=(
                "4K delivery target: 3840x2160, 16:9 master, 30 fps, H.264 high-profile; "
                "also derive a 2160x3840 9:16 crop only after title-safe review"
            ),
            rights_instructions=(
                "keep a source and license receipt for every visual asset",
                "do not render a person, logo, product UI, music, or voice without permission",
                f"preserve claim {citation.proof_claim_id} and digest {citation.evidence_sha256}",
            ),
        )

    @staticmethod
    def _audio_brief(request: CampaignStrategyInput) -> AudioProductionBrief:
        voice = ", ".join(request.brand.voice_principles)
        return AudioProductionBrief(
            voice_direction=(
                f"Human voice direction: {voice}; measured pace; read claim wording exactly."
            ),
            music_direction=(
                "Optional restrained instrumental bed; leave space for evidence and objection wording."
            ),
            sfx_direction=(
                "single subtle transition into the evidence card",
                "no applause, crowd reaction, sales chime, or simulated social proof",
            ),
            mix_spec=(
                "Stereo 48 kHz / 24-bit master, integrated -14 LUFS, true peak at or below -1 dBTP; "
                "supply voice-only and music-and-effects stems"
            ),
            rights_instructions=(
                "use an owned human recording or a voice model with explicit production rights",
                "use only owned or licensed music and SFX with a stored receipt",
                "do not imitate a real person without documented consent",
            ),
        )

    @staticmethod
    def _tracked_url(landing_url: str, strategy: GTMStrategy) -> str:
        parts = urlsplit(landing_url)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        query.update(
            {
                "utm_source": strategy.attribution.utm_source,
                "utm_medium": strategy.attribution.utm_medium,
                "utm_campaign": strategy.attribution.utm_campaign,
                "utm_content": strategy.attribution.utm_content,
                "experiment_id": strategy.attribution.experiment_id,
            }
        )
        return urlunsplit(
            (parts.scheme, parts.netloc, parts.path, urlencode(sorted(query.items())), parts.fragment)
        )

    @staticmethod
    def _scan_output(value: Any) -> None:
        def visit(item: Any, path: str) -> None:
            if is_dataclass(item):
                visit(asdict(item), path)
            elif isinstance(item, dict):
                for key, nested in item.items():
                    visit(nested, f"{path}.{key}")
            elif isinstance(item, (tuple, list)):
                for index, nested in enumerate(item):
                    visit(nested, f"{path}[{index}]")
            elif isinstance(item, str):
                if any(pattern.search(item) for pattern in _UNSAFE_EFFECT_PATTERNS):
                    raise ProductionPackError(
                        f"{path} contains an unsupported effect or quality claim"
                    )

        visit(value, "pack")


def production_pack_digest(pack: GTMProductionPack) -> str:
    """Return the verified stable digest for a compiled production pack."""

    if not pack.verify_digest():
        raise ProductionPackError("production pack digest verification failed")
    return pack.content_sha256
