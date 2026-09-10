"""Pinned formal Production metric for complete-cohort style dispersion."""

from __future__ import annotations

import math
from pathlib import Path

from specstyle.domain.enums import RuleLevel, RuleScope, RuleStatus, StaticApplicability
from specstyle.domain.identifiers import ArtifactId
from specstyle.observability.hashing import hash_bytes
from specstyle.spec.compiled_models import CompiledRule, ResourcePin
from specstyle.verification.rule_models import RuleResult

__all__ = (
    "evaluate_production_batch_consistency",
    "production_batch_consistency_pin",
)

_IMPLEMENTATION_ID = "batch-style-consistency"
_IMPLEMENTATION_REVISION = "normalized-centroid-rms-v1"


def production_batch_consistency_pin() -> ResourcePin:
    """Bind formal observations to the exact metric implementation bytes."""
    return ResourcePin(
        _IMPLEMENTATION_ID,
        _IMPLEMENTATION_REVISION,
        hash_bytes(Path(__file__).read_bytes()),
    )


def _formal_rule(rule: object, runtime_verifier_pin: object) -> bool:
    if type(rule) is not CompiledRule or type(runtime_verifier_pin) is not ResourcePin:
        return False
    binding = rule.threshold_binding
    definition = rule.definition
    return (
        definition.level is RuleLevel.L2
        and definition.scope is RuleScope.BATCH
        and definition.required
        and definition.applicability is StaticApplicability.APPLICABLE
        and rule.verifier_pin == runtime_verifier_pin
        and rule.metric_id is not None
        and rule.metric_id.value == "batch_style_consistency"
        and binding is not None
        and binding.status == "VALIDATED"
        and binding.metric_id == rule.metric_id
        and binding.operator == "<="
        and binding.production_approval_sha256 is not None
    )


def _normalized_vectors(
    items: tuple[tuple[ArtifactId, tuple[float, ...]], ...],
) -> tuple[tuple[float, ...], ...] | None:
    if (
        len(items) < 2
        or any(type(item) is not tuple or len(item) != 2 for item in items)
        or any(type(item[1]) is not tuple for item in items)
    ):
        return None
    ids = tuple(item[0] for item in items)
    vectors = tuple(item[1] for item in items)
    dimensions = {len(vector) for vector in vectors}
    valid = (
        all(type(item) is ArtifactId for item in ids)
        and len(set(ids)) == len(ids)
        and len(dimensions) == 1
        and next(iter(dimensions), 0) > 0
        and all(
            type(value) is float and math.isfinite(value)
            for vector in vectors
            for value in vector
        )
    )
    if not valid:
        return None
    normalized: list[tuple[float, ...]] = []
    for vector in vectors:
        norm = math.sqrt(sum(value * value for value in vector))
        if not math.isfinite(norm) or norm <= 0.0:
            return None
        normalized.append(tuple(value / norm for value in vector))
    return tuple(normalized)


def _dispersion(vectors: tuple[tuple[float, ...], ...]) -> float | None:
    count = len(vectors)
    center = tuple(sum(values) / count for values in zip(*vectors, strict=True))
    squared = tuple(
        sum((value - mean) ** 2 for value, mean in zip(vector, center, strict=True))
        for vector in vectors
    )
    score = math.sqrt(sum(squared) / count)
    if not math.isfinite(score):
        return None
    return 0.0 if score == 0.0 else score


def evaluate_production_batch_consistency(
    items: tuple[tuple[ArtifactId, tuple[float, ...]], ...],
    rule: CompiledRule,
    runtime_implementation_pin: ResourcePin,
    runtime_verifier_pin: ResourcePin,
    /,
) -> RuleResult:
    """Evaluate one exact ordered cohort; unusable evidence fails closed."""
    ids = (
        tuple(item[0] for item in items)
        if type(items) is tuple
        and items
        and all(type(item) is tuple and len(item) == 2 for item in items)
        and all(type(item[0]) is ArtifactId for item in items)
        and len({item[0] for item in items}) == len(items)
        else ()
    )
    if not ids:
        raise ValueError("invalid production batch metric cohort")
    try:
        implementation_ok = (
            type(runtime_implementation_pin) is ResourcePin
            and runtime_implementation_pin == production_batch_consistency_pin()
        )
    except OSError:
        implementation_ok = False
    vectors = _normalized_vectors(items)
    score = None if vectors is None else _dispersion(vectors)
    if (
        not implementation_ok
        or not _formal_rule(rule, runtime_verifier_pin)
        or score is None
    ):
        return RuleResult(rule.definition.rule_id, RuleStatus.UNVERIFIABLE, ids, None)
    threshold = rule.threshold_binding
    assert threshold is not None
    status = RuleStatus.PASS if score <= threshold.value else RuleStatus.FAIL
    return RuleResult(rule.definition.rule_id, status, ids, score)
