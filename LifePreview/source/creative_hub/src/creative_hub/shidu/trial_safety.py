"""Application-owned signal detection and fail-closed Shidu safety gates."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import Field, model_validator

from creative_hub.db.canonical import canonical_json_digest
from creative_hub.quality import FrozenModel, canonical_digest
from creative_hub.shidu.safety_cards import (
    BookSafetyCategory,
    SafetyCardService,
    SafetyContent,
    SafetyDecision,
    SafetyPhase,
    safety_cards_manifest,
)


TRIAL_SAFETY_DETECTOR_VERSION = "shidu-trial-safety-detector.v1"
TRIAL_SAFETY_GATE_SCHEMA_VERSION = "shidu-trial-safety-gate.v1"


class TrialSafetyError(ValueError):
    """Safety signals or their frozen release projection are invalid."""


class TrialSafetyGate(FrozenModel):
    schema_version: str = TRIAL_SAFETY_GATE_SCHEMA_VERSION
    primary_category: BookSafetyCategory
    phase: SafetyPhase
    safety_cards_manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    detector_version: str = TRIAL_SAFETY_DETECTOR_VERSION
    content_revision_id: str = Field(min_length=1, max_length=200)
    content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    decisions: tuple[SafetyDecision, ...] = Field(min_length=5, max_length=5)
    blocked_reason_codes: tuple[str, ...]
    safety_warnings: tuple[str, ...]
    rewrite_requirements: tuple[str, ...]
    required_human_review: bool
    release_decision_digest: str = ""

    @model_validator(mode="after")
    def bind_release_truth(self) -> TrialSafetyGate:
        if self.schema_version != TRIAL_SAFETY_GATE_SCHEMA_VERSION:
            raise ValueError("trial safety gate schema is unsupported")
        if self.detector_version != TRIAL_SAFETY_DETECTOR_VERSION:
            raise ValueError("trial safety detector version is unsupported")
        manifest = safety_cards_manifest()
        if self.safety_cards_manifest_digest != manifest.aggregate_digest:
            raise ValueError("trial safety cards manifest digest is invalid")
        if tuple(item.category for item in self.decisions) != tuple(
            BookSafetyCategory
        ):
            raise ValueError("trial safety gate requires all five card decisions")
        if any(
            item.phase is not self.phase
            or item.content_revision_id != self.content_revision_id
            or item.content_digest != self.content_digest
            for item in self.decisions
        ):
            raise ValueError("trial safety decisions do not bind one content fact")
        expected_codes = tuple(
            sorted(
                {
                    code
                    for item in self.decisions
                    for code in item.blocked_reason_codes
                }
            )
        )
        expected_warnings = tuple(
            sorted(
                {
                    warning
                    for item in self.decisions
                    for warning in item.safety_warnings
                }
            )
        )
        expected_rewrites = tuple(
            sorted(
                {
                    requirement
                    for item in self.decisions
                    for requirement in item.rewrite_requirements
                }
            )
        )
        if (
            self.blocked_reason_codes != expected_codes
            or self.safety_warnings != expected_warnings
            or self.rewrite_requirements != expected_rewrites
            or self.required_human_review != bool(expected_codes)
        ):
            raise ValueError("trial safety release projection is inconsistent")
        expected = canonical_digest(
            self.model_dump(mode="json", exclude={"release_decision_digest"})
        )
        if (
            self.release_decision_digest
            and self.release_decision_digest != expected
        ):
            raise ValueError("trial safety release decision digest is invalid")
        object.__setattr__(self, "release_decision_digest", expected)
        return self


class TrialScriptSafety(FrozenModel):
    schema_version: str = "shidu-script-safety.v1"
    primary_category: BookSafetyCategory
    safety_cards_manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    pre_compile: TrialSafetyGate
    post_compile: TrialSafetyGate
    release_decision_digest: str = ""

    @model_validator(mode="after")
    def bind_script_release(self) -> TrialScriptSafety:
        manifest_digest = safety_cards_manifest().aggregate_digest
        if (
            self.schema_version != "shidu-script-safety.v1"
            or self.safety_cards_manifest_digest != manifest_digest
            or self.pre_compile.primary_category is not self.primary_category
            or self.post_compile.primary_category is not self.primary_category
            or self.pre_compile.phase is not SafetyPhase.PRE_COMPILE
            or self.post_compile.phase is not SafetyPhase.POST_COMPILE
            or self.pre_compile.safety_cards_manifest_digest != manifest_digest
            or self.post_compile.safety_cards_manifest_digest != manifest_digest
        ):
            raise ValueError("trial script safety gates are inconsistent")
        expected = canonical_digest(
            {
                "schema_version": self.schema_version,
                "primary_category": self.primary_category.value,
                "safety_cards_manifest_digest": manifest_digest,
                "pre_compile_decision_digest": (
                    self.pre_compile.release_decision_digest
                ),
                "post_compile_decision_digest": (
                    self.post_compile.release_decision_digest
                ),
            }
        )
        if self.release_decision_digest and self.release_decision_digest != expected:
            raise ValueError("trial script safety release digest is invalid")
        object.__setattr__(self, "release_decision_digest", expected)
        return self


_SIGNAL_TERMS: dict[str, tuple[str, ...]] = {
    "core_spoiler_revealed": (
        "真凶是",
        "凶手就是",
        "谜底是",
        "结局是",
        "最终反转",
    ),
    "graphic_violence": ("肢解", "血浆四溅", "虐杀细节", "开膛"),
    "self_harm": ("割腕", "自杀方法", "跳楼自杀", "服药自杀"),
    "subject_is_minor": ("未成年人", "未成年", "十六岁", "高中生"),
    "identifiable_minor": ("实名未成年人", "未成年人的姓名"),
    "minor_sexualization": ("性化未成年人", "未成年情色"),
    "tobacco_alcohol_glamorized": ("抽烟很酷", "喝酒才成熟", "酗酒很迷人"),
    "hate_or_dehumanization": ("应当消灭这个族群", "不是人类的族群"),
    "unverified_medical_claim": ("停药即可治愈", "保证治愈", "无需就医"),
    "unverified_legal_claim": ("保证胜诉", "一定无罪", "无需律师"),
    "unverified_defamation": ("未经证实的贪污", "未经证实的犯罪指控"),
}


def _strings(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Mapping):
        return tuple(
            text
            for key, item in value.items()
            if key not in {"safety_gate", "safety_rewrite_provenance"}
            for text in _strings(item)
        )
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return tuple(text for item in value for text in _strings(item))
    return ()


def _without_none(value: object) -> object:
    """Match Pydantic's canonical ``exclude_none`` representation."""

    if isinstance(value, Mapping):
        return {
            key: _without_none(item)
            for key, item in value.items()
            if item is not None
        }
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return [_without_none(item) for item in value]
    return value


def _contains_source_span(
    texts: tuple[str, ...],
    source_passages: Sequence[str],
    *,
    limit: int = 20,
) -> bool:
    normalized_texts = tuple("".join(item.split()) for item in texts)
    for source in source_passages:
        normalized_source = "".join(str(source).split())
        if len(normalized_source) < limit:
            continue
        for index in range(len(normalized_source) - limit + 1):
            span = normalized_source[index : index + limit]
            if any(span in text for text in normalized_texts):
                return True
    return False


def detect_trial_safety_content(
    *,
    content_revision_id: str,
    content: Mapping[str, Any],
    source_passages: Sequence[str] = (),
) -> SafetyContent:
    """Extract bounded application-owned signals from immutable content."""

    if not isinstance(content, Mapping):
        raise TrialSafetyError("trial safety content must be an object")
    material = _without_none(
        {
            key: value
            for key, value in content.items()
            if key not in {"safety_gate", "safety_rewrite_provenance"}
        }
    )
    assert isinstance(material, dict)
    texts = _strings(material)
    joined = "\n".join(texts).casefold()
    signals = {
        signal: any(term.casefold() in joined for term in terms)
        for signal, terms in _SIGNAL_TERMS.items()
    }
    signals["identifiable_long_source_text"] = _contains_source_span(
        texts,
        source_passages,
    )
    evidence = {
        signal: [f"{TRIAL_SAFETY_DETECTOR_VERSION}:{signal}"]
        for signal, active in signals.items()
        if active
    }
    return SafetyContent(
        content_revision_id=content_revision_id,
        content_digest=canonical_json_digest(material),
        signals=signals,
        signal_evidence_refs=evidence,
    )


class TrialSafetyGateService:
    """Evaluate every card so a caller-selected category cannot weaken policy."""

    def __init__(self, cards: SafetyCardService | None = None) -> None:
        self._cards = cards or SafetyCardService()

    def evaluate(
        self,
        *,
        primary_category: BookSafetyCategory | str,
        phase: SafetyPhase | str,
        content_revision_id: str,
        content: Mapping[str, Any],
        source_passages: Sequence[str] = (),
    ) -> TrialSafetyGate:
        try:
            category = BookSafetyCategory(primary_category)
            resolved_phase = SafetyPhase(phase)
        except (TypeError, ValueError) as exc:
            raise TrialSafetyError("trial safety category or phase is invalid") from exc
        detected = detect_trial_safety_content(
            content_revision_id=content_revision_id,
            content=content,
            source_passages=source_passages,
        )
        decisions = tuple(
            self._cards.evaluate(item, detected, phase=resolved_phase)
            for item in BookSafetyCategory
        )
        codes = tuple(
            sorted({code for item in decisions for code in item.blocked_reason_codes})
        )
        warnings = tuple(
            sorted({value for item in decisions for value in item.safety_warnings})
        )
        rewrites = tuple(
            sorted(
                {
                    value
                    for item in decisions
                    for value in item.rewrite_requirements
                }
            )
        )
        return TrialSafetyGate(
            primary_category=category,
            phase=resolved_phase,
            safety_cards_manifest_digest=(
                safety_cards_manifest().aggregate_digest
            ),
            content_revision_id=detected.content_revision_id,
            content_digest=detected.content_digest,
            decisions=decisions,
            blocked_reason_codes=codes,
            safety_warnings=warnings,
            rewrite_requirements=rewrites,
            required_human_review=bool(codes),
        )


def require_trial_script_release(
    payload: Mapping[str, Any],
) -> TrialScriptSafety:
    """Return trusted safety truth only when a script may enter workflow."""

    try:
        safety = TrialScriptSafety.model_validate(payload.get("safety_gate"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise TrialSafetyError("trial script safety truth is missing or invalid") from exc
    if (
        safety.pre_compile.blocked_reason_codes
        or safety.pre_compile.required_human_review
        or safety.post_compile.blocked_reason_codes
        or safety.post_compile.required_human_review
    ):
        raise TrialSafetyError("trial script safety gate blocks workflow release")
    return safety


__all__ = [
    "TRIAL_SAFETY_DETECTOR_VERSION",
    "TRIAL_SAFETY_GATE_SCHEMA_VERSION",
    "TrialSafetyError",
    "TrialSafetyGate",
    "TrialSafetyGateService",
    "TrialScriptSafety",
    "detect_trial_safety_content",
    "require_trial_script_release",
]
