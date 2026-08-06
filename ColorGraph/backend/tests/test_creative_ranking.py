from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from test_creative_critic import (
    _calibration_gate,
    _critic_output,
    _director_identity,
    _requests,
    _runtime,
)

from colorgraph.agent.creative_contracts import (
    CompiledCandidate,
    CritiqueDimension,
    ExceptionApprovalSource,
    ExceptionMetric,
    IntentionalException,
    IntentionalExceptionKind,
    ProtectedAttribute,
    StrategyScope,
)
from colorgraph.agent.creative_critic import run_blind_pairwise_critic
from colorgraph.agent.creative_ranking import (
    HumanPreferenceEvidence,
    RankingGate,
    TemporalConsistencyEvidence,
    rank_creative_candidates,
    ranking_order_for_search,
)
from colorgraph.agent.creative_search import CandidateAttemptStatus

EVALUATED_AT = datetime(2026, 7, 30, 2, tzinfo=UTC)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _temporal(record, *, passed: bool = True) -> TemporalConsistencyEvidence:
    from colorgraph.agent.creative_contracts import canonical_sha256

    rendered_digest = canonical_sha256(
        {
            "candidate_frames": [
                {
                    "frame_index": item.frame_index,
                    "time_seconds": item.time_seconds,
                    "sha256": item.candidate_sha256,
                }
                for item in record.samples
            ]
        }
    )
    return TemporalConsistencyEvidence(
        candidate_id=record.candidate_id,
        scene_id=record.scene_id,
        rendered_sha256=rendered_digest,
        evaluated_frame_indices=[item.frame_index for item in record.samples],
        within_shot_passed=passed,
        between_shot_applicable=False,
        between_shot_passed=True,
        mask_continuity_passed=passed,
        evidence_ids=[
            f"temporal:{record.candidate_id}:{item.frame_index}"
            for item in record.samples
        ],
        failure_reasons=(
            [] if passed else ["Synthetic within-shot and mask instability."]
        ),
    )


async def _ranking_fixture(
    tmp_path: Path,
    *,
    calibration_authorized: bool = False,
):
    requests, all_records = _requests(tmp_path)
    records = all_records[:2]
    preferred = records[0].candidate_id
    critic_report = await run_blind_pairwise_critic(
        _runtime(
            [
                _critic_output(context, preferred_candidate_id=preferred)
                for context in requests
            ]
        ),
        requests=requests,
        director_identity=_director_identity(),
        calibration_gate=(
            _calibration_gate() if calibration_authorized else None
        ),
    )
    return records, list(critic_report.critiques), critic_report, all_records


def _profile(critique, values: dict[CritiqueDimension, float]):
    return critique.model_copy(
        update={
            "scores": [
                item.model_copy(
                    update={"score": values.get(item.dimension, item.score)}
                )
                for item in critique.scores
            ]
        }
    )


async def test_four_gate_ranking_is_reproducible_and_keeps_runner_up(
    tmp_path: Path,
) -> None:
    records, critiques, critic_report, _ = await _ranking_fixture(tmp_path)
    arguments = {
        "records": records,
        "critiques": critiques,
        "temporal_evidence": [_temporal(item) for item in records],
        "pairwise_reports": [critic_report],
        "evaluated_at": EVALUATED_AT,
    }

    first = rank_creative_candidates(**arguments)
    second = rank_creative_candidates(**arguments)

    assert first == second
    assert first.selection_digest == second.selection_digest
    assert [item.gate for item in first.gate_traces] == list(RankingGate)
    assert first.blind_pairwise_complete is True
    assert first.selected_candidate_id == records[0].candidate_id
    assert first.runner_up_candidate_id == records[1].candidate_id
    assert first.selection_status == "selected-shadow-requires-confirmation"
    assert first.automatic_selection_allowed is False
    assert set(first.ranking_order) == {item.candidate_id for item in records}
    for values in first.objective_values.values():
        assert set(values) == set(CritiqueDimension)


async def test_only_calibrated_position_consistent_critic_can_auto_select(
    tmp_path: Path,
) -> None:
    records, critiques, critic_report, _ = await _ranking_fixture(
        tmp_path,
        calibration_authorized=True,
    )

    report = rank_creative_candidates(
        records=records,
        critiques=critiques,
        temporal_evidence=[_temporal(item) for item in records],
        pairwise_reports=[critic_report],
        evaluated_at=EVALUATED_AT,
    )

    assert report.automatic_selection_allowed is True
    assert report.selection_status == "selected-calibrated-blind-critic"


async def test_missing_or_position_biased_pairwise_comparison_fails_closed(
    tmp_path: Path,
) -> None:
    records, critiques, critic_report, _ = await _ranking_fixture(tmp_path)
    common = {
        "records": records,
        "critiques": critiques,
        "temporal_evidence": [_temporal(item) for item in records],
        "evaluated_at": EVALUATED_AT,
    }

    missing = rank_creative_candidates(pairwise_reports=[], **common)
    biased = rank_creative_candidates(
        pairwise_reports=[
            critic_report.model_copy(update={"position_swap_consistent": False})
        ],
        **common,
    )

    assert missing.selection_status == "awaiting-blind-pairwise"
    assert missing.selected_candidate_id is None
    assert missing.missing_pairwise_pairs
    assert biased.selection_status == "awaiting-blind-pairwise"
    assert biased.automatic_selection_allowed is False


async def test_later_scores_and_human_preference_cannot_resurrect_hard_failure(
    tmp_path: Path,
) -> None:
    records, critiques, critic_report, all_records = await _ranking_fixture(tmp_path)
    third = all_records[2]
    failed_checks = [
        item.model_copy(update={"passed": False})
        for item in third.qc.checks
    ]
    hard_failed = third.model_copy(
        update={
            "status": CandidateAttemptStatus.HARD_FAIL,
            "qc": third.qc.model_copy(
                update={"hard_passed": False, "checks": failed_checks}
            ),
        }
    )
    ranked = rank_creative_candidates(
        records=[*records, hard_failed],
        critiques=critiques,
        temporal_evidence=[_temporal(item) for item in records],
        pairwise_reports=[critic_report],
        evaluated_at=EVALUATED_AT,
    )
    technical = ranked.gate_traces[0]

    assert hard_failed.candidate_id not in technical.passing_candidate_ids
    assert hard_failed.candidate_id not in ranked.retained_candidate_ids
    assert any(
        item.candidate_id == hard_failed.candidate_id
        and all(reason.startswith("hard_gate:") for reason in item.reasons)
        for item in technical.rejections
    )

    preference = HumanPreferenceEvidence(
        project_id="project:test",
        user_scope_id="user:test",
        ordered_candidate_ids=[hard_failed.candidate_id],
        evidence_digest=_sha("human-pref"),
        recorded_at=EVALUATED_AT,
        statement="Prefer the third candidate.",
    )
    with pytest.raises(ValueError, match="cannot resurrect"):
        rank_creative_candidates(
            records=[*records, hard_failed],
            critiques=critiques,
            temporal_evidence=[_temporal(item) for item in records],
            pairwise_reports=[critic_report],
            evaluated_at=EVALUATED_AT,
            human_preference=preference,
        )


async def test_tampered_rendered_asset_fails_the_first_gate(
    tmp_path: Path,
) -> None:
    records, critiques, critic_report, _ = await _ranking_fixture(tmp_path)
    tampered = records[0]
    Path(tampered.samples[0].candidate_path).write_bytes(b"tampered")

    report = rank_creative_candidates(
        records=records,
        critiques=critiques,
        temporal_evidence=[_temporal(item) for item in records],
        pairwise_reports=[critic_report],
        evaluated_at=EVALUATED_AT,
    )

    technical = report.gate_traces[0]
    rejection = next(
        item
        for item in technical.rejections
        if item.candidate_id == tampered.candidate_id
    )
    assert tampered.candidate_id not in technical.passing_candidate_ids
    assert any(
        "digest_mismatch" in reason
        for reason in rejection.reasons
    )


async def test_intent_and_temporal_failures_are_localizable(
    tmp_path: Path,
) -> None:
    records, critiques, _, _ = await _ranking_fixture(tmp_path)
    critiques_by_candidate = {
        critique.candidate_id: critique for critique in critiques
    }
    low_intent = _profile(
        critiques_by_candidate[records[0].candidate_id],
        {CritiqueDimension.CONCEPT_ALIGNMENT: 0.1},
    )
    other_critique = critiques_by_candidate[records[1].candidate_id]

    report = rank_creative_candidates(
        records=records,
        critiques=[low_intent, other_critique],
        temporal_evidence=[
            _temporal(records[0]),
            _temporal(records[1], passed=False),
        ],
        pairwise_reports=[],
        evaluated_at=EVALUATED_AT,
    )
    intent_gate = report.gate_traces[1]
    temporal_gate = report.gate_traces[2]

    assert intent_gate.rejections[0].candidate_id == low_intent.candidate_id
    assert any(
        "concept_alignment" in reason
        for reason in intent_gate.rejections[0].reasons
    )
    assert temporal_gate.rejections[0].candidate_id == other_critique.candidate_id
    assert "within_shot_temporal_failure" in temporal_gate.rejections[0].reasons
    assert report.selection_status == "insufficient-gate-survivors"


async def test_independent_tradeoffs_remain_on_pareto_front(
    tmp_path: Path,
) -> None:
    records, critiques, critic_report, _ = await _ranking_fixture(tmp_path)
    first = _profile(
        critiques[0],
        {
            CritiqueDimension.CONCEPT_ALIGNMENT: 0.9,
            CritiqueDimension.NATURALNESS: 0.4,
            CritiqueDimension.OVERGRADING_RISK: 0.6,
        },
    )
    second = _profile(
        critiques[1],
        {
            CritiqueDimension.CONCEPT_ALIGNMENT: 0.5,
            CritiqueDimension.NATURALNESS: 0.9,
            CritiqueDimension.OVERGRADING_RISK: 0.2,
        },
    )

    report = rank_creative_candidates(
        records=records,
        critiques=[first, second],
        temporal_evidence=[_temporal(item) for item in records],
        pairwise_reports=[critic_report],
        evaluated_at=EVALUATED_AT,
    )

    assert set(report.pareto_candidate_ids) == {
        first.candidate_id,
        second.candidate_id,
    }
    assert (
        report.objective_values[first.candidate_id][
            CritiqueDimension.OVERGRADING_RISK
        ]
        == pytest.approx(0.4)
    )
    assert (
        report.objective_values[second.candidate_id][
            CritiqueDimension.OVERGRADING_RISK
        ]
        == pytest.approx(0.8)
    )


async def test_human_preference_only_reorders_the_retained_set(
    tmp_path: Path,
) -> None:
    records, critiques, critic_report, _ = await _ranking_fixture(tmp_path)
    preferred_by_human = records[1].candidate_id
    preference = HumanPreferenceEvidence(
        project_id="project:test",
        user_scope_id="user:test",
        ordered_candidate_ids=[preferred_by_human, records[0].candidate_id],
        evidence_digest=_sha("human-order"),
        recorded_at=EVALUATED_AT,
        statement="The second direction better serves this project.",
    )

    report = rank_creative_candidates(
        records=records,
        critiques=critiques,
        temporal_evidence=[_temporal(item) for item in records],
        pairwise_reports=[critic_report],
        evaluated_at=EVALUATED_AT,
        human_preference=preference,
    )

    assert report.selected_candidate_id == preferred_by_human
    assert report.selection_status == "selected-human-preference"
    assert report.human_preference_applied is True
    assert report.automatic_selection_allowed is False

    with pytest.raises(ValueError, match="another project"):
        rank_creative_candidates(
            records=records,
            critiques=critiques,
            temporal_evidence=[_temporal(item) for item in records],
            pairwise_reports=[critic_report],
            evaluated_at=EVALUATED_AT,
            human_preference=preference.model_copy(
                update={"project_id": "project:other"}
            ),
        )


async def test_bound_exception_relaxes_only_creative_default_gate(
    tmp_path: Path,
) -> None:
    records, critiques, critic_report, _ = await _ranking_fixture(tmp_path)
    record = records[0]
    adjusted = _profile(
        next(item for item in critiques if item.candidate_id == record.candidate_id),
        {
            CritiqueDimension.NATURALNESS: 0.2,
            CritiqueDimension.OVERGRADING_RISK: 0.78,
        },
    )
    other = next(item for item in critiques if item.candidate_id != record.candidate_id)
    contract = CompiledCandidate.model_validate_json(
        Path(record.contract_path).read_text(encoding="utf-8"),
        strict=True,
    )
    exception = IntentionalException(
        exception_id="exception:selective-saturation",
        kind=IntentionalExceptionKind.SELECTIVE_SATURATION_PUSH,
        reason="A bounded local saturation departure serves the declared hierarchy.",
        evidence_ids=["frame:001"],
        scope=StrategyScope(
            project_id="project:test",
            scene_id=record.scene_id,
            mask_target="sky",
        ),
        metric=ExceptionMetric.OVERSATURATION_RATIO,
        maximum_metric_value=0.08,
        protected_attributes=[ProtectedAttribute.NATURAL_SATURATION],
        approval_source=ExceptionApprovalSource.AUTOMATIC,
        source_graph_digest=contract.source_graph_digest,
        candidate_digest=record.compiled_graph_digest,
        declared_at=datetime(2026, 7, 30, 1, tzinfo=UTC),
        invalidation_conditions=[
            "Invalidate if graph, candidate, scope, or evidence changes."
        ],
    )
    common = {
        "records": records,
        "critiques": [adjusted, other],
        "temporal_evidence": [_temporal(item) for item in records],
        "pairwise_reports": [critic_report],
        "evaluated_at": EVALUATED_AT,
    }

    rejected = rank_creative_candidates(**common)
    accepted = rank_creative_candidates(
        **common,
        intentional_exceptions={record.candidate_id: [exception]},
    )

    assert record.candidate_id not in rejected.gate_traces[1].passing_candidate_ids
    assert record.candidate_id in accepted.gate_traces[1].passing_candidate_ids
    assert accepted.applied_exception_ids[record.candidate_id] == [
        exception.exception_id
    ]


async def test_ranking_order_adapts_to_search_ranker_contract(
    tmp_path: Path,
) -> None:
    records, critiques, critic_report, _ = await _ranking_fixture(tmp_path)
    report = rank_creative_candidates(
        records=records,
        critiques=critiques,
        temporal_evidence=[_temporal(item) for item in records],
        pairwise_reports=[critic_report],
        evaluated_at=EVALUATED_AT,
    )

    order = ranking_order_for_search(report, records)

    assert order == report.ranking_order
    assert order[0] == report.selected_candidate_id
