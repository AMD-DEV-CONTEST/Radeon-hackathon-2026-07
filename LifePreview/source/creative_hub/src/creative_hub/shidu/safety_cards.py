"""Immutable, deterministic safety-card policy for Shidu trial content.

The policy consumes structured safety signals. Signal extraction is deliberately
outside this module so both pre-compile and post-compile gates can bind their
own evidence while sharing one deterministic decision contract.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from pydantic import Field, StrictBool, ValidationError, field_validator, model_validator

from creative_hub.quality import FrozenModel, canonical_digest


SAFETY_CARD_SCHEMA_VERSION = "creative-hub.shidu-safety-cards/v1"
SAFETY_CARD_EVALUATOR_VERSION = "shidu-safety-card-evaluator.v1"
SAFETY_BASELINE_POLICY_ID = "shidu-book-safety-baseline.v1"


class SafetyEvaluationError(ValueError):
    """Safety evaluation could not produce an authoritative decision."""


class BookSafetyCategory(StrEnum):
    FICTION = "fiction"
    BIOGRAPHY = "biography"
    HISTORY_NONFICTION = "history_nonfiction"
    MYSTERY = "mystery"
    YOUTH_ROMANCE = "youth_romance"


class SafetyPhase(StrEnum):
    PRE_COMPILE = "pre_compile"
    POST_COMPILE = "post_compile"


class SafetyRiskArea(StrEnum):
    CORE_SPOILERS = "core_spoilers"
    VIOLENCE_SELF_HARM = "violence_self_harm"
    MINORS = "minors"
    TOBACCO_ALCOHOL = "tobacco_alcohol"
    HATE = "hate"
    MEDICAL_LEGAL_MISINFORMATION = "medical_legal_misinformation"
    IDENTIFIABLE_LONG_SOURCE_TEXT = "identifiable_long_source_text"


class SafetySignals(FrozenModel):
    core_spoiler_revealed: StrictBool = False
    graphic_violence: StrictBool = False
    self_harm: StrictBool = False
    subject_is_minor: StrictBool = False
    identifiable_minor: StrictBool = False
    minor_sexualization: StrictBool = False
    tobacco_alcohol_glamorized: StrictBool = False
    hate_or_dehumanization: StrictBool = False
    unverified_medical_claim: StrictBool = False
    unverified_legal_claim: StrictBool = False
    unverified_defamation: StrictBool = False
    identifiable_long_source_text: StrictBool = False


_SIGNAL_NAMES = frozenset(SafetySignals.model_fields)


class SafetySignalEvidence(FrozenModel):
    signal_name: str = Field(min_length=1, max_length=80)
    evidence_refs: tuple[str, ...] = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def valid_evidence(self) -> SafetySignalEvidence:
        if self.signal_name not in _SIGNAL_NAMES:
            raise ValueError("unknown safety signal evidence")
        canonical = tuple(item.strip() for item in self.evidence_refs)
        if (
            any(not item for item in canonical)
            or len(canonical) != len(set(canonical))
            or canonical != tuple(sorted(canonical))
        ):
            raise ValueError("safety signal evidence must be unique and sorted")
        return self


class SafetyContent(FrozenModel):
    content_revision_id: str = Field(min_length=1, max_length=200)
    content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    signals: SafetySignals
    signal_evidence_refs: tuple[SafetySignalEvidence, ...] = ()
    input_digest: str = ""

    @field_validator("signal_evidence_refs", mode="before")
    @classmethod
    def normalize_evidence(cls, value: object) -> object:
        if isinstance(value, Mapping):
            normalized = []
            for name, refs in sorted(value.items(), key=lambda item: str(item[0])):
                if not isinstance(refs, (list, tuple)):
                    raise ValueError("safety signal evidence refs must be a list")
                normalized.append(
                    {
                        "signal_name": str(name),
                        "evidence_refs": tuple(sorted(refs)),
                    }
                )
            return tuple(normalized)
        return value

    @model_validator(mode="after")
    def bind_input_truth(self) -> SafetyContent:
        evidence_names = tuple(item.signal_name for item in self.signal_evidence_refs)
        if len(evidence_names) != len(set(evidence_names)):
            raise ValueError("safety signal evidence names must be unique")
        active_names = {
            name
            for name, active in self.signals.model_dump(mode="python").items()
            if active
        }
        if set(evidence_names) != active_names:
            raise ValueError("active safety signals require exact evidence refs")
        expected = canonical_digest(
            self.model_dump(mode="json", exclude={"input_digest"})
        )
        if self.input_digest and self.input_digest != expected:
            raise ValueError("input_digest does not match safety content")
        object.__setattr__(self, "input_digest", expected)
        return self


class SafetyRule(FrozenModel):
    rule_id: str = Field(pattern=r"^shidu-[a-z0-9-]+\.v[1-9][0-9]*$")
    risk_area: SafetyRiskArea
    trigger_all: tuple[str, ...] = Field(min_length=1)
    trigger_none: tuple[str, ...] = ()
    phases: tuple[SafetyPhase, ...] = Field(min_length=1)
    warning: str = Field(min_length=1, max_length=500)
    rewrite_requirement: str = Field(min_length=1, max_length=500)
    blocked_reason_code: str = Field(pattern=r"^[a-z][a-z0-9_]{2,100}$")
    required_human_review: bool = True

    @model_validator(mode="after")
    def valid_triggers(self) -> SafetyRule:
        required = set(self.trigger_all)
        forbidden = set(self.trigger_none)
        if (
            len(required) != len(self.trigger_all)
            or len(forbidden) != len(self.trigger_none)
            or required & forbidden
            or not (required | forbidden).issubset(_SIGNAL_NAMES)
        ):
            raise ValueError("safety rule has invalid signal triggers")
        if len(self.phases) != len(set(self.phases)):
            raise ValueError("safety rule phases must be unique")
        if self.blocked_reason_code not in self.rewrite_requirement:
            raise ValueError("rewrite requirement must name its blocked reason code")
        return self

    def matches(self, signals: SafetySignals, phase: SafetyPhase) -> bool:
        values = signals.model_dump(mode="python")
        return (
            phase in self.phases
            and all(values[name] for name in self.trigger_all)
            and not any(values[name] for name in self.trigger_none)
        )


class SafetyBaselinePolicy(FrozenModel):
    policy_id: str = Field(pattern=r"^shidu-[a-z0-9-]+\.v[1-9][0-9]*$")
    rules: tuple[SafetyRule, ...] = Field(min_length=1)
    policy_digest: str = ""

    @model_validator(mode="after")
    def bind_policy(self) -> SafetyBaselinePolicy:
        if len({item.rule_id for item in self.rules}) != len(self.rules):
            raise ValueError("baseline safety rule ids must be unique")
        expected = canonical_digest(
            self.model_dump(mode="json", exclude={"policy_digest"})
        )
        if self.policy_digest and self.policy_digest != expected:
            raise ValueError("policy_digest does not match immutable safety baseline")
        object.__setattr__(self, "policy_digest", expected)
        return self


class SafetyCard(FrozenModel):
    card_id: str = Field(pattern=r"^shidu-[a-z0-9-]+-safety\.v[1-9][0-9]*$")
    card_version: str = Field(pattern=r"^v[1-9][0-9]*$")
    category: BookSafetyCategory
    title: str = Field(min_length=1, max_length=120)
    baseline_policy_id: str = SAFETY_BASELINE_POLICY_ID
    baseline_policy_digest: str = ""
    covered_risk_areas: tuple[SafetyRiskArea, ...] = Field(min_length=1)
    category_rules: tuple[SafetyRule, ...] = ()
    card_digest: str = ""

    @model_validator(mode="after")
    def bind_card(self) -> SafetyCard:
        expected_id = (
            f"shidu-{self.category.value.replace('_', '-')}-safety.{self.card_version}"
        )
        if self.card_id != expected_id:
            raise ValueError("card_id does not match category and version")
        baseline = safety_baseline_policy_v1()
        if self.baseline_policy_id != baseline.policy_id:
            raise ValueError("unknown safety baseline policy")
        if (
            self.baseline_policy_digest
            and self.baseline_policy_digest != baseline.policy_digest
        ):
            raise ValueError("baseline_policy_digest does not match safety baseline")
        if (
            len(set(self.covered_risk_areas)) != len(self.covered_risk_areas)
            or set(self.covered_risk_areas) != set(SafetyRiskArea)
        ):
            raise ValueError("card must cover every required safety risk area")
        baseline_areas = {item.risk_area for item in baseline.rules}
        if not set(self.covered_risk_areas).issubset(baseline_areas):
            raise ValueError("card claims a risk area absent from its baseline")
        if len({item.rule_id for item in self.category_rules}) != len(
            self.category_rules
        ):
            raise ValueError("category safety rule ids must be unique")
        object.__setattr__(self, "baseline_policy_digest", baseline.policy_digest)
        expected = canonical_digest(
            self.model_dump(mode="json", exclude={"card_digest"})
        )
        if self.card_digest and self.card_digest != expected:
            raise ValueError("card_digest does not match immutable safety card")
        object.__setattr__(self, "card_digest", expected)
        return self


class SafetyCardsManifest(FrozenModel):
    schema_version: str
    baseline_policy_id: str
    baseline_policy_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    card_ids: tuple[str, ...]
    card_digests: tuple[str, ...]
    aggregate_digest: str = ""

    @model_validator(mode="after")
    def bind_manifest(self) -> SafetyCardsManifest:
        if (
            len(self.card_ids) != 5
            or len(set(self.card_ids)) != 5
            or len(self.card_digests) != 5
            or len(set(self.card_digests)) != 5
        ):
            raise ValueError("safety manifest requires five unique cards")
        expected = canonical_digest(
            self.model_dump(mode="json", exclude={"aggregate_digest"})
        )
        if self.aggregate_digest and self.aggregate_digest != expected:
            raise ValueError("aggregate_digest does not match safety manifest")
        object.__setattr__(self, "aggregate_digest", expected)
        return self


class SafetyDecision(FrozenModel):
    category: BookSafetyCategory
    phase: SafetyPhase
    card_id: str
    card_version: str
    card_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    baseline_policy_id: str
    baseline_policy_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    evaluator_version: str
    content_revision_id: str
    content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    matched_rule_ids: tuple[str, ...]
    safety_warnings: tuple[str, ...]
    rewrite_requirements: tuple[str, ...]
    blocked_reason_codes: tuple[str, ...]
    required_human_review: bool
    decision_digest: str = ""

    @model_validator(mode="after")
    def bind_decision(self) -> SafetyDecision:
        sequences = (
            self.matched_rule_ids,
            self.safety_warnings,
            self.rewrite_requirements,
            self.blocked_reason_codes,
        )
        if any(len(items) != len(set(items)) for items in sequences):
            raise ValueError("safety decision outputs must be unique")
        if bool(self.blocked_reason_codes) != bool(self.matched_rule_ids):
            raise ValueError("blocked reasons must exactly follow matched rules")
        if self.blocked_reason_codes and not self.required_human_review:
            raise ValueError("blocked safety decisions require human review")
        expected = canonical_digest(
            self.model_dump(mode="json", exclude={"decision_digest"})
        )
        if self.decision_digest and self.decision_digest != expected:
            raise ValueError("decision_digest does not match immutable safety decision")
        object.__setattr__(self, "decision_digest", expected)
        return self


_ALL_PHASES = (SafetyPhase.PRE_COMPILE, SafetyPhase.POST_COMPILE)


def _rule(
    rule_id: str,
    risk_area: SafetyRiskArea,
    trigger_all: tuple[str, ...],
    code: str,
    warning: str,
    rewrite: str,
    *,
    trigger_none: tuple[str, ...] = (),
) -> SafetyRule:
    return SafetyRule(
        rule_id=rule_id,
        risk_area=risk_area,
        trigger_all=trigger_all,
        trigger_none=trigger_none,
        phases=_ALL_PHASES,
        warning=warning,
        rewrite_requirement=f"{code}: {rewrite}",
        blocked_reason_code=code,
        required_human_review=True,
    )


_BASELINE_POLICY = SafetyBaselinePolicy(
    policy_id=SAFETY_BASELINE_POLICY_ID,
    rules=(
        _rule(
            "shidu-core-spoiler.v1",
            SafetyRiskArea.CORE_SPOILERS,
            ("core_spoiler_revealed",),
            "core_spoiler_revealed",
            "内容揭示了决定阅读体验的核心结果。",
            "删除核心结果，只保留当下冲突与未解问题。",
        ),
        _rule(
            "shidu-graphic-violence.v1",
            SafetyRiskArea.VIOLENCE_SELF_HARM,
            ("graphic_violence",),
            "graphic_violence_uncontextualized",
            "内容包含不必要的具体暴力描写。",
            "降低暴力细节，以非猎奇方式表达必要情节。",
        ),
        _rule(
            "shidu-self-harm.v1",
            SafetyRiskArea.VIOLENCE_SELF_HARM,
            ("self_harm",),
            "self_harm_risk",
            "内容涉及自伤或自杀风险。",
            "移除方法细节和浪漫化表达，并提交人工安全复核。",
        ),
        _rule(
            "shidu-identifiable-minor.v1",
            SafetyRiskArea.MINORS,
            ("identifiable_minor",),
            "identifiable_minor_privacy_risk",
            "内容包含可识别未成年人的敏感信息。",
            "匿名化未成年人身份并删除非必要敏感信息。",
        ),
        _rule(
            "shidu-minor-sexualization.v1",
            SafetyRiskArea.MINORS,
            ("minor_sexualization",),
            "minor_sexualization",
            "内容含未成年人性化表达。",
            "删除未成年人性化表达，不得以改写规避该限制。",
        ),
        _rule(
            "shidu-tobacco-alcohol.v1",
            SafetyRiskArea.TOBACCO_ALCOHOL,
            ("tobacco_alcohol_glamorized",),
            "tobacco_alcohol_glamorization",
            "内容美化或鼓励烟酒使用。",
            "去除鼓励性呈现，并保留必要的风险语境。",
        ),
        _rule(
            "shidu-hate.v1",
            SafetyRiskArea.HATE,
            ("hate_or_dehumanization",),
            "hate_or_dehumanization",
            "内容包含针对受保护群体的仇恨或非人化表达。",
            "删除仇恨或非人化表达；历史引述必须限定语境。",
        ),
        _rule(
            "shidu-medical-misinformation.v1",
            SafetyRiskArea.MEDICAL_LEGAL_MISINFORMATION,
            ("unverified_medical_claim",),
            "unverified_medical_misinformation",
            "内容提出未经核验的医疗结论或建议。",
            "删除诊疗建议，或改为有证据限定的非建议性表述。",
        ),
        _rule(
            "shidu-legal-misinformation.v1",
            SafetyRiskArea.MEDICAL_LEGAL_MISINFORMATION,
            ("unverified_legal_claim",),
            "unverified_legal_misinformation",
            "内容提出未经核验的法律结论或建议。",
            "删除法律建议，或改为有证据限定的一般信息。",
        ),
        _rule(
            "shidu-reputational-claim.v1",
            SafetyRiskArea.MEDICAL_LEGAL_MISINFORMATION,
            ("unverified_defamation",),
            "unverified_reputational_claim",
            "内容包含针对可识别真实人物的未经核验负面指控。",
            "删除指控，或仅保留由可靠证据直接支持的中性事实。",
        ),
        _rule(
            "shidu-long-source-text.v1",
            SafetyRiskArea.IDENTIFIABLE_LONG_SOURCE_TEXT,
            ("identifiable_long_source_text",),
            "identifiable_long_source_text",
            "内容复用了可识别的长段来源原文。",
            "改为独立概括；仅保留已核验且必要的短引文。",
        ),
    ),
)


def safety_baseline_policy_v1() -> SafetyBaselinePolicy:
    return _BASELINE_POLICY


_COVERED_RISK_AREAS = tuple(SafetyRiskArea)


_CARDS = (
    SafetyCard(
        card_id="shidu-fiction-safety.v1",
        card_version="v1",
        category=BookSafetyCategory.FICTION,
        title="小说试读安全卡",
        covered_risk_areas=_COVERED_RISK_AREAS,
        category_rules=(
            _rule(
                "shidu-fiction-core-outcome.v1",
                SafetyRiskArea.CORE_SPOILERS,
                ("core_spoiler_revealed",),
                "core_fiction_outcome_revealed",
                "小说试读揭示了核心结局或未来结果。",
                "回到单一当下冲突，删除核心结局与未来结果。",
            ),
        ),
    ),
    SafetyCard(
        card_id="shidu-biography-safety.v1",
        card_version="v1",
        category=BookSafetyCategory.BIOGRAPHY,
        title="传记试读安全卡",
        covered_risk_areas=_COVERED_RISK_AREAS,
        category_rules=(
            _rule(
                "shidu-biography-defamation.v1",
                SafetyRiskArea.MEDICAL_LEGAL_MISINFORMATION,
                ("unverified_defamation",),
                "unverified_defamation",
                "传记内容包含针对可识别真实人物的未经核验负面指控。",
                "删除指控，或仅保留由可靠证据直接支持并正确归因的中性事实。",
            ),
        ),
    ),
    SafetyCard(
        card_id="shidu-history-nonfiction-safety.v1",
        card_version="v1",
        category=BookSafetyCategory.HISTORY_NONFICTION,
        title="历史与非虚构试读安全卡",
        covered_risk_areas=_COVERED_RISK_AREAS,
        category_rules=(
            _rule(
                "shidu-history-violence-context.v1",
                SafetyRiskArea.VIOLENCE_SELF_HARM,
                ("graphic_violence",),
                "historical_violence_without_context",
                "历史暴力被具体呈现但缺少必要语境。",
                "降低细节并补足中性历史语境，避免猎奇化。",
            ),
        ),
    ),
    SafetyCard(
        card_id="shidu-mystery-safety.v1",
        card_version="v1",
        category=BookSafetyCategory.MYSTERY,
        title="悬疑推理试读安全卡",
        covered_risk_areas=_COVERED_RISK_AREAS,
        category_rules=(
            _rule(
                "shidu-mystery-core-reveal.v1",
                SafetyRiskArea.CORE_SPOILERS,
                ("core_spoiler_revealed",),
                "core_mystery_revealed",
                "悬疑试读揭示了真凶、谜底或核心反转。",
                "删除真凶、谜底和核心反转，只保留线索与未解问题。",
            ),
        ),
    ),
    SafetyCard(
        card_id="shidu-youth-romance-safety.v1",
        card_version="v1",
        category=BookSafetyCategory.YOUTH_ROMANCE,
        title="青春情感试读安全卡",
        covered_risk_areas=_COVERED_RISK_AREAS,
        category_rules=(
            _rule(
                "shidu-youth-minor-self-harm.v1",
                SafetyRiskArea.VIOLENCE_SELF_HARM,
                ("self_harm", "subject_is_minor"),
                "minor_self_harm_risk",
                "青春情感内容涉及未成年人自伤风险。",
                "移除方法细节和浪漫化表达，并提交未成年人安全人工复核。",
            ),
        ),
    ),
)


def safety_cards_v1() -> tuple[SafetyCard, ...]:
    return _CARDS


def safety_cards_manifest() -> SafetyCardsManifest:
    baseline = safety_baseline_policy_v1()
    return SafetyCardsManifest(
        schema_version=SAFETY_CARD_SCHEMA_VERSION,
        baseline_policy_id=baseline.policy_id,
        baseline_policy_digest=baseline.policy_digest,
        card_ids=tuple(item.card_id for item in _CARDS),
        card_digests=tuple(item.card_digest for item in _CARDS),
    )


class SafetyCardService:
    def __init__(
        self,
        *,
        cards: tuple[SafetyCard, ...] | None = None,
        baseline_policy: SafetyBaselinePolicy | None = None,
    ) -> None:
        self._baseline = baseline_policy or safety_baseline_policy_v1()
        selected = cards or safety_cards_v1()
        if (
            len(selected) != len(BookSafetyCategory)
            or {item.category for item in selected} != set(BookSafetyCategory)
            or len({item.card_id for item in selected}) != len(selected)
            or any(
                item.baseline_policy_id != self._baseline.policy_id
                or item.baseline_policy_digest != self._baseline.policy_digest
                for item in selected
            )
        ):
            raise SafetyEvaluationError("safety card set is incomplete or inconsistent")
        self._cards = {item.category: item for item in selected}

    def evaluate(
        self,
        category: BookSafetyCategory | str,
        content: SafetyContent | Mapping[str, Any],
        *,
        phase: SafetyPhase | str = SafetyPhase.POST_COMPILE,
    ) -> SafetyDecision:
        try:
            resolved_category = BookSafetyCategory(category)
        except (TypeError, ValueError) as error:
            raise SafetyEvaluationError("unknown safety category") from error
        try:
            resolved_phase = SafetyPhase(phase)
        except (TypeError, ValueError) as error:
            raise SafetyEvaluationError("unknown safety phase") from error
        try:
            resolved_content = (
                content
                if isinstance(content, SafetyContent)
                else SafetyContent.model_validate(content)
            )
        except (TypeError, ValidationError) as error:
            raise SafetyEvaluationError("malformed safety content") from error

        card = self._cards[resolved_category]
        category_matches = tuple(
            rule
            for rule in card.category_rules
            if rule.matches(resolved_content.signals, resolved_phase)
        )
        consumed_signals = {
            signal for rule in category_matches for signal in rule.trigger_all
        }
        baseline_matches = tuple(
            rule
            for rule in self._baseline.rules
            if not (set(rule.trigger_all) & consumed_signals)
            and rule.matches(resolved_content.signals, resolved_phase)
        )
        matched = (*category_matches, *baseline_matches)

        return SafetyDecision(
            category=resolved_category,
            phase=resolved_phase,
            card_id=card.card_id,
            card_version=card.card_version,
            card_digest=card.card_digest,
            baseline_policy_id=self._baseline.policy_id,
            baseline_policy_digest=self._baseline.policy_digest,
            evaluator_version=SAFETY_CARD_EVALUATOR_VERSION,
            content_revision_id=resolved_content.content_revision_id,
            content_digest=resolved_content.content_digest,
            input_digest=resolved_content.input_digest,
            matched_rule_ids=tuple(item.rule_id for item in matched),
            safety_warnings=tuple(item.warning for item in matched),
            rewrite_requirements=tuple(item.rewrite_requirement for item in matched),
            blocked_reason_codes=tuple(item.blocked_reason_code for item in matched),
            required_human_review=any(
                item.required_human_review for item in matched
            ),
        )


__all__ = [
    "SAFETY_BASELINE_POLICY_ID",
    "SAFETY_CARD_EVALUATOR_VERSION",
    "SAFETY_CARD_SCHEMA_VERSION",
    "BookSafetyCategory",
    "SafetyBaselinePolicy",
    "SafetyCard",
    "SafetyCardService",
    "SafetyCardsManifest",
    "SafetyContent",
    "SafetyDecision",
    "SafetyEvaluationError",
    "SafetyPhase",
    "SafetyRiskArea",
    "SafetyRule",
    "SafetySignalEvidence",
    "SafetySignals",
    "safety_baseline_policy_v1",
    "safety_cards_manifest",
    "safety_cards_v1",
]
