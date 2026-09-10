"""Product geometry verifier: mask IoU / coverage / safe-zone crop."""

from __future__ import annotations

from specstyle.domain.enums import RuleStatus
from specstyle.domain.identifiers import ArtifactId, RuleId
from specstyle.errors import DomainError
from specstyle.verification.l3.base import DomainContext, DomainPlugin
from specstyle.verification.l3.mask_provider import (
    Mask,
    MaskProvider,
    validate_mask_for_image,
)
from specstyle.verification.rule_models import RuleResult

RULE_PRODUCT_GEOMETRY = RuleId("L3_PRODUCT_GEOMETRY")


def mask_iou(a: Mask, b: Mask) -> float:
    if a.width != b.width or a.height != b.height:
        raise DomainError("mask size mismatch")
    inter = 0
    union = 0
    for x, y in zip(a.data, b.data, strict=True):
        if x or y:
            union += 1
        if x and y:
            inter += 1
    if union == 0:
        return 0.0
    return inter / union


def subject_coverage(mask: Mask) -> float:
    return mask.foreground_count() / float(mask.width * mask.height)


class ProductGeometryPlugin:
    plugin_id = "product_geometry"
    supported_domains = ("product_instance",)

    def __init__(
        self,
        masks: MaskProvider,
        reference_masks: MaskProvider,
        image_size: tuple[int, int],
        *,
        min_iou: float = 0.5,
        min_coverage: float = 0.05,
        max_coverage: float = 0.95,
    ) -> None:
        self._masks = masks
        self._refs = reference_masks
        self._size = image_size
        self._min_iou = min_iou
        self._min_cov = min_coverage
        self._max_cov = max_coverage

    def applicability(self, context: DomainContext, /) -> str:
        if context.domain_profile != "product_instance":
            return "NOT_APPLICABLE"
        return "APPLICABLE"

    def verify(self, artifact_id: ArtifactId, context: DomainContext, /) -> RuleResult:
        if self.applicability(context) != "APPLICABLE":
            raise DomainError("plugin not applicable")
        mask = self._masks.get_mask(artifact_id)
        reason = validate_mask_for_image(mask, self._size)
        if reason is not None:
            return RuleResult(
                RULE_PRODUCT_GEOMETRY, RuleStatus.UNVERIFIABLE, (artifact_id,), None
            )
        assert mask is not None
        cov = subject_coverage(mask)
        if cov < self._min_cov or cov > self._max_cov:
            return RuleResult(
                RULE_PRODUCT_GEOMETRY, RuleStatus.FAIL, (artifact_id,), cov
            )
        ref = self._refs.get_mask(artifact_id)
        if ref is None:
            # Mask reference unavailable → UNVERIFIABLE (never silent PASS).
            return RuleResult(
                RULE_PRODUCT_GEOMETRY, RuleStatus.UNVERIFIABLE, (artifact_id,), cov
            )
        ref_reason = validate_mask_for_image(ref, self._size)
        if ref_reason is not None:
            return RuleResult(
                RULE_PRODUCT_GEOMETRY, RuleStatus.UNVERIFIABLE, (artifact_id,), None
            )
        iou = mask_iou(mask, ref)
        if iou < self._min_iou:
            return RuleResult(
                RULE_PRODUCT_GEOMETRY, RuleStatus.FAIL, (artifact_id,), iou
            )
        return RuleResult(RULE_PRODUCT_GEOMETRY, RuleStatus.PASS, (artifact_id,), iou)


# Protocol satisfaction
_: DomainPlugin = ProductGeometryPlugin  # type: ignore[assignment,misc]
