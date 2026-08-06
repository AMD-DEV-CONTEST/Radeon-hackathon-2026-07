from __future__ import annotations

from datetime import UTC, datetime

from colorgraph.evaluation.shot_shadow import (
    REQUIRED_SHOT_MODELS,
    ShotDatasetEvidence,
    ShotEvaluationItem,
    ShotEvent,
    ShotModelArtifacts,
    ShotModelObservation,
    ShotModelRun,
    ShotShadowBundle,
    evaluate_shot_shadow,
)


def _item(*, origin: str = "camera_original") -> ShotEvaluationItem:
    return ShotEvaluationItem(
        item_id="video-1",
        source_group_id="source-1",
        media_origin=origin,
        media_sha256="a" * 64,
        annotation_sha256="b" * 64,
        frame_count=300,
        fps=30,
        events=[
            ShotEvent(
                event_id="hard",
                kind="hard_cut",
                start_frame=30,
                end_frame=30,
            ),
            ShotEvent(
                event_id="fade",
                kind="fade",
                start_frame=75,
                end_frame=80,
            ),
            ShotEvent(
                event_id="dissolve",
                kind="dissolve",
                start_frame=120,
                end_frame=126,
            ),
            ShotEvent(
                event_id="flash",
                kind="flash",
                start_frame=170,
                end_frame=171,
            ),
            ShotEvent(
                event_id="short",
                kind="short_shot",
                start_frame=220,
                end_frame=220,
            ),
        ],
    )


def _artifacts(
    *,
    model_id: str,
    commercial: bool = True,
    frozen: bool = True,
) -> ShotModelArtifacts:
    weights_required = model_id in {"transnetv2", "autoshot"}
    return ShotModelArtifacts(
        code_url=f"https://example.com/{model_id}/code",
        code_license_id="MIT",
        code_commercial_use_allowed=commercial,
        source_revision="c" * 40 if frozen else None,
        weights_required=weights_required,
        weights_url=(
            f"https://example.com/{model_id}/weights"
            if weights_required
            else None
        ),
        weights_license_id="MIT" if weights_required else None,
        weights_commercial_use_allowed=(
            commercial if weights_required else None
        ),
        checkpoint_sha256="d" * 64 if weights_required and frozen else None,
    )


def _completed_run(
    model_id: str,
    predictions: list[int],
    *,
    commercial: bool = True,
    frozen: bool = True,
) -> ShotModelRun:
    return ShotModelRun(
        model_id=model_id,
        status="completed",
        artifacts=_artifacts(
            model_id=model_id,
            commercial=commercial,
            frozen=frozen,
        ),
        observations=[
            ShotModelObservation(
                item_id="video-1",
                predicted_boundaries=predictions,
                elapsed_seconds=2,
                peak_cpu_memory_mb=512,
                peak_gpu_memory_mb=1024,
            )
        ],
    )


def _dataset(*, evidence_class: str = "engineering_fixture") -> ShotDatasetEvidence:
    return ShotDatasetEvidence(
        evidence_class=evidence_class,
        test_frozen_at=datetime(2026, 7, 30, tzinfo=UTC),
        annotation_guideline_version="shot-guideline/v1",
        gold_manifest_sha256="e" * 64 if evidence_class == "gold" else None,
        gold_audit_report_sha256="f" * 64 if evidence_class == "gold" else None,
        independent_reviewer_ids=["reviewer-1"] if evidence_class == "gold" else [],
    )


def _bundle(
    *,
    evidence_class: str = "engineering_fixture",
    candidate_predictions: list[int] | None = None,
) -> ShotShadowBundle:
    baseline = [30, 78, 170]
    candidate = candidate_predictions or [30, 78, 123, 220]
    return ShotShadowBundle(
        created_at=datetime(2026, 7, 30, tzinfo=UTC),
        dataset=_dataset(evidence_class=evidence_class),
        items=[_item()],
        runs=[
            _completed_run("current_detector", baseline),
            _completed_run("pyscenedetect_adaptive", baseline),
            _completed_run("transnetv2", candidate),
            _completed_run("autoshot", candidate),
        ],
    )


def _evaluate(bundle: ShotShadowBundle):
    return evaluate_shot_shadow(
        bundle,
        input_path="shot-shadow.json",
        input_sha256="0" * 64,
        created_at=datetime(2026, 7, 30, tzinfo=UTC),
    )


def test_metrics_separate_transition_kinds_and_flash_false_triggers() -> None:
    report = _evaluate(_bundle())
    candidate = next(
        item for item in report.reports if item.model_id == "transnetv2"
    )

    assert candidate.metrics is not None
    assert candidate.metrics.f1 == 1
    assert candidate.metrics.by_kind["hard_cut"].recall == 1
    assert candidate.metrics.by_kind["fade"].recall == 1
    assert candidate.metrics.by_kind["dissolve"].recall == 1
    assert candidate.metrics.by_kind["short_shot"].recall == 1
    assert candidate.metrics.by_kind["flash"].false_trigger_rate == 0
    assert candidate.processing_fps == 150


def test_missing_model_keeps_report_partial_and_shadow_only() -> None:
    bundle = _bundle()
    bundle.runs = [run for run in bundle.runs if run.model_id != "autoshot"]

    report = _evaluate(bundle)

    assert report.status == "partial"
    assert report.release_status == "shadow_only"
    assert report.missing_models == ["autoshot"]
    assert report.gates["required_model_matrix_completed"] is False


def test_complete_engineering_fixture_cannot_authorize_default() -> None:
    report = _evaluate(_bundle())

    assert report.status == "complete"
    assert report.gates["candidate_quality_improvement"] is True
    assert report.gates["frozen_human_gold_test"] is False
    assert report.release_status == "shadow_only"
    assert report.recommended_candidate is None


def test_frozen_gold_matrix_can_recommend_the_better_candidate() -> None:
    report = _evaluate(_bundle(evidence_class="gold"))

    assert set(run.model_id for run in report.reports) == set(
        REQUIRED_SHOT_MODELS
    )
    assert all(report.gates.values())
    assert report.release_status == "eligible_default_candidate"
    assert report.recommended_candidate in {"transnetv2", "autoshot"}


def test_noncommercial_or_unfrozen_artifacts_fail_closed() -> None:
    bundle = _bundle(evidence_class="gold")
    autoshot = next(run for run in bundle.runs if run.model_id == "autoshot")
    autoshot.artifacts.weights_commercial_use_allowed = False
    autoshot.artifacts.source_revision = None

    report = _evaluate(bundle)
    autoshot_report = next(
        item for item in report.reports if item.model_id == "autoshot"
    )

    assert autoshot_report.artifact_gate_passed is False
    assert set(autoshot_report.artifact_blockers) >= {
        "weights_commercial_use_not_cleared",
        "source_revision_unfrozen",
    }
    assert report.gates["artifacts_frozen_and_commercially_cleared"] is False
    assert report.release_status == "shadow_only"
