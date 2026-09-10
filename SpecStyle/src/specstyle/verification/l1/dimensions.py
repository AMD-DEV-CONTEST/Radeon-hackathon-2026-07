"""L1 dimension hard rules: exact size and ratio."""

from __future__ import annotations

from specstyle.domain.enums import RuleStatus
from specstyle.domain.identifiers import ArtifactId, RuleId
from specstyle.errors import DomainError
from specstyle.verification.l1.decode import DecodedImage, decode_png_bytes
from specstyle.verification.rule_models import RuleResult

RULE_DIMENSIONS = RuleId("L1_DIMENSIONS")


def check_dimensions(
    artifact_id: ArtifactId,
    data: bytes,
    expected: tuple[int, int],
    /,
) -> RuleResult:
    if (
        type(expected) is not tuple
        or len(expected) != 2
        or type(expected[0]) is not int
        or type(expected[1]) is not int
        or isinstance(expected[0], bool)
        or isinstance(expected[1], bool)
        or expected[0] < 1
        or expected[1] < 1
    ):
        raise DomainError("invalid expected dimensions")
    try:
        decoded = decode_png_bytes(data)
    except DomainError:
        return RuleResult(
            RULE_DIMENSIONS, RuleStatus.UNVERIFIABLE, (artifact_id,), None
        )
    if decoded.size != expected:
        return RuleResult(RULE_DIMENSIONS, RuleStatus.FAIL, (artifact_id,), 0.0)
    return RuleResult(RULE_DIMENSIONS, RuleStatus.PASS, (artifact_id,), 1.0)


def check_dimensions_decoded(
    artifact_id: ArtifactId,
    decoded: DecodedImage,
    expected: tuple[int, int],
    /,
) -> RuleResult:
    if decoded.size != expected:
        return RuleResult(RULE_DIMENSIONS, RuleStatus.FAIL, (artifact_id,), 0.0)
    return RuleResult(RULE_DIMENSIONS, RuleStatus.PASS, (artifact_id,), 1.0)
