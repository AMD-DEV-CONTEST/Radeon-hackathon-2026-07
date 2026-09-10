"""Product local feature composite (CPU fake path, no ROCm)."""

from __future__ import annotations

from specstyle.domain.enums import RuleStatus
from specstyle.domain.identifiers import ArtifactId, RuleId, Sha256
from specstyle.errors import DomainError
from specstyle.observability.hashing import hash_bytes
from specstyle.verification.l3.mask_provider import (
    Mask,
    MaskProvider,
    validate_mask_for_image,
)
from specstyle.verification.rule_models import RuleResult

RULE_PRODUCT_FEATURES = RuleId("L3_PRODUCT_FEATURES")


def masked_feature_fingerprint(image_bytes: bytes, mask: Mask) -> Sha256:
    if type(image_bytes) is not bytes or type(mask) is not Mask:
        raise DomainError("invalid feature inputs")
    # Deterministic: hash image + mask bytes (CPU-safe composite proxy).
    return hash_bytes(image_bytes + bytes(mask.data))


def evaluate_product_features(
    artifact_id: ArtifactId,
    image_bytes: bytes | None,
    mask_provider: MaskProvider,
    reference_image: bytes | None,
    reference_mask_provider: MaskProvider,
    image_size: tuple[int, int],
    *,
    min_similarity: float = 1.0,
) -> RuleResult:
    if image_bytes is None or reference_image is None:
        return RuleResult(
            RULE_PRODUCT_FEATURES, RuleStatus.UNVERIFIABLE, (artifact_id,), None
        )
    mask = mask_provider.get_mask(artifact_id)
    ref_mask = reference_mask_provider.get_mask(artifact_id)
    if (
        validate_mask_for_image(mask, image_size) is not None
        or validate_mask_for_image(ref_mask, image_size) is not None
    ):
        return RuleResult(
            RULE_PRODUCT_FEATURES, RuleStatus.UNVERIFIABLE, (artifact_id,), None
        )
    assert mask is not None and ref_mask is not None
    a = masked_feature_fingerprint(image_bytes, mask)
    b = masked_feature_fingerprint(reference_image, ref_mask)
    # Exact fingerprint match → 1.0; else 0.0 (fake composite for CPU tests).
    score = 1.0 if a == b else 0.0
    status = RuleStatus.PASS if score >= min_similarity else RuleStatus.FAIL
    return RuleResult(RULE_PRODUCT_FEATURES, status, (artifact_id,), score)
