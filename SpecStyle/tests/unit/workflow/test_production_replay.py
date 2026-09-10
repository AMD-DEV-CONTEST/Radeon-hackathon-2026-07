from __future__ import annotations

from dataclasses import replace

import pytest

from specstyle.domain.identifiers import Sha256
from specstyle.errors import DomainError
from specstyle.exporting.bundle import ExportBundle
from specstyle.workflow.production_replay import (
    ProductionReplayEvidence,
    ReplayMetricObservation,
    assess_production_replay,
    capture_production_replay_evidence,
)
from tests.unit.workflow.test_production_export import _case


def _sha(ch: str) -> Sha256:
    return Sha256(ch * 64)


def _metric(
    level: str,
    rule_id: str,
    metric_id: str,
    score: float | None,
    tolerance: float,
    *,
    status: str = "PASS",
) -> ReplayMetricObservation:
    return ReplayMetricObservation(level, rule_id, metric_id, status, score, tolerance)


def _evidence(*, candidate: bool = False) -> ProductionReplayEvidence:
    suffix = "candidate" if candidate else "baseline"
    return ProductionReplayEvidence(
        job_id=f"run-one-{suffix}",
        bundle_name=f"bundle-run-one-{suffix}",
        bundle_sha256=_sha("b" if candidate else "a"),
        artifact_sha256=_sha("d" if candidate else "c"),
        form_fingerprint=_sha("1"),
        compiled_spec_hash=_sha("2"),
        graph_fingerprint=_sha("3"),
        model_pins_fingerprint=_sha("4"),
        generation_fingerprint=_sha("5"),
        required_gate_fingerprint=_sha("6"),
        required_gate_state_fingerprint=_sha("7"),
        route_fingerprint=_sha("8"),
        environment_fingerprint=_sha("9"),
        environment_policy="advisory",
        variation_index=4,
        seed=1234,
        metrics=(_metric("L2", "l2_style", "style_similarity", 0.90, 0.02),),
        l3_status="NOT_APPLICABLE",
        l3_reason="NO_L3_CONFIG",
    )


def test_semantic_replay_can_be_exact_without_pixel_equality() -> None:
    baseline = _evidence()
    candidate = replace(
        _evidence(candidate=True),
        metrics=(_metric("L2", "l2_style", "style_similarity", 0.91, 0.02),),
    )

    result = assess_production_replay(baseline, candidate)

    assert result.status == "EXACT"
    assert result.reasons == ()
    assert result.artifact_hash_equal is False
    assert result.l3_status == "NOT_APPLICABLE"
    assert result.metrics[0].delta == pytest.approx(0.01)
    assert result.metrics[0].tolerance == 0.02


def test_advisory_environment_difference_is_compatible() -> None:
    baseline = _evidence()
    candidate = replace(_evidence(candidate=True), environment_fingerprint=_sha("e"))

    result = assess_production_replay(baseline, candidate)

    assert result.status == "COMPATIBLE"
    assert result.reasons == ("environment_fingerprint_differs",)


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    (
        ("generation_fingerprint", _sha("e"), "generation_fingerprint_mismatch"),
        ("required_gate_fingerprint", _sha("e"), "required_gate_mismatch"),
        (
            "required_gate_state_fingerprint",
            _sha("e"),
            "required_gate_state_mismatch",
        ),
        ("route_fingerprint", _sha("e"), "route_mismatch"),
        ("variation_index", 5, "variation_index_mismatch"),
        ("seed", 99, "seed_mismatch"),
    ),
)
def test_identity_gate_and_route_drift_are_rejected(
    field: str, value: object, reason: str
) -> None:
    result = assess_production_replay(
        _evidence(), replace(_evidence(candidate=True), **{field: value})
    )

    assert result.status == "REJECTED"
    assert reason in result.reasons


def test_metric_delta_over_spec_tolerance_is_rejected() -> None:
    candidate = replace(
        _evidence(candidate=True),
        metrics=(_metric("L2", "l2_style", "style_similarity", 0.93, 0.02),),
    )

    result = assess_production_replay(_evidence(), candidate)

    assert result.status == "REJECTED"
    assert result.reasons == ("metric_delta_exceeded:L2:l2_style",)


@pytest.mark.parametrize(
    "candidate_metrics",
    (
        (),
        (_metric("L2", "l2_style", "style_similarity", None, 0.02),),
    ),
)
def test_missing_or_unscored_applicable_metric_is_unverifiable(
    candidate_metrics: tuple[ReplayMetricObservation, ...],
) -> None:
    candidate = replace(_evidence(candidate=True), metrics=candidate_metrics)

    result = assess_production_replay(_evidence(), candidate)

    assert result.status == "UNVERIFIABLE"
    assert result.reasons


def test_unscored_status_drift_remains_unverifiable() -> None:
    candidate = replace(
        _evidence(candidate=True),
        metrics=(
            _metric(
                "L2",
                "l2_style",
                "style_similarity",
                None,
                0.02,
                status="UNVERIFIABLE",
            ),
        ),
    )

    result = assess_production_replay(_evidence(), candidate)

    assert result.status == "UNVERIFIABLE"
    assert result.reasons == ("metric_unscored:L2:l2_style",)


def test_strict_environment_difference_is_rejected() -> None:
    baseline = replace(_evidence(), environment_policy="strict")
    candidate = replace(
        _evidence(candidate=True),
        environment_policy="strict",
        environment_fingerprint=_sha("e"),
    )

    result = assess_production_replay(baseline, candidate)

    assert result.status == "REJECTED"
    assert result.reasons == ("environment_fingerprint_mismatch",)


def test_replay_requires_new_job_and_bundle_identities() -> None:
    baseline = _evidence()
    candidate = replace(
        _evidence(candidate=True),
        job_id=baseline.job_id,
        bundle_name=baseline.bundle_name,
    )

    result = assess_production_replay(baseline, candidate)

    assert result.status == "REJECTED"
    assert result.reasons == ("job_identity_reused", "bundle_identity_reused")


def test_invalid_replay_evidence_is_rejected() -> None:
    with pytest.raises(DomainError, match="invalid production replay evidence"):
        ProductionReplayEvidence(  # type: ignore[arg-type]
            "job",
            "bundle",
            _sha("a"),
            _sha("b"),
            _sha("c"),
            _sha("d"),
            _sha("e"),
            _sha("f"),
            _sha("1"),
            _sha("2"),
            _sha("3"),
            _sha("4"),
            _sha("5"),
            "advisory",
            True,
            1,
            (),
            "NOT_APPLICABLE",
            "NO_L3_CONFIG",
        )
    with pytest.raises(DomainError, match="invalid production replay evidence"):
        replace(_evidence(), metrics=object())  # type: ignore[arg-type]


def test_assessment_revalidates_frozen_evidence_members() -> None:
    candidate = _evidence(candidate=True)
    object.__setattr__(candidate.metrics[0], "score", float("nan"))

    with pytest.raises(DomainError, match="invalid production replay evidence"):
        assess_production_replay(_evidence(), candidate)


def test_assessment_rejects_tampered_sha_members() -> None:
    baseline = _evidence()
    candidate = _evidence(candidate=True)
    object.__setattr__(baseline.compiled_spec_hash, "value", "tampered")
    object.__setattr__(candidate.compiled_spec_hash, "value", "tampered")

    with pytest.raises(DomainError, match="invalid production replay evidence"):
        assess_production_replay(baseline, candidate)


def test_evidence_copies_sha_members_and_enforces_seed_ranges() -> None:
    source_hash = _sha("2")
    evidence = replace(_evidence(), compiled_spec_hash=source_hash)
    object.__setattr__(source_hash, "value", "tampered")
    assert evidence.compiled_spec_hash == _sha("2")

    with pytest.raises(DomainError, match="invalid production replay evidence"):
        replace(_evidence(), variation_index=2**31)
    with pytest.raises(DomainError, match="invalid production replay evidence"):
        replace(_evidence(), seed=2**63)


def _bundle(name: str) -> ExportBundle:
    return ExportBundle(
        name,
        1,
        2,
        _sha("a"),
        _sha("b"),
        _sha("c"),
        (),
    )


def test_capture_uses_initial_generation_and_final_verification_contract() -> None:
    case = _case(job_id="run-one-baseline")

    evidence = capture_production_replay_evidence(
        case.result, _bundle("bundle-run-one-baseline"), _sha("f")
    )

    initial = case.result.history.initial_attempt.request
    assert evidence.job_id == "run-one-baseline"
    assert evidence.bundle_name == "bundle-run-one-baseline"
    assert evidence.bundle_sha256 == _sha("c")
    assert evidence.artifact_sha256 == case.result.artifact.ref.sha256
    assert evidence.form_fingerprint == _sha("f")
    assert evidence.compiled_spec_hash == case.result.compiled.compiled_spec_hash
    assert evidence.generation_fingerprint == initial.generation_fingerprint
    assert evidence.environment_fingerprint == initial.environment_hash
    assert evidence.environment_policy == "advisory"
    assert evidence.variation_index == initial.variation_index
    assert evidence.seed == initial.seed.seed
    assert evidence.l3_status == "NOT_APPLICABLE"
    assert evidence.l3_reason == "NO_L3_CONFIG"
    assert tuple(
        (item.level, item.rule_id, item.metric_id) for item in evidence.metrics
    ) == (("L2", "style", "style-metric"),)
    assert evidence.metrics[0].score is None
    assert evidence.metrics[0].tolerance == 0.0


def test_capture_rejects_non_domain_result_or_bundle() -> None:
    case = _case()
    with pytest.raises(DomainError, match="invalid production replay evidence"):
        capture_production_replay_evidence(object(), _bundle("bundle-job"), _sha("f"))  # type: ignore[arg-type]
    with pytest.raises(DomainError, match="invalid production replay evidence"):
        capture_production_replay_evidence(case.result, object(), _sha("f"))  # type: ignore[arg-type]
