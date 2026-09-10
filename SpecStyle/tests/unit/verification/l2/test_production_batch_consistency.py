"""Pinned formal Production batch-consistency metric contracts."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from specstyle.domain.enums import RuleLevel, RuleScope, RuleStatus, StaticApplicability
from specstyle.domain.identifiers import ArtifactId, Identifier, RuleId
from specstyle.observability.hashing import hash_bytes
from specstyle.spec.compiled_models import (
    CompiledRule,
    CompiledThresholdBinding,
    ResourcePin,
)
from specstyle.verification.rule_models import GatePolicy, RuleDefinition


def _pin(name: str) -> ResourcePin:
    return ResourcePin(name, "r1", hash_bytes(name.encode()))


def _rule(threshold: float = 0.25) -> CompiledRule:
    metric_id = Identifier("batch_style_consistency")
    return CompiledRule(
        RuleDefinition(
            RuleId("l2_batch_style_consistency"),
            RuleLevel.L2,
            RuleScope.BATCH,
            True,
            StaticApplicability.APPLICABLE,
            GatePolicy("reject", "reject", "manual_review"),
        ),
        _pin("style-encoder"),
        metric_id,
        CompiledThresholdBinding(
            _pin("l2-profile"),
            "formal-l2",
            "VALIDATED",
            metric_id,
            "<=",
            threshold,
            hash_bytes(b"calibration"),
            hash_bytes(b"validation"),
            hash_bytes(b"protocol"),
            hash_bytes(b"approval"),
        ),
        1,
        (),
    )


def _items(*vectors: tuple[float, ...]):
    return tuple(
        (ArtifactId(f"artifact-{index}"), vector)
        for index, vector in enumerate(vectors)
    )


def test_formal_batch_metric_is_pinned_to_exact_source_and_uses_lte() -> None:
    from specstyle.verification.l2 import production_batch_consistency as module

    pin = module.production_batch_consistency_pin()
    passed = module.evaluate_production_batch_consistency(
        _items((1.0, 0.0), (1.0, 0.0)), _rule(), pin, _pin("style-encoder")
    )
    failed = module.evaluate_production_batch_consistency(
        _items((1.0, 0.0), (0.0, 1.0)), _rule(), pin, _pin("style-encoder")
    )

    assert pin.sha256 == hash_bytes(Path(module.__file__).read_bytes())
    assert passed.status is RuleStatus.PASS and passed.score == 0.0
    assert failed.status is RuleStatus.FAIL
    assert failed.score is not None and failed.score > 0.25
    assert failed.affected_artifact_ids == (
        ArtifactId("artifact-0"),
        ArtifactId("artifact-1"),
    )


def test_formal_batch_metric_fails_closed_for_runtime_or_evidence_drift() -> None:
    from specstyle.verification.l2.production_batch_consistency import (
        evaluate_production_batch_consistency,
        production_batch_consistency_pin,
    )

    valid = production_batch_consistency_pin()
    cases = (
        (_items((1.0, 0.0), (1.0,)), _rule(), valid, _pin("style-encoder")),
        (
            (
                (ArtifactId("artifact-0"), (1.0, 0.0)),
                (ArtifactId("artifact-1"), [1.0]),
            ),
            _rule(),
            valid,
            _pin("style-encoder"),
        ),
        (
            _items((0.0, 0.0), (1.0, 0.0)),
            _rule(),
            valid,
            _pin("style-encoder"),
        ),
        (
            _items((float("nan"), 0.0), (1.0, 0.0)),
            _rule(),
            valid,
            _pin("style-encoder"),
        ),
        (
            _items((1.0, 0.0), (1.0, 0.0)),
            _rule(),
            _pin("drifted"),
            _pin("style-encoder"),
        ),
        (
            _items((1.0, 0.0), (1.0, 0.0)),
            replace(_rule(), verifier_pin=_pin("wrong-encoder")),
            valid,
            _pin("style-encoder"),
        ),
    )
    for items, rule, runtime_pin, verifier_pin in cases:
        result = evaluate_production_batch_consistency(
            items,  # type: ignore[arg-type]
            rule,
            runtime_pin,
            verifier_pin,
        )
        assert result.status is RuleStatus.UNVERIFIABLE
        assert result.score is None
        assert result.affected_artifact_ids == tuple(item[0] for item in items)


def test_formal_batch_metric_rejects_nonformal_rule_contract() -> None:
    from specstyle.verification.l2.production_batch_consistency import (
        evaluate_production_batch_consistency,
        production_batch_consistency_pin,
    )

    rule = _rule()
    legacy_metric = Identifier("batch_style_dispersion_max")
    invalid_rules = (
        replace(
            rule,
            metric_id=legacy_metric,
            threshold_binding=replace(rule.threshold_binding, metric_id=legacy_metric),
        ),
        replace(rule, threshold_binding=replace(rule.threshold_binding, operator=">=")),
        replace(
            rule, threshold_binding=replace(rule.threshold_binding, status="DRAFT")
        ),
        replace(
            rule,
            threshold_binding=replace(
                rule.threshold_binding, production_approval_sha256=None
            ),
        ),
    )
    for invalid in invalid_rules:
        result = evaluate_production_batch_consistency(
            _items((1.0, 0.0), (1.0, 0.0)),
            invalid,
            production_batch_consistency_pin(),
            _pin("style-encoder"),
        )
        assert result.status is RuleStatus.UNVERIFIABLE
        assert result.score is None


def test_formal_batch_metric_requires_at_least_two_unique_members() -> None:
    from specstyle.verification.l2.production_batch_consistency import (
        evaluate_production_batch_consistency,
        production_batch_consistency_pin,
    )

    result = evaluate_production_batch_consistency(
        _items((1.0, 0.0)),
        _rule(),
        production_batch_consistency_pin(),
        _pin("style-encoder"),
    )

    assert result.status is RuleStatus.UNVERIFIABLE
    assert result.score is None
