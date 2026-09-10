"""L1 pixel hard rules: min size, all black/white, empty content."""

from __future__ import annotations

from specstyle.domain.enums import RuleStatus
from specstyle.domain.identifiers import ArtifactId, RuleId
from specstyle.errors import DomainError
from specstyle.verification.l1.decode import DecodedImage, decode_png_bytes
from specstyle.verification.rule_models import RuleResult

RULE_PIXELS = RuleId("L1_PIXELS")
_MIN_EDGE = 8


def check_pixels(artifact_id: ArtifactId, data: bytes, /) -> RuleResult:
    try:
        decoded = decode_png_bytes(data)
    except DomainError:
        return RuleResult(RULE_PIXELS, RuleStatus.UNVERIFIABLE, (artifact_id,), None)
    return check_pixels_decoded(artifact_id, decoded)


def check_pixels_decoded(
    artifact_id: ArtifactId, decoded: DecodedImage, /
) -> RuleResult:
    w, h = decoded.size
    if w < _MIN_EDGE or h < _MIN_EDGE:
        return RuleResult(RULE_PIXELS, RuleStatus.FAIL, (artifact_id,), 0.0)
    if not decoded.pixels_rgb:
        return RuleResult(RULE_PIXELS, RuleStatus.FAIL, (artifact_id,), 0.0)
    if all(p == (0, 0, 0) for p in decoded.pixels_rgb):
        return RuleResult(RULE_PIXELS, RuleStatus.FAIL, (artifact_id,), 0.0)
    if all(p == (255, 255, 255) for p in decoded.pixels_rgb):
        return RuleResult(RULE_PIXELS, RuleStatus.FAIL, (artifact_id,), 0.0)
    return RuleResult(RULE_PIXELS, RuleStatus.PASS, (artifact_id,), 1.0)
