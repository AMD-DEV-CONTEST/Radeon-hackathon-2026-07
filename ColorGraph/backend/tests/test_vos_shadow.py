from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from colorgraph.evaluation.vos_shadow import (
    REQUIRED_VOS_MODELS,
    REQUIRED_VOS_SCENARIOS,
    VOSCompatibilityEvidence,
    VOSDatasetEvidence,
    VOSEvaluationItem,
    VOSModelArtifacts,
    VOSModelRun,
    VOSObservation,
    VOSShadowBundle,
    evaluate_vos_shadow,
)


def _dataset(*, evidence_class: str = "engineering_fixture") -> VOSDatasetEvidence:
    return VOSDatasetEvidence(
        evidence_class=evidence_class,
        test_frozen_at=datetime(2026, 7, 30, tzinfo=UTC),
        annotation_guideline_version="vos-gold/v1",
        gold_manifest_sha256="e" * 64 if evidence_class == "gold" else None,
        gold_audit_report_sha256="f" * 64 if evidence_class == "gold" else None,
        independent_reviewer_ids=["reviewer-1"] if evidence_class == "gold" else [],
    )


def _items(*, evidence_class: str) -> list[VOSEvaluationItem]:
    origin = "camera_original" if evidence_class == "gold" else "procedural"
    return [
        VOSEvaluationItem(
            item_id=scenario,
            source_group_id=f"source-{scenario}",
            scenario=scenario,
            media_origin=origin,
            media_sha256=hashlib.sha256(f"media-{scenario}".encode()).hexdigest(),
            annotation_sha256=hashlib.sha256(
                f"annotation-{scenario}".encode()
            ).hexdigest(),
            frame_count=3_600 if scenario == "long_drift" else 150,
            duration_seconds=120 if scenario == "long_drift" else 5,
            object_count=2,
        )
        for scenario in REQUIRED_VOS_SCENARIOS
    ]


def _compatibility() -> list[VOSCompatibilityEvidence]:
    return [
        VOSCompatibilityEvidence(
            platform="windows",
            accelerator="cpu",
            status="passed",
            report_sha256="1" * 64,
        ),
        VOSCompatibilityEvidence(
            platform="windows",
            accelerator="cuda",
            status="passed",
            report_sha256="2" * 64,
        ),
        VOSCompatibilityEvidence(
            platform="wsl2",
            accelerator="cuda",
            status="passed",
            report_sha256="3" * 64,
        ),
        VOSCompatibilityEvidence(
            platform="linux",
            accelerator="cuda",
            status="passed",
            report_sha256="4" * 64,
        ),
        VOSCompatibilityEvidence(
            platform="windows",
            accelerator="rocm",
            status="blocked",
            blocker="ROCm is unavailable on this fixture host.",
        ),
        VOSCompatibilityEvidence(
            platform="linux",
            accelerator="rocm",
            status="blocked",
            blocker="ROCm is unavailable on this fixture host.",
        ),
    ]


def _artifacts(model_id: str) -> VOSModelArtifacts:
    weights_required = model_id != "farneback"
    return VOSModelArtifacts(
        code_url=f"https://example.com/{model_id}/code",
        code_license_id="Apache-2.0",
        code_commercial_use_allowed=True,
        source_revision="c" * 40,
        weights_required=weights_required,
        weights_url=(
            f"https://example.com/{model_id}/weights"
            if weights_required
            else None
        ),
        weights_license_id="Apache-2.0" if weights_required else None,
        weights_commercial_use_allowed=True if weights_required else None,
        weights_redistribution_allowed=True if weights_required else None,
        checkpoint_sha256="d" * 64 if weights_required else None,
        license_review_sha256="a" * 64,
        semantic_anchor_initialization=model_id in {"sam21", "sam31", "cutie"},
        reports_occlusion_or_uncertainty=model_id == "sea_raft",
        maximum_objects=8 if model_id == "sam31" else None,
        window_frames=240 if model_id == "sam31" else None,
        compatibility=_compatibility(),
    )


def _run(
    model_id: str,
    items: list[VOSEvaluationItem],
    *,
    temporal_iou: float,
    boundary_f: float,
    drift_stability: float,
    lost_rate: float,
    reappearance_recall: float,
    fps: float = 10,
    peak_gpu_memory_mb: float = 8_000,
    memory_growth_mb: float = 256,
) -> VOSModelRun:
    return VOSModelRun(
        model_id=model_id,
        status="completed",
        artifacts=_artifacts(model_id),
        observations=[
            VOSObservation(
                item_id=item.item_id,
                prediction_sha256=hashlib.sha256(
                    f"{model_id}-{item.item_id}".encode()
                ).hexdigest(),
                temporal_iou_sum=temporal_iou * 100,
                temporal_sample_count=100,
                boundary_f_sum=boundary_f * 100,
                boundary_sample_count=100,
                normalized_drift_error_sum=(1 - drift_stability) * 100,
                drift_sample_count=100,
                lost_object_frames=round(lost_rate * 100),
                object_frame_count=100,
                identity_switches=1 if model_id == "farneback" else 0,
                reappearance_events=(
                    10 if item.scenario == "disappear_reappear" else 0
                ),
                reappearance_reacquired=(
                    round(reappearance_recall * 10)
                    if item.scenario == "disappear_reappear"
                    else 0
                ),
                elapsed_seconds=item.frame_count / fps,
                peak_cpu_memory_mb=512,
                peak_gpu_memory_mb=peak_gpu_memory_mb,
                memory_growth_mb=memory_growth_mb,
            )
            for item in items
        ],
    )


def _bundle(
    *,
    evidence_class: str = "engineering_fixture",
) -> VOSShadowBundle:
    items = _items(evidence_class=evidence_class)
    return VOSShadowBundle(
        created_at=datetime(2026, 7, 30, tzinfo=UTC),
        dataset=_dataset(evidence_class=evidence_class),
        items=items,
        runs=[
            _run(
                "farneback",
                items,
                temporal_iou=0.65,
                boundary_f=0.65,
                drift_stability=0.70,
                lost_rate=0.10,
                reappearance_recall=0.70,
                fps=40,
                peak_gpu_memory_mb=0,
            ),
            _run(
                "sam21",
                items,
                temporal_iou=0.80,
                boundary_f=0.80,
                drift_stability=0.85,
                lost_rate=0.03,
                reappearance_recall=0.90,
            ),
            _run(
                "sam31",
                items,
                temporal_iou=0.805,
                boundary_f=0.805,
                drift_stability=0.855,
                lost_rate=0.03,
                reappearance_recall=0.90,
            ),
            _run(
                "cutie",
                items,
                temporal_iou=0.77,
                boundary_f=0.77,
                drift_stability=0.82,
                lost_rate=0.05,
                reappearance_recall=0.90,
            ),
            _run(
                "sea_raft",
                items,
                temporal_iou=0.75,
                boundary_f=0.75,
                drift_stability=0.80,
                lost_rate=0.06,
                reappearance_recall=0.80,
            ),
        ],
    )


def _evaluate(bundle: VOSShadowBundle):
    return evaluate_vos_shadow(
        bundle,
        input_path="vos-shadow.json",
        input_sha256="0" * 64,
        created_at=datetime(2026, 7, 30, tzinfo=UTC),
    )


def test_reports_all_failure_modes_temporal_boundary_and_runtime() -> None:
    report = _evaluate(_bundle())
    sam21 = next(item for item in report.reports if item.model_id == "sam21")

    assert set(sam21.scenario_metrics) == set(REQUIRED_VOS_SCENARIOS)
    assert sam21.temporal_iou == 0.8
    assert sam21.boundary_f == 0.8
    assert sam21.drift_stability == 0.85
    assert sam21.lost_object_frame_rate == 0.03
    assert sam21.reappearance_recall == 0.9
    assert sam21.processing_fps == 10
    assert sam21.peak_gpu_memory_mb == 8_000
    assert sam21.maximum_memory_growth_mb == 256
    assert sam21.compatibility_matrix_documented is True
    assert sam21.candidate_gate_passed is True


def test_complete_engineering_fixture_stays_shadow_only() -> None:
    report = _evaluate(_bundle())

    assert report.status == "complete"
    assert report.gates["frozen_human_gold_test"] is False
    assert report.release_status == "shadow_only"
    assert report.eligible_candidates == []
    assert report.recommended_primary is None


def test_missing_model_row_keeps_report_partial() -> None:
    bundle = _bundle()
    bundle.runs = [run for run in bundle.runs if run.model_id != "cutie"]

    report = _evaluate(bundle)

    assert report.status == "partial"
    assert report.missing_models == ["cutie"]
    assert report.gates["required_model_rows_documented"] is False


def test_gold_recommends_sam21_and_explicit_fallback_roles() -> None:
    report = _evaluate(_bundle(evidence_class="gold"))

    assert set(item.model_id for item in report.reports) == set(
        REQUIRED_VOS_MODELS
    )
    assert report.release_status == "eligible_candidates"
    assert report.recommended_primary == "sam21"
    assert report.recommended_vos_fallback == "cutie"
    assert report.recommended_flow_fallback == "sea_raft"


def test_sam31_requires_material_gain_over_same_gold_set() -> None:
    bundle = _bundle(evidence_class="gold")
    sam31 = next(run for run in bundle.runs if run.model_id == "sam31")
    for observation in sam31.observations:
        observation.temporal_iou_sum = 92
        observation.boundary_f_sum = 92
        observation.normalized_drift_error_sum = 5
        observation.lost_object_frames = 1

    report = _evaluate(bundle)

    assert report.recommended_primary == "sam31"


def test_license_platform_and_memory_fail_only_the_affected_candidate() -> None:
    bundle = _bundle(evidence_class="gold")
    sam31 = next(run for run in bundle.runs if run.model_id == "sam31")
    sam31.artifacts.weights_redistribution_allowed = False
    sam31.artifacts.compatibility = [
        item
        for item in sam31.artifacts.compatibility
        if not (
            item.platform in {"wsl2", "linux"}
            and item.accelerator == "cuda"
        )
    ]
    for observation in sam31.observations:
        observation.memory_growth_mb = 2_048

    report = _evaluate(bundle)
    sam31_report = next(
        item for item in report.reports if item.model_id == "sam31"
    )

    assert sam31_report.candidate_gate_passed is False
    assert set(sam31_report.candidate_blockers) >= {
        "artifact_gate_not_passed",
        "memory_growth_exceeded",
    }
    assert set(sam31_report.artifact_blockers) >= {
        "weights_redistribution_not_cleared",
        "deployment_compatibility_not_passed",
    }
    assert report.release_status == "eligible_candidates"
    assert report.recommended_primary == "sam21"
