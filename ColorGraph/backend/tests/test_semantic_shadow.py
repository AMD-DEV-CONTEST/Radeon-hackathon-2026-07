from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from colorgraph.evaluation.semantic_shadow import (
    REQUIRED_SEMANTIC_MODELS,
    SemanticClassCounts,
    SemanticDatasetEvidence,
    SemanticEvaluationItem,
    SemanticModelArtifacts,
    SemanticModelObservation,
    SemanticModelRun,
    SemanticShadowBundle,
    evaluate_semantic_shadow,
)

KEY_CLASSES = ("water", "vegetation", "mountain")


def _dataset(*, evidence_class: str = "engineering_fixture") -> SemanticDatasetEvidence:
    return SemanticDatasetEvidence(
        evidence_class=evidence_class,
        test_frozen_at=datetime(2026, 7, 30, tzinfo=UTC),
        annotation_guideline_version="semantic-gold/v1",
        gold_manifest_sha256="e" * 64 if evidence_class == "gold" else None,
        gold_audit_report_sha256="f" * 64 if evidence_class == "gold" else None,
        independent_reviewer_ids=["reviewer-1"] if evidence_class == "gold" else [],
    )


def _item(*, origin: str = "camera_original") -> SemanticEvaluationItem:
    return SemanticEvaluationItem(
        item_id="video-1",
        source_group_id="source-1",
        media_origin=origin,
        media_sha256="a" * 64,
        annotation_sha256="b" * 64,
        frame_count=10,
        width=32,
        height=18,
        annotated_classes=list(KEY_CLASSES),
    )


def _artifacts(*, commercial: bool = True) -> SemanticModelArtifacts:
    return SemanticModelArtifacts(
        code_url="https://example.com/code",
        code_license_id="Apache-2.0",
        code_commercial_use_allowed=commercial,
        source_revision="c" * 40,
        weights_url="https://example.com/weights",
        weights_license_id="Apache-2.0",
        weights_commercial_use_allowed=commercial,
        checkpoint_sha256="d" * 64,
        label_space="ade20k",
        label_mapping_sha256="1" * 64,
    )


def _counts(
    class_name: str,
    *,
    intersection: int,
    boundary_matches: int,
    temporal_error: float,
) -> SemanticClassCounts:
    return SemanticClassCounts(
        class_name=class_name,
        intersection_pixels=intersection,
        union_pixels=200 - intersection,
        predicted_pixels=100,
        reference_pixels=100,
        matched_predicted_boundary_pixels=boundary_matches,
        predicted_boundary_pixels=40,
        matched_reference_boundary_pixels=boundary_matches,
        reference_boundary_pixels=40,
        temporal_absolute_error_sum=temporal_error * 100,
        temporal_sample_count=100,
    )


def _run(
    model_id: str,
    *,
    intersection: int,
    boundary_matches: int,
    temporal_error: float,
    commercial: bool = True,
    elapsed_seconds: float = 2,
    peak_gpu_memory_mb: float = 4_000,
) -> SemanticModelRun:
    return SemanticModelRun(
        model_id=model_id,
        status="completed",
        artifacts=_artifacts(commercial=commercial),
        operating_system="Windows",
        runtime="cuda",
        precision="fp16",
        observations=[
            SemanticModelObservation(
                item_id="video-1",
                prediction_sha256=hashlib.sha256(model_id.encode()).hexdigest(),
                class_counts=[
                    _counts(
                        class_name,
                        intersection=intersection,
                        boundary_matches=boundary_matches,
                        temporal_error=temporal_error,
                    )
                    for class_name in KEY_CLASSES
                ],
                frames_processed=10,
                elapsed_seconds=elapsed_seconds,
                peak_cpu_memory_mb=512,
                peak_gpu_memory_mb=peak_gpu_memory_mb,
            )
        ],
    )


def _bundle(
    *,
    evidence_class: str = "engineering_fixture",
) -> SemanticShadowBundle:
    return SemanticShadowBundle(
        created_at=datetime(2026, 7, 30, tzinfo=UTC),
        dataset=_dataset(evidence_class=evidence_class),
        items=[_item()],
        runs=[
            _run(
                "current_segformer_b0",
                intersection=70,
                boundary_matches=28,
                temporal_error=0.2,
            ),
            _run(
                "segformer_b5",
                intersection=85,
                boundary_matches=36,
                temporal_error=0.1,
            ),
            _run(
                "oneformer_ade20k_swin_large",
                intersection=86,
                boundary_matches=36,
                temporal_error=0.1,
            ),
        ],
    )


def _evaluate(bundle: SemanticShadowBundle):
    return evaluate_semantic_shadow(
        bundle,
        input_path="semantic-shadow.json",
        input_sha256="0" * 64,
        created_at=datetime(2026, 7, 30, tzinfo=UTC),
    )


def test_reports_key_class_iou_boundary_temporal_speed_and_vram() -> None:
    report = _evaluate(_bundle())
    b5 = next(item for item in report.reports if item.model_id == "segformer_b5")

    assert set(b5.class_metrics) == set(KEY_CLASSES)
    assert b5.class_metrics["water"].iou == 85 / 115
    assert b5.class_metrics["water"].boundary_f == 0.9
    assert b5.class_metrics["water"].temporal_stability == 0.9
    assert b5.processing_fps == 5
    assert b5.peak_gpu_memory_mb == 4_000
    assert b5.candidate_quality_gate_passed is True


def test_complete_engineering_fixture_stays_shadow_only() -> None:
    report = _evaluate(_bundle())

    assert report.status == "complete"
    assert report.gates["candidate_key_class_quality_and_runtime"] is True
    assert report.gates["frozen_human_gold_test"] is False
    assert report.release_status == "shadow_only"
    assert report.recommended_candidate is None


def test_missing_model_keeps_required_matrix_partial() -> None:
    bundle = _bundle()
    bundle.runs = [
        run
        for run in bundle.runs
        if run.model_id != "oneformer_ade20k_swin_large"
    ]

    report = _evaluate(bundle)

    assert report.status == "partial"
    assert report.missing_models == ["oneformer_ade20k_swin_large"]
    assert report.gates["required_model_matrix_completed"] is False


def test_gold_prefers_lower_migration_b5_for_marginal_oneformer_gain() -> None:
    report = _evaluate(_bundle(evidence_class="gold"))

    assert set(item.model_id for item in report.reports) == set(
        REQUIRED_SEMANTIC_MODELS
    )
    assert all(report.gates.values())
    assert report.release_status == "eligible_default_candidate"
    assert report.recommended_candidate == "segformer_b5"


def test_key_class_regression_license_and_runtime_fail_closed() -> None:
    bundle = _bundle(evidence_class="gold")
    b5 = next(run for run in bundle.runs if run.model_id == "segformer_b5")
    b5.artifacts.weights_commercial_use_allowed = False
    water = next(
        item
        for item in b5.observations[0].class_counts
        if item.class_name == "water"
    )
    water.intersection_pixels = 50
    water.union_pixels = 150
    b5.observations[0].peak_gpu_memory_mb = 20_000

    report = _evaluate(bundle)
    b5_report = next(
        item for item in report.reports if item.model_id == "segformer_b5"
    )

    assert b5_report.candidate_quality_gate_passed is False
    assert set(b5_report.candidate_quality_blockers) >= {
        "artifact_gate_not_passed",
        "water_iou_regressed",
        "peak_gpu_memory_exceeded",
    }
    assert report.gates["artifacts_frozen_and_commercially_cleared"] is False
    assert report.release_status == "shadow_only"
    assert report.recommended_candidate is None
