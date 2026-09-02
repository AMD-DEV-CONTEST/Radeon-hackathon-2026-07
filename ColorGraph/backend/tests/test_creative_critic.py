from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_creative_search import (
    _budget,
    _context,
    _DirectionalQC,
    _FakeRenderer,
    _graph,
    _strategies_and_inputs,
)

from colorgraph.agent.creative_contracts import (
    CreativeBrief,
    CritiqueDimension,
    CritiqueEvidenceRole,
)
from colorgraph.agent.creative_critic import (
    BlindCandidateAssessment,
    BlindCriticRegion,
    BlindCriticRequestContext,
    BlindDimensionScore,
    BlindLabel,
    BlindPairwiseCriticOutput,
    BlindVisualEvidence,
    CalibrationPreference,
    CreativeModelIdentity,
    CriticExpertCalibrationRecord,
    CriticModelRelationship,
    CriticViolationCode,
    VisualCriticValidationError,
    audit_blind_critic_output,
    build_blind_pairwise_critic_requests,
    build_critic_calibration_gate,
    run_blind_pairwise_critic,
    summarize_critic_reliability,
)
from colorgraph.agent.creative_provider import (
    CreativeProviderRuntime,
    CreativeRole,
    FakeCreativeModelProvider,
    RawProviderResponse,
    RuntimePolicy,
)
from colorgraph.agent.creative_search import (
    BudgetedCandidateSearchRunner,
    CandidateAttemptStatus,
    CandidateSearchStore,
    SearchCandidateRecord,
)


def _survivors_and_briefs(
    tmp_path: Path,
) -> tuple[list[SearchCandidateRecord], dict[str, CreativeBrief]]:
    graph = _graph()
    candidates, _ = _strategies_and_inputs(graph)
    result = BudgetedCandidateSearchRunner(
        renderer=_FakeRenderer(),
        qc_evaluator=_DirectionalQC(),
        store=CandidateSearchStore(tmp_path / "search"),
    ).run(
        run_id="run:critic-fixture",
        context=_context(graph),
        current_graph=graph,
        candidates=candidates,
        budget=_budget(frames=9),
    )
    return list(result.survivors), {
        item.brief.brief_id: item.brief for item in candidates
    }


def _requests(
    tmp_path: Path,
) -> tuple[
    tuple[BlindCriticRequestContext, BlindCriticRequestContext],
    list[SearchCandidateRecord],
]:
    records, briefs = _survivors_and_briefs(tmp_path)
    left, right = records[:2]
    requests = build_blind_pairwise_critic_requests(
        pair_id="pair:test",
        left_record=left,
        left_brief=briefs[left.brief_id],
        left_exceptions=[],
        right_record=right,
        right_brief=briefs[right.brief_id],
        right_exceptions=[],
        randomization_seed="frozen-seed",
    )
    return requests, records


def _evidence_id(
    context: BlindCriticRequestContext,
    *,
    label: BlindLabel,
    role: CritiqueEvidenceRole,
) -> str:
    return next(
        item.evidence_id
        for item in context.manifest
        if item.label == label and item.role == role
    )


def _critic_output(
    context: BlindCriticRequestContext,
    *,
    preferred_candidate_id: str | None,
    score_offset: float = 0,
    reason: str = "The declared intent is expressed coherently in the supplied regions.",
) -> BlindPairwiseCriticOutput:
    assessments = []
    for label in BlindLabel:
        candidate_id = context.label_to_candidate_id[label]
        candidate_evidence = _evidence_id(
            context,
            label=label,
            role=CritiqueEvidenceRole.CANDIDATE,
        )
        source_evidence = _evidence_id(
            context,
            label=label,
            role=CritiqueEvidenceRole.SOURCE,
        )
        preferred = candidate_id == preferred_candidate_id
        assessments.append(
            BlindCandidateAssessment(
                label=label,
                scores=[
                    BlindDimensionScore(
                        dimension=dimension,
                        score=(
                            (0.18 if preferred else 0.39)
                            if dimension == CritiqueDimension.OVERGRADING_RISK
                            else (0.82 if preferred else 0.61)
                        )
                        + score_offset,
                        confidence=0.8,
                        evidence=[
                            BlindVisualEvidence(
                                evidence_id=candidate_evidence,
                                region=BlindCriticRegion(
                                    x=0,
                                    y=0,
                                    width=1,
                                    height=1,
                                ),
                                observation=(
                                    "The candidate frame preserves a legible subject "
                                    "relationship."
                                ),
                            )
                        ],
                        counterevidence=[
                            BlindVisualEvidence(
                                evidence_id=source_evidence,
                                region=BlindCriticRegion(
                                    x=0,
                                    y=0,
                                    width=1,
                                    height=1,
                                ),
                                observation=(
                                    "The source frame provides the comparison boundary."
                                ),
                            )
                        ],
                        concise_reason=reason,
                    )
                    for dimension in CritiqueDimension
                ],
            )
        )
    preferred_label = "tie"
    if preferred_candidate_id is not None:
        preferred_label = next(
            label.value
            for label, candidate_id in context.label_to_candidate_id.items()
            if candidate_id == preferred_candidate_id
        )
    return BlindPairwiseCriticOutput(
        assessments=assessments,
        preferred_label=preferred_label,
        preference_confidence=0.83,
        pairwise_evidence_ids=[
            _evidence_id(
                context,
                label=label,
                role=CritiqueEvidenceRole.CANDIDATE,
            )
            for label in BlindLabel
        ],
        pairwise_reason="One treatment supports its own brief more coherently.",
    )


def _runtime(
    outputs: list[BlindPairwiseCriticOutput],
    *,
    provider_id: str = "critic-provider",
    model_id: str = "critic-model",
    model_revision: str = "critic-revision",
) -> CreativeProviderRuntime:
    provider = FakeCreativeModelProvider(
        responses=[
            RawProviderResponse(text=output.model_dump_json())
            for output in outputs
        ],
        provider_id=provider_id,
        model_id=model_id,
        model_revision=model_revision,
    )
    return CreativeProviderRuntime(
        {role: provider for role in CreativeRole},
        policy=RuntimePolicy(maximum_retries=0),
    )


def _director_identity() -> CreativeModelIdentity:
    return CreativeModelIdentity(
        provider_id="director-provider",
        model_id="director-model",
        model_revision="director-revision",
        prompt_version="closed-book-director/v2",
    )


def _critic_identity() -> CreativeModelIdentity:
    return CreativeModelIdentity(
        provider_id="critic-provider",
        model_id="critic-model",
        model_revision="critic-revision",
        prompt_version="blind-visual-critic/v3",
    )


def _calibration_gate():
    records = []
    for relationship in CriticModelRelationship:
        for index in range(24):
            expert = (
                CalibrationPreference.LEFT
                if index % 2 == 0
                else CalibrationPreference.RIGHT
            )
            critic = expert
            if (
                relationship == CriticModelRelationship.SAME_AS_DIRECTOR
                and index % 3 == 0
            ):
                critic = (
                    CalibrationPreference.RIGHT
                    if expert == CalibrationPreference.LEFT
                    else CalibrationPreference.LEFT
                )
            records.append(
                CriticExpertCalibrationRecord(
                    record_id=f"{relationship.value}:{index}",
                    pair_id=f"pair:{relationship.value}:{index}",
                    source_id=f"source:{relationship.value}:{index}",
                    model_relationship=relationship,
                    critic_preference=critic,
                    expert_preference=expert,
                    position_swap_consistent=True,
                    shortcut_violation=False,
                    unsupported_evidence=False,
                )
            )
    return build_critic_calibration_gate(
        records,
        deployment_critic_identity=_critic_identity(),
        director_identity=_director_identity(),
    )


def test_blind_requests_hide_candidate_recipe_and_swap_positions(
    tmp_path: Path,
) -> None:
    requests, records = _requests(tmp_path)
    first, second = requests

    for context in requests:
        payload = json.loads(context.request.prompt)
        assert [item["label"] for item in payload["candidates"]] == ["A", "B"]
        assert context.request.prompt_version == "blind-visual-critic/v3"
        assert context.request.max_output_tokens == 8_192
        assert "exactly two assessments" in context.request.prompt
        assert len(context.request.images) == 18
        assert all(item.asset_id.startswith(("A:", "B:")) for item in context.request.images)
        manifest = {item.evidence_id: item for item in context.manifest}
        hard_contract = payload["hard_contract"]
        assert hard_contract["pairwise_evidence_ids"] == [
            hard_contract["labels"][label.value]["evidence_id"]
            for label in BlindLabel
        ]
        for label in BlindLabel:
            binding = hard_contract["labels"][label.value]
            assert manifest[binding["evidence_id"]].role == (
                CritiqueEvidenceRole.CANDIDATE
            )
            assert manifest[binding["counterevidence_id"]].role == (
                CritiqueEvidenceRole.SOURCE
            )
            assert binding["region"] == {
                "x": 0.0,
                "y": 0.0,
                "width": 1.0,
                "height": 1.0,
            }
        for record in records[:2]:
            assert record.candidate_id not in context.request.prompt
            assert record.strategy_id not in context.request.prompt
            assert record.graph_path not in context.request.prompt
            assert record.contract_path not in context.request.prompt
            assert context.qc_digests[record.candidate_id] in context.request.prompt

    assert first.label_to_candidate_id[BlindLabel.A] == second.label_to_candidate_id[
        BlindLabel.B
    ]
    assert first.label_to_candidate_id[BlindLabel.B] == second.label_to_candidate_id[
        BlindLabel.A
    ]
    assert first.blind_order_digest == second.blind_order_digest


async def test_pairwise_run_unblinds_grounded_scores_and_requires_calibration(
    tmp_path: Path,
) -> None:
    requests, records = _requests(tmp_path)
    preferred = records[0].candidate_id
    outputs = [
        _critic_output(context, preferred_candidate_id=preferred)
        for context in requests
    ]

    report = await run_blind_pairwise_critic(
        _runtime(outputs),
        requests=requests,
        director_identity=_director_identity(),
    )

    assert report.preferred_candidate_id == preferred
    assert report.position_swap_consistent is True
    assert report.maximum_swapped_score_delta == 0
    assert report.auto_selection_allowed is False
    assert report.calibration_authorized is False
    assert report.self_evaluation_model is False
    assert len(report.critiques) == 2
    assert all(len(item.scores) == len(CritiqueDimension) for item in report.critiques)
    for critique in report.critiques:
        assert critique.technical_integrity_sha256 == requests[0].qc_digests[
            critique.candidate_id
        ]
        assert all(score.frame_regions for score in critique.scores)
        assert all(score.counter_frame_regions for score in critique.scores)
        assert all(
            region.role == CritiqueEvidenceRole.CANDIDATE
            for score in critique.scores
            for region in score.frame_regions
        )


async def test_pairwise_run_repairs_both_blind_orders_when_regions_are_not_normalized(
    tmp_path: Path,
) -> None:
    requests, records = _requests(tmp_path)
    preferred = records[0].candidate_id
    valid_outputs = [
        _critic_output(context, preferred_candidate_id=preferred)
        for context in requests
    ]

    def unnormalized(output: BlindPairwiseCriticOutput) -> BlindPairwiseCriticOutput:
        assessments = []
        for assessment in output.assessments:
            scores = []
            for score in assessment.scores:
                region = BlindCriticRegion(
                    x=100,
                    y=100,
                    width=800,
                    height=800,
                )
                scores.append(
                    score.model_copy(
                        update={
                            "evidence": [
                                score.evidence[0].model_copy(
                                    update={"region": region}
                                )
                            ],
                            "counterevidence": [
                                score.counterevidence[0].model_copy(
                                    update={"region": region}
                                )
                            ],
                        }
                    )
                )
            assessments.append(
                assessment.model_copy(update={"scores": scores})
            )
        return output.model_copy(update={"assessments": assessments})

    runtime = _runtime(
        [
            *(unnormalized(output) for output in valid_outputs),
            *valid_outputs,
        ]
    )
    report = await run_blind_pairwise_critic(
        runtime,
        requests=requests,
        director_identity=_director_identity(),
    )
    provider = runtime.providers[CreativeRole.CRITIC]

    assert report.position_swap_consistent
    assert all(item.valid for item in report.output_audits)
    assert all(
        item.prompt_version == "blind-visual-critic/v3-repair1"
        for item in report.provider_audits
    )
    assert isinstance(provider, FakeCreativeModelProvider)
    assert provider.calls == 4


async def test_calibration_enables_selection_but_a_tie_never_does(
    tmp_path: Path,
) -> None:
    requests, records = _requests(tmp_path)
    preferred = records[0].candidate_id
    selected = await run_blind_pairwise_critic(
        _runtime(
            [
                _critic_output(context, preferred_candidate_id=preferred)
                for context in requests
            ]
        ),
        requests=requests,
        director_identity=_director_identity(),
        calibration_gate=_calibration_gate(),
    )
    tied = await run_blind_pairwise_critic(
        _runtime(
            [
                _critic_output(context, preferred_candidate_id=None)
                for context in requests
            ]
        ),
        requests=requests,
        director_identity=_director_identity(),
        calibration_gate=_calibration_gate(),
    )

    assert selected.auto_selection_allowed is True
    assert tied.position_swap_consistent is True
    assert tied.preferred_candidate_id is None
    assert tied.auto_selection_allowed is False


async def test_position_preference_and_score_drift_fail_closed(
    tmp_path: Path,
) -> None:
    requests, _ = _requests(tmp_path)
    first_preference = requests[0].label_to_candidate_id[BlindLabel.A]
    second_preference = requests[1].label_to_candidate_id[BlindLabel.A]
    outputs = [
        _critic_output(
            requests[0],
            preferred_candidate_id=first_preference,
        ),
        _critic_output(
            requests[1],
            preferred_candidate_id=second_preference,
            score_offset=0.16,
        ),
    ]

    report = await run_blind_pairwise_critic(
        _runtime(outputs),
        requests=requests,
        director_identity=_director_identity(),
        calibration_gate=_calibration_gate(),
        maximum_swapped_score_delta=0.15,
    )

    assert report.position_swap_consistent is False
    assert report.maximum_swapped_score_delta == pytest.approx(0.37)
    assert report.preferred_candidate_id is None
    assert report.auto_selection_allowed is False


def test_output_audit_rejects_unknown_cross_label_and_missing_counterevidence(
    tmp_path: Path,
) -> None:
    requests, records = _requests(tmp_path)
    context = requests[0]
    output = _critic_output(
        context,
        preferred_candidate_id=records[0].candidate_id,
    )
    first_assessment = output.assessments[0]
    first_score = first_assessment.scores[0]
    other_label = (
        BlindLabel.B if first_assessment.label == BlindLabel.A else BlindLabel.A
    )
    cross_id = _evidence_id(
        context,
        label=other_label,
        role=CritiqueEvidenceRole.CANDIDATE,
    )
    broken_score = first_score.model_copy(
        update={
            "evidence": [
                BlindVisualEvidence(
                    evidence_id="unknown:asset",
                    region=BlindCriticRegion(x=0, y=0, width=100, height=100),
                    observation="This identifier was not supplied.",
                ),
                BlindVisualEvidence(
                    evidence_id=cross_id,
                    region=BlindCriticRegion(x=0, y=0, width=1, height=1),
                    observation="This belongs to the other blind label.",
                ),
            ],
            "counterevidence": [
                BlindVisualEvidence(
                    evidence_id=cross_id,
                    region=BlindCriticRegion(x=0, y=0, width=1, height=1),
                    observation="This is not valid same-label counterevidence.",
                )
            ],
        }
    )
    broken_assessment = first_assessment.model_copy(
        update={"scores": [broken_score, *first_assessment.scores[1:]]}
    )
    broken = output.model_copy(
        update={"assessments": [broken_assessment, output.assessments[1]]}
    )

    audit = audit_blind_critic_output(broken, context=context)
    codes = {item.code for item in audit.violations}

    assert audit.valid is False
    assert CriticViolationCode.UNKNOWN_EVIDENCE in codes
    assert CriticViolationCode.CROSS_LABEL_EVIDENCE in codes
    assert CriticViolationCode.INVALID_REGION in codes
    assert CriticViolationCode.MISSING_CANDIDATE_EVIDENCE in codes
    assert CriticViolationCode.MISSING_COUNTEREVIDENCE in codes


@pytest.mark.parametrize(
    "shortcut",
    [
        "Brighter is better.",
        "More saturation means better.",
        "Higher contrast is better.",
        "A blockbuster landscape is better.",
        "Blue snow means cinematic.",
        "Cyan snow is cinematic.",
        "More HDR means better.",
        "Crushed foreground is better.",
    ],
)
def test_output_audit_rejects_aesthetic_shortcuts(
    tmp_path: Path,
    shortcut: str,
) -> None:
    requests, records = _requests(tmp_path)
    output = _critic_output(
        requests[0],
        preferred_candidate_id=records[0].candidate_id,
        reason=shortcut,
    )

    audit = audit_blind_critic_output(output, context=requests[0])

    assert audit.valid is False
    assert any(
        item.code == CriticViolationCode.BIAS_SHORTCUT
        for item in audit.violations
    )


async def test_invalid_provider_output_raises_audited_validation_error(
    tmp_path: Path,
) -> None:
    requests, records = _requests(tmp_path)
    outputs = [
        _critic_output(
            context,
            preferred_candidate_id=records[0].candidate_id,
            reason="Brighter is better.",
        )
        for context in requests
    ]

    with pytest.raises(VisualCriticValidationError) as raised:
        await run_blind_pairwise_critic(
            _runtime([*outputs, *outputs]),
            requests=requests,
            director_identity=_director_identity(),
        )

    assert raised.value.audit.valid is False
    assert any(
        item.code == CriticViolationCode.BIAS_SHORTCUT
        for item in raised.value.audit.violations
    )


def test_request_rejects_a_candidate_that_failed_hard_qc(tmp_path: Path) -> None:
    records, briefs = _survivors_and_briefs(tmp_path)
    left, right = records[:2]
    failed_qc = left.qc.model_copy(update={"hard_passed": False})
    failed = left.model_copy(
        update={
            "status": CandidateAttemptStatus.HARD_FAIL,
            "qc": failed_qc,
        }
    )

    with pytest.raises(ValueError, match="only accepts deterministic QC survivors"):
        build_blind_pairwise_critic_requests(
            pair_id="pair:hard-fail",
            left_record=failed,
            left_brief=briefs[left.brief_id],
            left_exceptions=[],
            right_record=right,
            right_brief=briefs[right.brief_id],
            right_exceptions=[],
            randomization_seed="seed",
        )


async def test_reliability_metrics_and_self_evaluation_identity(
    tmp_path: Path,
) -> None:
    requests, records = _requests(tmp_path)
    preferred = records[0].candidate_id
    identity = CreativeModelIdentity(
        provider_id="same-provider",
        model_id="same-model",
        model_revision="same-revision",
        prompt_version="director/v1",
    )
    report = await run_blind_pairwise_critic(
        _runtime(
            [
                _critic_output(context, preferred_candidate_id=preferred)
                for context in requests
            ],
            provider_id=identity.provider_id,
            model_id=identity.model_id,
            model_revision=identity.model_revision,
        ),
        requests=requests,
        director_identity=identity,
    )

    metrics = summarize_critic_reliability([report])

    assert report.self_evaluation_model is True
    assert metrics.report_count == 1
    assert metrics.position_inconsistency_rate == 0
    assert metrics.shortcut_violation_rate == 0
    assert metrics.unsupported_evidence_rate == 0
    assert metrics.auto_selection_rate == 0
    assert report.calibration_authorized is False
    assert any(
        "self-evaluation" in reason
        for reason in report.calibration_failure_reasons
    )


def test_expert_calibration_gate_reports_independent_and_self_model_results() -> None:
    gate = _calibration_gate()

    assert gate.authorized is True
    assert gate.independent_metrics.record_count == 24
    assert gate.independent_metrics.preference_accuracy == 1
    assert gate.independent_metrics.preference_correlation == 1
    assert gate.independent_metrics.accuracy_ci95_low > 0.8
    assert gate.self_evaluation_metrics.record_count == 24
    assert gate.self_evaluation_metrics.preference_accuracy < 0.7
    assert gate.failure_reasons == []


async def test_calibration_gate_is_bound_to_the_runtime_model_identity(
    tmp_path: Path,
) -> None:
    requests, records = _requests(tmp_path)
    preferred = records[0].candidate_id
    report = await run_blind_pairwise_critic(
        _runtime(
            [
                _critic_output(context, preferred_candidate_id=preferred)
                for context in requests
            ],
            model_revision="uncalibrated-revision",
        ),
        requests=requests,
        director_identity=_director_identity(),
        calibration_gate=_calibration_gate(),
    )

    assert report.position_swap_consistent is True
    assert report.preferred_candidate_id == preferred
    assert report.calibration_authorized is False
    assert report.auto_selection_allowed is False
    assert any(
        "runtime Critic identity differs" in reason
        for reason in report.calibration_failure_reasons
    )
