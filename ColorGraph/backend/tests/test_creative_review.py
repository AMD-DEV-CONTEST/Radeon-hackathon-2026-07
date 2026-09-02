from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from test_creative_agent_evaluation import (
    _bundle,
    _candidate_artifact,
    _scores,
)
from test_creative_critic import (
    _critic_identity,
    _critic_output,
    _director_identity,
    _requests,
    _runtime,
)

from colorgraph.agent.creative_critic import (
    CriticCalibrationThresholds,
    PairwiseVisualCriticReport,
    run_blind_pairwise_critic,
)
from colorgraph.evaluation.creative_agent import (
    CreativeAgentEvaluationConfig,
    CreativeChallengeTag,
    CreativeEvaluationDimension,
    CreativePairChoice,
    CreativePipelineVariant,
    evaluate_creative_agent_file,
)
from colorgraph.evaluation.creative_critic_calibration import (
    CreativeCriticCalibrationSource,
    CreativeCriticReportBinding,
    load_creative_critic_calibration,
)
from colorgraph.evaluation.creative_intake import (
    CreativeArtifactReference,
    CreativeGoldArtifactSet,
    CreativeProductionManifest,
    sha256_file,
)
from colorgraph.evaluation.creative_review import (
    CreativeBlindPairResponse,
    CreativeReviewDraft,
    CreativeReviewerAssignment,
    CreativeReviewerRegistration,
    CreativeReviewerSubmission,
    CreativeReviewPanel,
    assemble_creative_production_evaluation,
    create_creative_review_freeze,
)

NOW = datetime(2026, 7, 30, 9, tzinfo=UTC)


def _artifact(
    root: Path,
    relative_path: str,
    content: str,
) -> CreativeArtifactReference:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return CreativeArtifactReference(
        relative_path=relative_path,
        sha256=sha256_file(path),
    )


def _inputs(root: Path) -> tuple[Path, Path]:
    fixture = _bundle()
    items = fixture.items[:3]
    item_ids = {item.item_id for item in items}
    candidates = [
        item for item in fixture.candidates if item.item_id in item_ids
    ]
    challenges = [
        item for item in fixture.challenges if item.item_id in item_ids
    ]
    item_artifacts = [
        CreativeGoldArtifactSet(
            item_id=item.item_id,
            media=_artifact(
                root,
                f"source/media/{item.item_id}.txt",
                f"media:{item.item_id}",
            ),
            annotation=_artifact(
                root,
                f"source/annotations/{item.item_id}.json",
                f"annotation:{item.item_id}",
            ),
            license_evidence=_artifact(
                root,
                f"source/licenses/{item.item_id}.txt",
                f"camera-original grant:{item.item_id}",
            ),
        )
        for item in items
    ]
    candidate_artifacts = [
        _candidate_artifact(root, candidate)
        for candidate in candidates
    ]
    draft = CreativeReviewDraft(
        evaluation_id="creative-production-workflow",
        dataset_version="creative-production/v1",
        created_at=NOW,
        authorized_by=["evaluation-owner"],
        authorized_at=NOW,
        items=items,
        candidates=candidates,
        judge_records=[],
        challenges=challenges,
        config=CreativeAgentEvaluationConfig(
            minimum_reviewers=3,
            minimum_rule_baseline_pairs=3,
            minimum_preference_ci95_low=0.4,
            maximum_position_bias=0.5,
            minimum_direction_diversity=0.15,
            required_variants=list(CreativePipelineVariant),
            required_challenges=[
                item.tag for item in challenges
            ],
        ),
        item_artifacts=item_artifacts,
        candidate_artifacts=candidate_artifacts,
    )
    draft_path = root / "draft.json"
    draft_path.write_text(draft.model_dump_json(indent=2), encoding="utf-8")

    registrations: list[CreativeReviewerRegistration] = []
    for reviewer in fixture.reviewers:
        registrations.append(
            CreativeReviewerRegistration(
                reviewer=reviewer,
                qualification_attestation=_artifact(
                    root,
                    f"panel/{reviewer.reviewer_id}.txt",
                    f"approved qualification:{reviewer.reviewer_id}",
                ),
                qualification_approved_by="panel-coordinator",
                signed_at=NOW,
            )
        )
    panel = CreativeReviewPanel(
        evaluation_id=draft.evaluation_id,
        dataset_version=draft.dataset_version,
        registered_at=NOW,
        panel_approved_by=["panel-owner"],
        reviewers=registrations,
    )
    panel_path = root / "panel.json"
    panel_path.write_text(panel.model_dump_json(indent=2), encoding="utf-8")
    return draft_path, panel_path


def _submissions(
    root: Path,
    manifest,
) -> list[Path]:
    output: list[Path] = []
    for binding in manifest.assignments:
        assignment_path = root / binding.assignment.relative_path
        assignment = CreativeReviewerAssignment.model_validate_json(
            assignment_path.read_text(encoding="utf-8")
        )
        answer_key = {item.pair_id: item for item in binding.answer_key}
        responses: list[CreativeBlindPairResponse] = []
        for pair in assignment.pairs:
            key = answer_key[pair.pair_id]
            full_on_left = key.left_candidate_id.endswith(
                CreativePipelineVariant.FULL_PIPELINE.value
            )
            assert (
                full_on_left
                or key.right_candidate_id.endswith(
                    CreativePipelineVariant.FULL_PIPELINE.value
                )
            )
            responses.append(
                CreativeBlindPairResponse(
                    pair_id=pair.pair_id,
                    left_asset_id=pair.left.asset_id,
                    right_asset_id=pair.right.asset_id,
                    choice=(
                        CreativePairChoice.LEFT
                        if full_on_left
                        else CreativePairChoice.RIGHT
                    ),
                    left_scores=_scores(full=full_on_left),
                    right_scores=_scores(full=not full_on_left),
                )
            )
        submission = CreativeReviewerSubmission(
            freeze_id=manifest.freeze_id,
            evaluation_id=manifest.evaluation_id,
            dataset_version=manifest.dataset_version,
            reviewer_id=binding.reviewer_id,
            assignment_sha256=binding.assignment.sha256,
            submitted_at=NOW,
            responses=responses,
        )
        path = root / f"{binding.reviewer_id}-submission.json"
        path.write_text(
            submission.model_dump_json(indent=2),
            encoding="utf-8",
        )
        output.append(path)
    return output


def test_review_freeze_and_assembly_bind_independent_expert_submissions(
    tmp_path: Path,
) -> None:
    draft_path, panel_path = _inputs(tmp_path)
    freeze_root = tmp_path / "freeze"

    manifest = create_creative_review_freeze(
        draft_path,
        panel_path,
        freeze_root,
    )

    assert len(manifest.assignments) == 3
    assignment_text = (
        freeze_root
        / manifest.assignments[0].assignment.relative_path
    ).read_text(encoding="utf-8")
    assert "full_pipeline" not in assignment_text
    submissions = _submissions(freeze_root, manifest)
    bundle_path = freeze_root / "evaluation-input.json"
    bundle = assemble_creative_production_evaluation(
        freeze_root / "creative-review-freeze.json",
        submissions,
        bundle_path,
    )

    assert bundle.evidence_class.value == "production"
    assert len(bundle.reviewers) == 3
    assert len(bundle.reviews) == 63
    report = evaluate_creative_agent_file(
        bundle_path,
        freeze_root / "evaluation-report.json",
    )
    assert report.production_evidence_audit is not None
    assert report.production_evidence_audit.passed
    assert report.production_evidence_audit.checked_reviewer_responses == 3
    assert report.release_status == "eligible_default"
    assert all(report.gates.values())

    source_submission = (
        freeze_root
        / bundle.production_manifest.relative_path
    )
    assert source_submission.is_file()


def test_production_evaluation_fails_closed_after_submission_tampering(
    tmp_path: Path,
) -> None:
    draft_path, panel_path = _inputs(tmp_path)
    freeze_root = tmp_path / "freeze"
    manifest = create_creative_review_freeze(
        draft_path,
        panel_path,
        freeze_root,
    )
    submissions = _submissions(freeze_root, manifest)
    bundle_path = freeze_root / "evaluation-input.json"
    bundle = assemble_creative_production_evaluation(
        freeze_root / "creative-review-freeze.json",
        submissions,
        bundle_path,
    )
    production_manifest_path = (
        freeze_root / bundle.production_manifest.relative_path
    )
    production_manifest = CreativeProductionManifest.model_validate_json(
        production_manifest_path.read_text(encoding="utf-8")
    )
    reviewer_id = manifest.assignments[0].reviewer_id
    reviewer_binding = next(
        item
        for item in production_manifest.reviewer_attestations
        if item.reviewer_id == reviewer_id
    )
    response_path = (
        freeze_root / reviewer_binding.source_submission.relative_path
    )
    response_path.write_text("tampered", encoding="utf-8")

    report = evaluate_creative_agent_file(
        bundle_path,
        freeze_root / "tampered-report.json",
    )

    assert report.release_status == "shadow_only"
    assert report.production_evidence_audit is not None
    assert not report.production_evidence_audit.passed
    assert any(
        reviewer_id in issue and "digest mismatch" in issue
        for issue in report.production_evidence_audit.issues
    )


def test_dimension_fixture_still_covers_every_review_score() -> None:
    assert set(_scores(full=True).values) == set(CreativeEvaluationDimension)
    assert set(CreativeChallengeTag)


async def test_critic_calibration_is_derived_from_bound_expert_and_report_evidence(
    tmp_path: Path,
) -> None:
    draft_path, panel_path = _inputs(tmp_path)
    freeze_root = tmp_path / "freeze"
    manifest = create_creative_review_freeze(
        draft_path,
        panel_path,
        freeze_root,
    )
    bundle_path = freeze_root / "evaluation-input.json"
    bundle = assemble_creative_production_evaluation(
        freeze_root / "creative-review-freeze.json",
        _submissions(freeze_root, manifest),
        bundle_path,
    )
    critic_requests, critic_records = _requests(tmp_path / "critic")
    fixture_preferred = critic_records[0].candidate_id
    independent = await run_blind_pairwise_critic(
        _runtime(
            [
                _critic_output(
                    context,
                    preferred_candidate_id=fixture_preferred,
                )
                for context in critic_requests
            ]
        ),
        requests=critic_requests,
        director_identity=_director_identity(),
    )
    self_evaluation = await run_blind_pairwise_critic(
        _runtime(
            [
                _critic_output(
                    context,
                    preferred_candidate_id=fixture_preferred,
                )
                for context in critic_requests
            ],
            provider_id=_director_identity().provider_id,
            model_id=_director_identity().model_id,
            model_revision=_director_identity().model_revision,
        ),
        requests=critic_requests,
        director_identity=_director_identity(),
    )
    assert isinstance(independent, PairwiseVisualCriticReport)
    assert isinstance(self_evaluation, PairwiseVisualCriticReport)
    pair_reviews = {}
    for review in bundle.reviews:
        pair_reviews.setdefault(review.pair_id, review)
    selected_pairs = list(sorted(pair_reviews.items()))[:5]
    bindings: list[CreativeCriticReportBinding] = []
    reports_root = freeze_root / "critic-reports"
    reports_root.mkdir()
    for relationship, base_report in (
        ("independent", independent),
        ("same", self_evaluation),
    ):
        for index, (pair_id, review) in enumerate(selected_pairs):
            pair_candidates = [
                review.displayed_left_candidate_id,
                review.displayed_right_candidate_id,
            ]
            winner = next(
                candidate_id
                for candidate_id in pair_candidates
                if candidate_id.endswith(
                    CreativePipelineVariant.FULL_PIPELINE.value
                )
            )
            loser = next(
                candidate_id
                for candidate_id in pair_candidates
                if candidate_id != winner
            )
            left, right = (
                (winner, loser) if index % 2 == 0 else (loser, winner)
            )
            report = base_report.model_copy(
                update={
                    "pair_id": pair_id,
                    "preferred_candidate_id": winner,
                    "critiques": [
                        base_report.critiques[0].model_copy(
                            update={"candidate_id": left}
                        ),
                        base_report.critiques[1].model_copy(
                            update={"candidate_id": right}
                        ),
                    ],
                }
            )
            report_path = reports_root / f"{relationship}-{index}.json"
            report_path.write_text(
                report.model_dump_json(indent=2),
                encoding="utf-8",
            )
            bindings.append(
                CreativeCriticReportBinding(
                    record_id=f"{relationship}:{index}",
                    pair_id=pair_id,
                    item_id=review.item_id,
                    left_candidate_id=left,
                    right_candidate_id=right,
                    report=CreativeArtifactReference(
                        relative_path=report_path.relative_to(
                            freeze_root
                        ).as_posix(),
                        sha256=sha256_file(report_path),
                    ),
                )
            )
    source = CreativeCriticCalibrationSource(
        calibration_id="production-critic-calibration-v1",
        created_at=NOW,
        authorized_by=["calibration-owner"],
        authorized_at=NOW,
        evaluation_bundle=CreativeArtifactReference(
            relative_path=bundle_path.relative_to(freeze_root).as_posix(),
            sha256=sha256_file(bundle_path),
        ),
        deployment_critic_identity=_critic_identity(),
        director_identity=_director_identity(),
        thresholds=CriticCalibrationThresholds(
            minimum_records_per_relationship=5,
            minimum_decisive_coverage=0.75,
            minimum_accuracy_ci95_low=0.5,
            minimum_preference_correlation=0.3,
            maximum_position_inconsistency_rate=0.1,
            maximum_shortcut_violation_rate=0,
            maximum_unsupported_evidence_rate=0,
        ),
        reports=bindings,
    )
    source_path = freeze_root / "critic-calibration-source.json"
    source_path.write_text(
        source.model_dump_json(indent=2),
        encoding="utf-8",
    )

    loaded = load_creative_critic_calibration(source_path)

    assert loaded.gate is not None
    assert loaded.gate.authorized
    assert loaded.audit.evidence_integrity_passed
    assert loaded.audit.calibration_authorized
    assert loaded.audit.qualified_reviewer_count == 3
    assert loaded.audit.checked_report_count == 10
    assert loaded.audit.independent_record_count == 5
    assert loaded.audit.self_evaluation_record_count == 5

    first_report = freeze_root / bindings[0].report.relative_path
    first_report.write_text("tampered", encoding="utf-8")
    tampered = load_creative_critic_calibration(source_path)
    assert tampered.gate is None
    assert not tampered.audit.evidence_integrity_passed
