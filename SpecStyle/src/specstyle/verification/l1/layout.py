"""L1 layout soft rules: subject bbox vs safe zone."""

from __future__ import annotations

from dataclasses import dataclass

from specstyle.domain.enums import RuleStatus
from specstyle.domain.identifiers import ArtifactId, RuleId
from specstyle.errors import DomainError
from specstyle.verification.rule_models import RuleResult

RULE_LAYOUT = RuleId("L1_LAYOUT")


@dataclass(frozen=True, slots=True)
class BBox:
    """Normalized [0,1] inclusive box: x0,y0,x1,y1."""

    x0: float
    y0: float
    x1: float
    y1: float

    def __post_init__(self) -> None:
        for name in ("x0", "y0", "x1", "y1"):
            value = getattr(self, name)
            if type(value) is not float or not 0.0 <= value <= 1.0:
                raise DomainError("invalid bbox")
        if self.x1 < self.x0 or self.y1 < self.y0:
            raise DomainError("invalid bbox")


@dataclass(frozen=True, slots=True)
class SafeZone:
    x0: float
    y0: float
    x1: float
    y1: float

    def __post_init__(self) -> None:
        for name in ("x0", "y0", "x1", "y1"):
            value = getattr(self, name)
            if type(value) is not float or not 0.0 <= value <= 1.0:
                raise DomainError("invalid safe zone")
        if self.x1 < self.x0 or self.y1 < self.y0:
            raise DomainError("invalid safe zone")


def check_layout(
    artifact_id: ArtifactId,
    bboxes: tuple[BBox, ...] | None,
    safe_zone: SafeZone,
    /,
    *,
    missing_policy: str = "unverifiable",
) -> RuleResult:
    """If bboxes is None → UNVERIFIABLE or WARNING; empty → FAIL; outside safe → FAIL."""
    if missing_policy not in ("unverifiable", "warning"):
        raise DomainError("invalid missing bbox policy")
    if bboxes is None:
        status = (
            RuleStatus.UNVERIFIABLE
            if missing_policy == "unverifiable"
            else RuleStatus.WARNING
        )
        return RuleResult(RULE_LAYOUT, status, (artifact_id,), None)
    if type(bboxes) is not tuple or not bboxes:
        return RuleResult(RULE_LAYOUT, RuleStatus.FAIL, (artifact_id,), 0.0)
    for box in bboxes:
        if type(box) is not BBox:
            raise DomainError("invalid bbox")
        if (
            box.x0 < safe_zone.x0
            or box.y0 < safe_zone.y0
            or box.x1 > safe_zone.x1
            or box.y1 > safe_zone.y1
        ):
            return RuleResult(RULE_LAYOUT, RuleStatus.FAIL, (artifact_id,), 0.0)
    return RuleResult(RULE_LAYOUT, RuleStatus.PASS, (artifact_id,), 1.0)
