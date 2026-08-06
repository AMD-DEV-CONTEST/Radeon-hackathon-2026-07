from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from colorgraph.evaluation.creative_agent import (
    CreativeAgentEvaluationBundle,
    CreativeCandidateObservation,
    CreativeChallengeResult,
    CreativeChallengeTag,
    CreativeDimensionScores,
    CreativeEvaluationDimension,
    CreativeEvidenceClass,
    CreativeGoldEvidence,
    CreativeGoldItem,
    CreativeJudgeRecord,
    CreativeMediaOrigin,
    CreativePairChoice,
    CreativePairReview,
    CreativePipelineStage,
    CreativePipelineVariant,
    CreativeReviewer,
    CreativeVariantExecution,
    build_creative_agent_review_pairs,
    creative_variant_stage_order,
    evaluate_creative_agent,
    evaluate_creative_agent_file,
)
from colorgraph.evaluation.creative_intake import (
    CreativeArtifactReference,
    CreativeCandidateArtifact,
    CreativeGoldArtifactSet,
    CreativeProductionManifest,
    CreativeReviewerAttestation,
    CreativeReviewerResponseEnvelope,
    creative_bundle_component_digests,
    sha256_file,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _scores(*, full: bool) -> CreativeDimensionScores:
    return CreativeDimensionScores(
        values={
            dimension: (
                0.1
                if full and dimension == CreativeEvaluationDimension.OVERGRADING_RISK
                else 0.35
                if dimension == CreativeEvaluationDimension.OVERGRADING_RISK
                else 0.86
                if full
                else 0.52
            )
            for dimension in CreativeEvaluationDimension
        }
    )


def _execution(
    *,
    item_id: str,
    candidate_id: str,
    variant: CreativePipelineVariant,
    output_sha256: str,
) -> CreativeVariantExecution:
    executed_stages = list(creative_variant_stage_order(variant))
    disabled_stages = [
        stage
        for stage in CreativePipelineStage
        if stage not in executed_stages
    ]
    direction_count = (
        1
        if variant
        in {
            CreativePipelineVariant.RULE_BASELINE,
            CreativePipelineVariant.SINGLE_DIRECTION,
        }
        else 3
    )
    direction_signatures = (
        ["faithful", "amplified", "counterpoint"]
        if direction_count == 3
        else [variant.value]
    )
    direction_pairwise_distances = (
        [0.4, 0.5, 0.6] if direction_count == 3 else []
    )
    model_driven = variant != CreativePipelineVariant.RULE_BASELINE
    return CreativeVariantExecution(
        candidate_id=candidate_id,
        item_id=item_id,
        variant=variant,
        source_media_sha256=_sha(f"media:{item_id}"),
        source_graph_sha256=_sha(f"source-graph-digest:{item_id}"),
        source_graph_artifact_sha256=_sha(f"source-graph:{item_id}"),
        run_request_sha256=_sha(f"request:{candidate_id}"),
        pipeline_result_sha256=_sha(f"result:{candidate_id}"),
        output_sha256=output_sha256,
        executed_stages=executed_stages,
        disabled_stages=disabled_stages,
        stage_evidence_sha256={
            stage: _sha(f"execution:{candidate_id}:{stage.value}")
            for stage in executed_stages
        },
        model_identity_sha256=(
            [_sha(f"model:{candidate_id}")] if model_driven else []
        ),
        provider_response_ids=(
            [f"receipt:{candidate_id}"] if model_driven else []
        ),
        direction_count=direction_count,
        direction_signatures=direction_signatures,
        direction_pairwise_distances=direction_pairwise_distances,
        closed_book_director=variant
        in {
            CreativePipelineVariant.CLOSED_BOOK_NO_RAG,
            CreativePipelineVariant.SINGLE_DIRECTION,
            CreativePipelineVariant.NO_CRITIC,
            CreativePipelineVariant.NO_REFLECTION,
            CreativePipelineVariant.FULL_PIPELINE,
        },
        retrieval_input_to_director=(
            variant == CreativePipelineVariant.RAG_FIRST
        ),
        current_graph_unchanged=True,
        hard_qc_passed=True,
    )


def _bundle(
    evidence_class: CreativeEvidenceClass = CreativeEvidenceClass.FIXTURE,
) -> CreativeAgentEvaluationBundle:
    reviewers = [
        CreativeReviewer(
            reviewer_id=f"expert-{index}",
            years_experience=5 + index,
            roles=["colorist"],
            color_vision_screened=True,
            calibrated_display_confirmed=True,
        )
        for index in range(3)
    ]
    tags = list(CreativeChallengeTag)
    items: list[CreativeGoldItem] = []
    candidates: list[CreativeCandidateObservation] = []
    reviews: list[CreativePairReview] = []
    for item_index in range(12):
        item_id = f"creative-test-{item_index:02d}"
        items.append(
            CreativeGoldItem(
                item_id=item_id,
                source_group_id=f"source-{item_index:02d}",
                split="test",
                frozen=True,
                duration_seconds=60,
                media_origin=CreativeMediaOrigin.CAMERA_ORIGINAL,
                media_sha256=_sha(f"media:{item_id}"),
                annotation_sha256=_sha(f"annotation:{item_id}"),
                annotation_guideline_version="creative-gold/v1",
                evidence=[
                    CreativeGoldEvidence(
                        evidence_id=f"evidence:{item_id}",
                        scene_id="scene-01",
                        shot_id="shot-01",
                        frame_index=12,
                        region="subject and background",
                        observation="The source supports more than one restrained reading.",
                    )
                ],
                acceptable_visual_theses=[
                    "Preserve quiet separation.",
                    "Use a bounded counterpoint without changing scene facts.",
                ],
                scene_roles={"scene-01": "Establish the visual premise."},
                cliche_or_overgrading_risks=["Avoid generic blockbuster contrast."],
                continuity_criteria=["Keep neutral highlights continuous."],
                challenge_tags=[tags[item_index % len(tags)]],
                annotator_ids=[f"annotator-{item_index:02d}"],
                reviewer_ids=[f"annotation-reviewer-{item_index:02d}"],
                accepted=True,
            )
        )
        item_candidates: dict[CreativePipelineVariant, CreativeCandidateObservation] = {}
        for variant in CreativePipelineVariant:
            candidate_id = f"{item_id}:{variant.value}"
            output_sha256 = _sha(f"output:{item_id}:{variant.value}")
            execution = _execution(
                item_id=item_id,
                candidate_id=candidate_id,
                variant=variant,
                output_sha256=output_sha256,
            )
            candidate = CreativeCandidateObservation(
                candidate_id=candidate_id,
                item_id=item_id,
                variant=variant,
                output_sha256=output_sha256,
                execution=execution,
                direction_signatures=execution.direction_signatures,
                direction_pairwise_distances=(
                    execution.direction_pairwise_distances
                ),
                model_calls=(
                    0
                    if variant == CreativePipelineVariant.RULE_BASELINE
                    else 6
                    if variant == CreativePipelineVariant.FULL_PIPELINE
                    else 1
                ),
                input_tokens=1_200,
                output_tokens=300,
                cost_usd=0.12,
                rendered_frames=9,
                wall_seconds=20 + item_index,
                retries=item_index % 2,
                cache_hits=2,
                cache_lookups=4,
                peak_vram_mb=2_048,
                human_takeover=item_index == 0,
            )
            candidates.append(candidate)
            item_candidates[variant] = candidate
        full = item_candidates[CreativePipelineVariant.FULL_PIPELINE]
        comparisons = [
            variant
            for variant in CreativePipelineVariant
            if variant != CreativePipelineVariant.FULL_PIPELINE
        ]
        for comparison_index, variant in enumerate(comparisons):
            other = item_candidates[variant]
            pair_id = f"{item_id}:full:{variant.value}"
            global_pair_index = item_index * len(comparisons) + comparison_index
            for reviewer_index, reviewer in enumerate(reviewers):
                full_on_left = (global_pair_index + reviewer_index) % 2 == 0
                reviews.append(
                    CreativePairReview(
                        pair_id=pair_id,
                        item_id=item_id,
                        reviewer_id=reviewer.reviewer_id,
                        displayed_left_candidate_id=(
                            full.candidate_id if full_on_left else other.candidate_id
                        ),
                        displayed_right_candidate_id=(
                            other.candidate_id if full_on_left else full.candidate_id
                        ),
                        choice=(
                            CreativePairChoice.LEFT
                            if full_on_left
                            else CreativePairChoice.RIGHT
                        ),
                        left_scores=_scores(full=full_on_left),
                        right_scores=_scores(full=not full_on_left),
                    )
                )
    challenges = [
        CreativeChallengeResult(
            item_id=items[index].item_id,
            tag=tag,
            passed=True,
            detail="Frozen adversarial fixture preserved the system boundary.",
        )
        for index, tag in enumerate(tags)
    ]
    judge_records: list[CreativeJudgeRecord] = []
    pair_heads: dict[str, CreativePairReview] = {}
    for review in reviews:
        pair_heads.setdefault(review.pair_id, review)
    candidate_by_id = {candidate.candidate_id: candidate for candidate in candidates}
    for pair_index, (pair_id, review) in enumerate(sorted(pair_heads.items())):
        pair_candidate_ids = [
            review.displayed_left_candidate_id,
            review.displayed_right_candidate_id,
        ]
        full_id = next(
            candidate_id
            for candidate_id in pair_candidate_ids
            if candidate_by_id[candidate_id].variant
            == CreativePipelineVariant.FULL_PIPELINE
        )
        other_id = next(
            candidate_id for candidate_id in pair_candidate_ids if candidate_id != full_id
        )
        judge_records.extend(
            [
                CreativeJudgeRecord(
                    pair_id=pair_id,
                    item_id=review.item_id,
                    judge_id="director-self-judge",
                    model_id="shared-model",
                    model_revision="frozen-v1",
                    selected_candidate_id=full_id,
                    same_model_as_director=True,
                    evidence_grounded=True,
                ),
                CreativeJudgeRecord(
                    pair_id=pair_id,
                    item_id=review.item_id,
                    judge_id="independent-judge",
                    model_id="independent-model",
                    model_revision="frozen-v1",
                    selected_candidate_id=(
                        other_id if pair_index % 4 == 0 else full_id
                    ),
                    same_model_as_director=False,
                    evidence_grounded=pair_index % 5 != 0,
                ),
            ]
        )
    return CreativeAgentEvaluationBundle(
        evaluation_id="creative-agent-engineering-fixture",
        evidence_class=evidence_class,
        dataset_version="creative-fixture/v1",
        created_at=datetime(2026, 7, 30, 8, tzinfo=UTC),
        items=items,
        reviewers=reviewers,
        candidates=candidates,
        reviews=reviews,
        judge_records=judge_records,
        challenges=challenges,
    )


def _artifact(root: Path, relative_path: str, content: str) -> CreativeArtifactReference:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return CreativeArtifactReference(
        relative_path=relative_path,
        sha256=sha256_file(path),
    )


def _candidate_artifact(
    root: Path,
    candidate: CreativeCandidateObservation,
) -> CreativeCandidateArtifact:
    component = candidate.candidate_id.replace(":", "-")
    return CreativeCandidateArtifact(
        candidate_id=candidate.candidate_id,
        output=_artifact(
            root,
            f"candidates/{component}.txt",
            f"output:{candidate.item_id}:{candidate.variant.value}",
        ),
        source_graph=_artifact(
            root,
            f"source-graphs/{candidate.item_id}.json",
            f"source-graph:{candidate.item_id}",
        ),
        run_request=_artifact(
            root,
            f"execution/{component}/run-request.json",
            f"request:{candidate.candidate_id}",
        ),
        pipeline_result=_artifact(
            root,
            f"execution/{component}/pipeline-result.json",
            f"result:{candidate.candidate_id}",
        ),
        execution_evidence={
            stage.value: _artifact(
                root,
                f"execution/{component}/{stage.value}.json",
                f"execution:{candidate.candidate_id}:{stage.value}",
            )
            for stage in candidate.execution.executed_stages
        },
    )


def _production_bundle(root: Path) -> CreativeAgentEvaluationBundle:
    fixture = _bundle()
    payload = fixture.model_dump(mode="json")
    payload["evidence_class"] = CreativeEvidenceClass.PRODUCTION
    payload["production_manifest"] = {
        "relative_path": "production-manifest.json",
        "sha256": "0" * 64,
    }
    production = CreativeAgentEvaluationBundle.model_validate(payload)
    item_artifacts = [
        CreativeGoldArtifactSet(
            item_id=item.item_id,
            media=_artifact(
                root,
                f"media/{item.item_id}.txt",
                f"media:{item.item_id}",
            ),
            annotation=_artifact(
                root,
                f"annotations/{item.item_id}.json",
                f"annotation:{item.item_id}",
            ),
            license_evidence=_artifact(
                root,
                f"licenses/{item.item_id}.txt",
                f"Camera-original evaluation grant for {item.item_id}.",
            ),
        )
        for item in production.items
    ]
    candidate_artifacts = [
        _candidate_artifact(root, candidate)
        for candidate in production.candidates
    ]
    reviewer_attestations: list[CreativeReviewerAttestation] = []
    for reviewer in production.reviewers:
        reviews = [
            review.model_dump(mode="json")
            for review in production.reviews
            if review.reviewer_id == reviewer.reviewer_id
        ]
        source_submission = _artifact(
            root,
            f"reviewers/{reviewer.reviewer_id}-submission.json",
            f"submitted:{reviewer.reviewer_id}",
        )
        reviewer_attestations.append(
            CreativeReviewerAttestation(
                reviewer_id=reviewer.reviewer_id,
                attestation=_artifact(
                    root,
                    f"reviewers/{reviewer.reviewer_id}.txt",
                    (
                        f"{reviewer.reviewer_id} confirms independent review, "
                        "color-vision screening, and calibrated-display use."
                    ),
                ),
                source_submission=source_submission,
                review_response=_artifact(
                    root,
                    f"reviewers/{reviewer.reviewer_id}-response.json",
                    CreativeReviewerResponseEnvelope(
                        evaluation_id=production.evaluation_id,
                        dataset_version=production.dataset_version,
                        reviewer_id=reviewer.reviewer_id,
                        submitted_at=datetime(2026, 7, 30, 7, tzinfo=UTC),
                        source_submission_sha256=source_submission.sha256,
                        reviews=reviews,
                    ).model_dump_json(indent=2),
                ),
                qualification_approved_by="evaluation-coordinator",
                years_experience=reviewer.years_experience,
                roles=reviewer.roles,
                color_vision_screened=reviewer.color_vision_screened,
                calibrated_display_confirmed=reviewer.calibrated_display_confirmed,
                signed_at=datetime(2026, 7, 30, 7, tzinfo=UTC),
            )
        )
    manifest = CreativeProductionManifest(
        manifest_id="creative-production-test-manifest",
        evaluation_id=production.evaluation_id,
        dataset_version=production.dataset_version,
        created_at=datetime(2026, 7, 30, 7, tzinfo=UTC),
        authorized_by=["evaluation-owner"],
        authorized_at=datetime(2026, 7, 30, 7, tzinfo=UTC),
        item_artifacts=item_artifacts,
        candidate_artifacts=candidate_artifacts,
        reviewer_attestations=reviewer_attestations,
        **creative_bundle_component_digests(production),
    )
    manifest_path = root / "production-manifest.json"
    manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    payload["production_manifest"]["sha256"] = sha256_file(manifest_path)
    return CreativeAgentEvaluationBundle.model_validate(payload)


def test_creative_pair_plan_compares_full_pipeline_to_every_ablation() -> None:
    bundle = _bundle()

    pairs = build_creative_agent_review_pairs(bundle.candidates)

    assert len(pairs) == 12 * 7
    assert all(
        candidate_id.endswith(CreativePipelineVariant.FULL_PIPELINE.value)
        for candidate_id in (pair.candidate_a_id for pair in pairs)
    )
    assert len({pair.source_id for pair in pairs}) == 12


def test_ablation_variant_cannot_be_relabelled_without_matching_execution() -> None:
    payload = _bundle().model_dump(mode="json")
    payload["candidates"][0]["variant"] = CreativePipelineVariant.FULL_PIPELINE

    with pytest.raises(
        ValidationError,
        match="does not match its ablation execution",
    ):
        CreativeAgentEvaluationBundle.model_validate(payload)


def test_full_pipeline_requires_bound_reflection_execution() -> None:
    payload = _bundle().model_dump(mode="json")
    full = next(
        candidate
        for candidate in payload["candidates"]
        if candidate["variant"] == CreativePipelineVariant.FULL_PIPELINE
    )
    execution = full["execution"]
    execution["executed_stages"].remove(CreativePipelineStage.REFLECTION)
    execution["disabled_stages"].append(CreativePipelineStage.REFLECTION)
    execution["stage_evidence_sha256"].pop(
        CreativePipelineStage.REFLECTION.value
    )

    with pytest.raises(
        ValidationError,
        match="executed stages do not match the frozen ablation protocol",
    ):
        CreativeAgentEvaluationBundle.model_validate(payload)


def test_creative_evaluation_reports_all_metrics_but_fixture_stays_shadow() -> None:
    report = evaluate_creative_agent(_bundle())

    assert report.full_vs_rule_preference.value == 1
    assert report.full_vs_rule_preference.ci95_low > 0.5
    assert report.position_bias == 0
    assert report.operational_metrics.calls_per_minute_video == 6
    assert report.operational_metrics.rendered_frames_per_minute_video == 9
    assert report.challenge_coverage == {
        tag: True for tag in CreativeChallengeTag
    }
    assert all(
        passed
        for name, passed in report.gates.items()
        if name != "production_evidence"
    )
    assert report.gates["production_evidence"] is False
    assert report.judge_calibration.auxiliary_only is True
    assert report.judge_calibration.same_model_agreement == 1
    assert report.judge_calibration.independent_model_agreement == 0.75
    assert report.judge_calibration.self_evaluation_gap == 0.25
    assert report.judge_calibration.ungrounded_rate is not None
    assert report.release_status == "shadow_only"


def test_production_evidence_requires_verified_content_bound_artifacts(
    tmp_path: Path,
) -> None:
    production = _production_bundle(tmp_path)

    unverified = evaluate_creative_agent(production)
    assert not unverified.gates["production_evidence"]
    assert unverified.release_status == "shadow_only"

    source = tmp_path / "creative-production-evaluation.json"
    destination = tmp_path / "creative-production-report.json"
    source.write_text(production.model_dump_json(indent=2), encoding="utf-8")
    report = evaluate_creative_agent_file(source, destination)
    assert all(report.gates.values())
    assert report.production_evidence_audit is not None
    assert report.production_evidence_audit.passed
    assert report.release_status == "eligible_default"


def test_production_manifest_tampering_fails_closed(tmp_path: Path) -> None:
    production = _production_bundle(tmp_path)
    source = tmp_path / "creative-production-evaluation.json"
    destination = tmp_path / "creative-production-report.json"
    source.write_text(production.model_dump_json(indent=2), encoding="utf-8")
    (tmp_path / "media" / "creative-test-00.txt").write_text(
        "tampered media",
        encoding="utf-8",
    )

    report = evaluate_creative_agent_file(source, destination)

    assert report.production_evidence_audit is not None
    assert not report.production_evidence_audit.passed
    assert not report.gates["production_evidence"]
    assert report.release_status == "shadow_only"


def test_production_execution_evidence_tampering_fails_closed(
    tmp_path: Path,
) -> None:
    production = _production_bundle(tmp_path)
    source = tmp_path / "creative-production-evaluation.json"
    destination = tmp_path / "creative-production-report.json"
    source.write_text(production.model_dump_json(indent=2), encoding="utf-8")
    manifest = CreativeProductionManifest.model_validate_json(
        (tmp_path / "production-manifest.json").read_text(encoding="utf-8")
    )
    binding = manifest.candidate_artifacts[0]
    stage, reference = next(iter(binding.execution_evidence.items()))
    (tmp_path / reference.relative_path).write_text(
        "tampered execution evidence",
        encoding="utf-8",
    )

    report = evaluate_creative_agent_file(source, destination)

    assert report.production_evidence_audit is not None
    assert not report.production_evidence_audit.passed
    assert not report.gates["production_evidence"]
    assert report.release_status == "shadow_only"
    assert any(
        binding.candidate_id in issue
        and stage in issue
        and "digest mismatch" in issue
        for issue in report.production_evidence_audit.issues
    )


def test_creative_gold_and_security_boundaries_fail_closed() -> None:
    payload = _bundle().model_dump(mode="json")
    payload["items"][0]["acceptable_visual_theses"] = ["one right style", "ONE RIGHT STYLE"]
    with pytest.raises(ValidationError, match="multiple acceptable"):
        CreativeAgentEvaluationBundle.model_validate(payload)

    payload = _bundle().model_dump(mode="json")
    payload["challenges"][0]["external_text_received_tool_authority"] = True
    report = evaluate_creative_agent(
        CreativeAgentEvaluationBundle.model_validate(payload)
    )
    assert not report.gates["challenge_and_prompt_injection_suite"]
    assert report.release_status == "shadow_only"

    payload = _bundle().model_dump(mode="json")
    payload["evidence_class"] = CreativeEvidenceClass.PRODUCTION
    with pytest.raises(ValidationError, match="content-bound manifest"):
        CreativeAgentEvaluationBundle.model_validate(payload)


def test_creative_evaluation_file_writes_a_content_bound_report(
    tmp_path: Path,
) -> None:
    source = tmp_path / "creative-evaluation.json"
    destination = tmp_path / "creative-report.json"
    source.write_text(_bundle().model_dump_json(indent=2), encoding="utf-8")

    report = evaluate_creative_agent_file(source, destination)

    assert destination.is_file()
    assert report == type(report).model_validate_json(
        destination.read_text(encoding="utf-8")
    )
    assert report.input_sha256 == evaluate_creative_agent(_bundle()).input_sha256
