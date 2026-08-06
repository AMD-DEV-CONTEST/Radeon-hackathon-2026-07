from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from test_creative_agent_evaluation import _artifact, _execution, _sha

from colorgraph.evaluation.creative_ablation import (
    CreativeAblationEvaluationCoverage,
    CreativeAblationMatrixManifest,
    CreativeAblationProviderEvidence,
    CreativeAblationSeedManifest,
    CreativeDirectionDistanceEvidence,
    audit_creative_ablation_matrix,
    audit_creative_ablation_seed,
    audit_creative_ablation_seed_file,
)
from colorgraph.evaluation.creative_agent import CreativePipelineVariant
from colorgraph.evaluation.creative_intake import (
    CreativeArtifactReference,
    sha256_file,
)


def _seed_for(
    root: Path,
    *,
    item_id: str,
    variant: CreativePipelineVariant,
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    candidate_id = f"{item_id}:{variant.value}"
    output_sha256 = _sha(f"output:{item_id}:{variant.value}")
    run_request_path = root / "run-request.json"
    run_request_path.write_text(
        json.dumps(
            {
                "schema_version": "test-run-request/v1",
                "candidate_id": candidate_id,
                "variant": variant.value,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    pipeline_result_path = root / "pipeline-result.json"
    pipeline_result_path.write_text(
        json.dumps(
            {
                "schema_version": "test-pipeline-result/v1",
                "candidate_id": candidate_id,
                "current_graph_unchanged": True,
                "reflection_stage_executed": (
                    variant == CreativePipelineVariant.FULL_PIPELINE
                ),
                "reflection_completed": (
                    variant == CreativePipelineVariant.FULL_PIPELINE
                ),
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    execution = _execution(
        item_id=item_id,
        candidate_id=candidate_id,
        variant=variant,
        output_sha256=output_sha256,
    ).model_copy(
        update={
            "run_request_sha256": sha256_file(run_request_path),
            "pipeline_result_sha256": sha256_file(pipeline_result_path),
        }
    )
    execution_path = root / "execution.json"
    execution_path.write_text(
        execution.model_dump_json(indent=2),
        encoding="utf-8",
    )
    stage_evidence = {
        stage: _artifact(
            root,
            f"stages/{stage.value}.json",
            f"execution:{candidate_id}:{stage.value}",
        )
        for stage in execution.executed_stages
    }
    manifest = CreativeAblationSeedManifest(
        created_at=datetime(2026, 7, 30, 12, tzinfo=UTC),
        project_id="creative-project",
        run_id=f"creative-ablation-run:{item_id}:{variant.value}",
        item_id=item_id,
        candidate_id=candidate_id,
        variant=variant,
        provider=CreativeAblationProviderEvidence(
            provider_id=(
                "offline-rules"
                if variant == CreativePipelineVariant.RULE_BASELINE
                else "frozen-test-provider"
            ),
            runtime_version="colorgraph.offline-creative-pipeline/v1",
            model_id=(
                "none"
                if variant == CreativePipelineVariant.RULE_BASELINE
                else "frozen-test-model"
            ),
            model_revision=(
                "none"
                if variant == CreativePipelineVariant.RULE_BASELINE
                else "frozen-test-v1"
            ),
            successful_calls=(
                0 if variant == CreativePipelineVariant.RULE_BASELINE else 1
            ),
            total_calls=(
                0 if variant == CreativePipelineVariant.RULE_BASELINE else 1
            ),
        ),
        execution={
            "relative_path": "execution.json",
            "sha256": sha256_file(execution_path),
        },
        source_media=_artifact(
            root,
            "media/source.txt",
            f"media:{item_id}",
        ),
        source_graph=_artifact(
            root,
            "source/graph.json",
            f"source-graph:{item_id}",
        ),
        run_request=CreativeArtifactReference(
            relative_path="run-request.json",
            sha256=sha256_file(run_request_path),
        ),
        pipeline_result=CreativeArtifactReference(
            relative_path="pipeline-result.json",
            sha256=sha256_file(pipeline_result_path),
        ),
        output=_artifact(
            root,
            "output/candidate.txt",
            f"output:{item_id}:{variant.value}",
        ),
        stage_evidence=stage_evidence,
        direction_distance=CreativeDirectionDistanceEvidence(
            metric="colorgraph.mean-rgb-l1/v1",
            definition="Frozen test direction distances.",
            pair_order=(
                ["faithful__amplified", "faithful__counterpoint", "amplified__counterpoint"]
                if execution.direction_count == 3
                else []
            ),
            values=execution.direction_pairwise_distances,
            mean=(
                sum(execution.direction_pairwise_distances)
                / len(execution.direction_pairwise_distances)
                if execution.direction_pairwise_distances
                else 0
            ),
            formal_full_pipeline_threshold=0.15,
            formal_full_pipeline_gate_passed=bool(
                execution.direction_pairwise_distances
                and (
                    sum(execution.direction_pairwise_distances)
                    / len(execution.direction_pairwise_distances)
                )
                >= 0.15
            ),
        ),
        evaluation_coverage=CreativeAblationEvaluationCoverage(
            test_items_present=1,
            minimum_rule_baseline_pairs=10,
            rule_baseline_pairs_present=0,
            variants_present=[variant],
            missing_variants=[
                candidate_variant
                for candidate_variant in CreativePipelineVariant
                if candidate_variant != variant
            ],
        ),
        formal_blockers=["Independent production evidence is absent."],
    )
    manifest_path = root / "manifest.json"
    manifest_path.write_text(
        manifest.model_dump_json(indent=2),
        encoding="utf-8",
    )
    return manifest_path


def _seed(root: Path) -> Path:
    return _seed_for(
        root,
        item_id="creative-test-00",
        variant=CreativePipelineVariant.RULE_BASELINE,
    )


def _matrix_manifest(
    root: Path,
    seed_paths: list[Path],
) -> Path:
    manifest = CreativeAblationMatrixManifest(
        evaluation_id="creative-evaluation",
        dataset_version="creative-dataset-v1",
        created_at=datetime(2026, 7, 30, 13, tzinfo=UTC),
        seed_manifests=[
            CreativeArtifactReference(
                relative_path=path.relative_to(root).as_posix(),
                sha256=sha256_file(path),
            )
            for path in seed_paths
        ],
    )
    path = root / "matrix.json"
    path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    return path


def test_creative_ablation_seed_audit_binds_every_executed_stage(
    tmp_path: Path,
) -> None:
    manifest_path = _seed(tmp_path)
    output_path = tmp_path / "audit.json"

    audit = audit_creative_ablation_seed_file(manifest_path, output_path)

    assert audit.passed
    assert audit.execution_protocol_valid
    assert audit.checked_artifacts == 10
    assert audit.formal_review_freeze is False
    assert audit.formal_release_eligible is False
    assert output_path.is_file()


def test_creative_ablation_seed_tampering_fails_closed(
    tmp_path: Path,
) -> None:
    manifest_path = _seed(tmp_path)
    (tmp_path / "stages" / "renderer.json").write_text(
        "tampered",
        encoding="utf-8",
    )

    audit = audit_creative_ablation_seed(manifest_path)

    assert not audit.passed
    assert any(
        "renderer stage digest mismatch" in issue for issue in audit.issues
    )


def test_ablation_matrix_reports_exact_missing_variants_without_claiming_release(
    tmp_path: Path,
) -> None:
    seed_path = _seed(tmp_path / "seed")
    matrix_path = _matrix_manifest(tmp_path, [seed_path])

    audit = audit_creative_ablation_matrix(matrix_path)

    assert audit.technical_evidence_integrity_passed
    assert not audit.technical_matrix_complete
    assert not audit.passed
    assert audit.checked_seed_manifests == audit.passed_seed_manifests == 1
    assert audit.unique_test_items == 1
    assert audit.item_coverage[0].variants_present == [
        CreativePipelineVariant.RULE_BASELINE
    ]
    assert CreativePipelineVariant.FULL_PIPELINE in (
        audit.item_coverage[0].missing_variants
    )
    assert audit.formal_review_freeze is False
    assert audit.formal_release_eligible is False


def test_complete_ten_by_eight_ablation_matrix_is_only_technical_evidence(
    tmp_path: Path,
) -> None:
    seed_paths = [
        _seed_for(
            tmp_path / "seeds" / item_id / variant.value,
            item_id=item_id,
            variant=variant,
        )
        for item_id in (f"creative-test-{index:02d}" for index in range(10))
        for variant in CreativePipelineVariant
    ]
    matrix_path = _matrix_manifest(tmp_path, seed_paths)

    audit = audit_creative_ablation_matrix(matrix_path)

    assert audit.passed
    assert audit.technical_evidence_integrity_passed
    assert audit.technical_matrix_complete
    assert audit.checked_seed_manifests == audit.passed_seed_manifests == 80
    assert audit.unique_test_items == audit.complete_test_items == 10
    assert all(item.complete for item in audit.item_coverage)
    assert audit.formal_review_freeze is False
    assert audit.formal_release_eligible is False
