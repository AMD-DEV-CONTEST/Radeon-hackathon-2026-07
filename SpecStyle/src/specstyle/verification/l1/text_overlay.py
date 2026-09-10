"""L1 text overlay soft rules: content match, truncation, soft quality warnings."""

from __future__ import annotations

from dataclasses import dataclass

from specstyle.domain.enums import RuleStatus
from specstyle.domain.identifiers import ArtifactId, RuleId
from specstyle.errors import DomainError
from specstyle.verification.rule_models import RuleResult

RULE_TEXT = RuleId("L1_TEXT")
RULE_SOFT_QUALITY = RuleId("L1_SOFT_QUALITY")


@dataclass(frozen=True, slots=True)
class TextOverlaySpec:
    expected_text: str
    max_chars: int
    rendered_text: str | None

    def __post_init__(self) -> None:
        if type(self.expected_text) is not str or type(self.max_chars) is not int:
            raise DomainError("invalid text overlay")
        if isinstance(self.max_chars, bool) or self.max_chars < 1:
            raise DomainError("invalid text overlay")
        if self.rendered_text is not None and type(self.rendered_text) is not str:
            raise DomainError("invalid text overlay")


def check_text_overlay(artifact_id: ArtifactId, spec: TextOverlaySpec, /) -> RuleResult:
    if type(spec) is not TextOverlaySpec:
        raise DomainError("invalid text overlay")
    if spec.rendered_text is None:
        return RuleResult(RULE_TEXT, RuleStatus.UNVERIFIABLE, (artifact_id,), None)
    if len(spec.rendered_text) > spec.max_chars:
        return RuleResult(RULE_TEXT, RuleStatus.FAIL, (artifact_id,), 0.0)
    if spec.rendered_text != spec.expected_text:
        return RuleResult(RULE_TEXT, RuleStatus.FAIL, (artifact_id,), 0.0)
    return RuleResult(RULE_TEXT, RuleStatus.PASS, (artifact_id,), 1.0)


def soft_quality_warnings(
    artifact_id: ArtifactId,
    *,
    blur_score: float | None,
    exposure_score: float | None,
    contrast_score: float | None,
) -> RuleResult:
    """Advisory soft metrics: missing → WARNING, out of [0,1] band → WARNING."""

    def _ok(value: float | None) -> bool:
        if value is None:
            return False
        if type(value) is not float:
            raise DomainError("invalid soft metric")
        return 0.15 <= value <= 0.95

    if not _ok(blur_score) or not _ok(exposure_score) or not _ok(contrast_score):
        return RuleResult(RULE_SOFT_QUALITY, RuleStatus.WARNING, (artifact_id,), None)
    return RuleResult(RULE_SOFT_QUALITY, RuleStatus.PASS, (artifact_id,), 1.0)
