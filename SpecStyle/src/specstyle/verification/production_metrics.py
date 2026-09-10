"""Private CPU metric primitives for the production verifier."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from specstyle.domain.enums import RuleStatus
from specstyle.domain.identifiers import ArtifactId
from specstyle.spec.compiled_models import CompiledRule
from specstyle.verification.l1.production_bindings import (
    _ProductionL1Implementation as _L1Implementation,
)
from specstyle.verification.rule_models import RuleResult

__all__ = ()


class _MetricContractViolation(Exception):
    pass


def _unverifiable_result(rule: CompiledRule, artifact_id: ArtifactId) -> RuleResult:
    return RuleResult(
        rule.definition.rule_id, RuleStatus.UNVERIFIABLE, (artifact_id,), None
    )


@dataclass(frozen=True, slots=True)
class _MetricOutcome:
    status: RuleStatus
    score: float | None


@dataclass(frozen=True, slots=True)
class _ThresholdOutcome:
    status: RuleStatus | None
    score: float | None
    execute: bool


def _canonical_score(value: float) -> float:
    return 0.0 if value == 0.0 else value


def _l1_outcome(
    implementation: str,
    decode_succeeded: bool,
    dimensions_status: RuleStatus | None,
    pixels_status: RuleStatus | None,
    /,
) -> _MetricOutcome:
    valid_primitive_statuses = {RuleStatus.PASS, RuleStatus.FAIL}
    try:
        selected = _L1Implementation(implementation)
        valid = (
            type(implementation) is str
            and type(decode_succeeded) is bool
            and (
                not decode_succeeded
                or (
                    dimensions_status in valid_primitive_statuses
                    and pixels_status in valid_primitive_statuses
                )
            )
            and (
                decode_succeeded
                or (dimensions_status is None and pixels_status is None)
            )
        )
    except (TypeError, ValueError):
        selected, valid = None, False
    if not valid:
        raise _MetricContractViolation
    if not decode_succeeded:
        status = (
            RuleStatus.FAIL
            if selected in {_L1Implementation.DECODE, _L1Implementation.BUNDLE}
            else RuleStatus.UNVERIFIABLE
        )
        return _MetricOutcome(status, None)
    status = {
        _L1Implementation.DECODE: RuleStatus.PASS,
        _L1Implementation.DIMENSIONS: dimensions_status,
        _L1Implementation.PIXELS: pixels_status,
        _L1Implementation.BUNDLE: (
            RuleStatus.PASS
            if dimensions_status is RuleStatus.PASS and pixels_status is RuleStatus.PASS
            else RuleStatus.FAIL
        ),
    }[selected]
    return _MetricOutcome(status, 1.0 if status is RuleStatus.PASS else 0.0)


def _shape(value: object) -> tuple[int, ...] | None:
    try:
        shape = tuple(value.shape)  # type: ignore[union-attr]
    except Exception:
        return None
    return shape if all(type(edge) is int and edge > 0 for edge in shape) else None


def _finite(torch: Any, value: Any) -> bool:
    try:
        return torch.isfinite(value).all().item() is True
    except Exception:
        return False


def _float64_tensor(torch: Any, value: object, ndim: int) -> Any:
    shape = _shape(value)
    cpu = torch.device("cpu")
    try:
        valid = (
            type(value) is torch.Tensor
            and shape is not None
            and len(shape) == ndim
            and type(value.device) is torch.device
            and value.device == cpu
            and value.dtype is torch.float32
            and value.is_contiguous() is True
            and value.requires_grad is False
            and _finite(torch, value)
        )
        converted = value.to(device=cpu, dtype=torch.float64) if valid else None
        valid = valid and (
            type(converted) is torch.Tensor
            and _shape(converted) == shape
            and converted.device == cpu
            and converted.dtype is torch.float64
            and converted.is_contiguous() is True
            and converted.requires_grad is False
            and _finite(torch, converted)
        )
    except Exception:
        valid = False
        converted = None
    if not valid:
        raise _MetricContractViolation
    return converted


def _normalize(torch: Any, value: Any) -> Any:
    try:
        norm = torch.linalg.vector_norm(value).item()
        if type(norm) is not float or not math.isfinite(norm) or norm <= 0.0:
            raise _MetricContractViolation
        normalized = value / norm
        if not _finite(torch, normalized):
            raise _MetricContractViolation
        return normalized
    except _MetricContractViolation:
        raise
    except Exception:
        raise _MetricContractViolation from None


def _patch_feature(torch: Any, patch: object) -> Any:
    value = _float64_tensor(torch, patch, 2)
    try:
        feature = torch.cat((value.mean(dim=0), value.std(dim=0, correction=0)), dim=0)
    except Exception:
        raise _MetricContractViolation from None
    if _shape(feature) != (value.shape[1] * 2,):
        raise _MetricContractViolation
    return _normalize(torch, feature)


def _cosine(torch: Any, left: Any, right: Any) -> float:
    if _shape(left) != _shape(right):
        raise _MetricContractViolation
    try:
        score = torch.dot(left, right).item()
    except Exception:
        raise _MetricContractViolation from None
    if type(score) is not float or not math.isfinite(score):
        raise _MetricContractViolation
    return _canonical_score(max(-1.0, min(1.0, score)))


def _median(values: tuple[float, ...]) -> float:
    if not values or any(type(value) is not float for value in values):
        raise _MetricContractViolation
    ordered = tuple(sorted(values))
    middle = len(ordered) // 2
    median = (
        ordered[middle]
        if len(ordered) % 2
        else (ordered[middle - 1] + ordered[middle]) / 2.0
    )
    return _canonical_score(median)


def _l2_similarity(
    torch: Any,
    output_patch: object,
    reference_patches: tuple[object, ...],
    /,
) -> float:
    if type(reference_patches) is not tuple or not reference_patches:
        raise _MetricContractViolation
    output = _patch_feature(torch, output_patch)
    scores = tuple(
        _cosine(torch, output, _patch_feature(torch, reference))
        for reference in reference_patches
    )
    return _median(scores)


def _l3_similarity(
    torch: Any, output_projected: object, source_projected: object, /
) -> float:
    output = _normalize(torch, _float64_tensor(torch, output_projected, 1))
    source = _normalize(torch, _float64_tensor(torch, source_projected, 1))
    return _cosine(torch, output, source)


def _threshold_outcome(
    status: str, threshold: float, score: float | None, /
) -> _ThresholdOutcome:
    if (
        type(status) is not str
        or status not in {"DRAFT", "CALIBRATED", "VALIDATED", "REVOKED"}
        or type(threshold) is not float
        or not math.isfinite(threshold)
        or not -1.0 <= threshold <= 1.0
    ):
        raise _MetricContractViolation
    if status != "VALIDATED":
        if score is not None:
            raise _MetricContractViolation
        result = RuleStatus.FAIL if status == "REVOKED" else RuleStatus.UNVERIFIABLE
        return _ThresholdOutcome(result, None, False)
    if score is None:
        return _ThresholdOutcome(None, None, True)
    if type(score) is not float or not math.isfinite(score) or not -1.0 <= score <= 1.0:
        raise _MetricContractViolation
    score = _canonical_score(score)
    return _ThresholdOutcome(
        RuleStatus.PASS if score >= threshold else RuleStatus.FAIL,
        score,
        False,
    )
