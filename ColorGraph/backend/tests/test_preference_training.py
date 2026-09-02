from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pytest

from colorgraph.evaluation.preference import (
    BRADLEY_TERRY_VERSION,
    PairwiseChoice,
    PairwisePreferenceRecord,
    PreferenceSplit,
    PreferenceTrainingConfig,
    preference_probability,
    preference_records_from_review,
    train_bradley_terry_preference,
)
from colorgraph.evaluation.review import (
    ExpertReviewer,
    Preference,
    ReviewPair,
    ReviewResponse,
    ViewingEnvironment,
    build_blinded_review_session,
)
from colorgraph.evaluation.runner import _evaluate_sections


def _synthetic_records(
    *,
    seed: int = 20260730,
) -> list[PairwisePreferenceRecord]:
    rng = np.random.default_rng(seed)
    records: list[PairwisePreferenceRecord] = []
    reviewers = [f"reviewer-{index}" for index in range(5)]
    for source_index in range(60):
        split = (
            PreferenceSplit.TRAIN
            if source_index < 30
            else (
                PreferenceSplit.CALIBRATION
                if source_index < 40
                else PreferenceSplit.TEST
            )
        )
        for pair_index in range(8):
            features_a = {
                "rule_score": float(rng.normal()),
                "clip_score": float(rng.normal()),
                "siglip2_score": float(rng.normal()),
                "scene_support": float(rng.normal()),
            }
            features_b = {
                "rule_score": float(rng.normal()),
                "clip_score": float(rng.normal()),
                "siglip2_score": float(rng.normal()),
                "scene_support": float(rng.normal()),
            }
            margin = (
                features_a["rule_score"]
                - features_b["rule_score"]
                + features_a["clip_score"]
                - features_b["clip_score"]
                + 0.70
                * (
                    features_a["scene_support"]
                    - features_b["scene_support"]
                )
                + 0.25
                * (
                    features_a["siglip2_score"]
                    - features_b["siglip2_score"]
                )
            )
            for reviewer_index, reviewer_id in enumerate(reviewers):
                observed = (
                    margin
                    + rng.normal(0, 0.35)
                    + (reviewer_index - 2) * 0.02
                )
                choice = (
                    PairwiseChoice.TIE
                    if abs(observed) < 0.12
                    else (
                        PairwiseChoice.A
                        if observed > 0
                        else PairwiseChoice.B
                    )
                )
                records.append(
                    PairwisePreferenceRecord(
                        id=f"{source_index}:{pair_index}:{reviewer_id}",
                        pair_id=f"pair-{source_index}-{pair_index}",
                        source_id=f"source-{source_index}",
                        candidate_a_id=f"a-{source_index}-{pair_index}",
                        candidate_b_id=f"b-{source_index}-{pair_index}",
                        reviewer_id=reviewer_id,
                        choice=choice,
                        confidence=min(5, max(1, int(abs(observed) * 2) + 1)),
                        split=split,
                        features_a=features_a,
                        features_b=features_b,
                    )
                )
    return records


def test_domain_bradley_terry_is_calibrated_and_beats_frozen_baselines() -> None:
    records = _synthetic_records()
    config = PreferenceTrainingConfig(
        bootstrap_samples=100,
        minimum_pairs_per_split=20,
        bootstrap_seed=17,
    )

    first = train_bradley_terry_preference(records, config=config)
    second = train_bradley_terry_preference(records, config=config)

    assert first.artifact.schema_version == BRADLEY_TERRY_VERSION
    assert first.artifact.training_digest == second.artifact.training_digest
    assert first.artifact.coefficients == second.artifact.coefficients
    assert first.artifact.temperature == pytest.approx(second.artifact.temperature)
    assert first.artifact.converged is True
    assert first.test_metrics.pairwise_accuracy > 0.94
    assert first.test_metrics.bradley_terry_log_loss < 0.06
    assert first.test_metrics.expected_calibration_error < 0.03
    assert first.reviewer_agreement.fleiss_kappa > 0.70
    assert first.all_required_baselines_significantly_better is True
    assert {
        comparison.baseline for comparison in first.baseline_comparisons
    } == {"rule_wins", "clip", "siglip2"}
    assert all(
        comparison.accuracy_difference_ci95_low > 0
        and comparison.log_loss_difference_ci95_high < 0
        for comparison in first.baseline_comparisons
    )

    sample = records[0]
    probability_a = preference_probability(
        first.artifact,
        sample.features_a,
        sample.features_b,
    )
    probability_b = preference_probability(
        first.artifact,
        sample.features_b,
        sample.features_a,
    )
    assert probability_a + probability_b == pytest.approx(1, abs=1e-12)


def test_preference_training_rejects_source_split_leakage() -> None:
    records = _synthetic_records()[:5]
    leaked = records[0].model_copy(
        update={
            "id": "leaked",
            "pair_id": "leaked-pair",
            "split": PreferenceSplit.TEST,
        }
    )

    with pytest.raises(ValueError, match="leaks across preference splits"):
        train_bradley_terry_preference(
            [*records, leaked],
            config=PreferenceTrainingConfig(
                bootstrap_samples=20,
                minimum_pairs_per_split=2,
            ),
        )


def test_tie_only_test_split_fails_instead_of_inventing_accuracy() -> None:
    records = _synthetic_records()
    tied = [
        record.model_copy(
            update={"choice": PairwiseChoice.TIE},
        )
        if record.split == PreferenceSplit.TEST
        else record
        for record in records
    ]

    with pytest.raises(ValueError, match="no decisive expert consensus"):
        train_bradley_terry_preference(
            tied,
            config=PreferenceTrainingConfig(
                bootstrap_samples=20,
                minimum_pairs_per_split=20,
            ),
        )


def test_blinded_expert_responses_unblind_to_canonical_training_records() -> None:
    reviewers = [
        ExpertReviewer(
            id=f"expert-{index}",
            years_experience=5 + index,
            roles=["colorist"],
            color_vision_screened=True,
            display_calibration_confirmed=True,
        )
        for index in range(3)
    ]
    pair = ReviewPair(
        id="pair-1",
        source_id="source-1",
        candidate_a_id="candidate-a",
        candidate_b_id="candidate-b",
    )
    session, key = build_blinded_review_session(
        "session-1",
        [pair],
        reviewers,
        seed=91,
        viewing_environment=ViewingEnvironment(
            display_model="Reference display",
            calibration_profile_sha256="a" * 64,
            white_point="D65",
            peak_luminance_nits=100,
            black_luminance_nits=0.01,
            color_space="Rec.709",
            eotf="BT.1886",
            ambient_lux=5,
            viewing_distance_meters=1.2,
            calibration_date=datetime(2026, 7, 1, tzinfo=UTC),
        ),
    )
    responses: list[ReviewResponse] = []
    for reviewer_session in session.sessions:
        assignment = reviewer_session.assignments[0]
        mapping = key.mappings[f"{reviewer_session.reviewer_id}:pair-1"]
        preference = (
            Preference.A
            if mapping[assignment.blind_a] == "candidate-a"
            else Preference.B
        )
        responses.append(
            ReviewResponse(
                session_id=session.session_id,
                reviewer_id=reviewer_session.reviewer_id,
                pair_id=pair.id,
                preference=preference,
                confidence=5,
            )
        )

    records = preference_records_from_review(
        session,
        key,
        responses,
        candidate_features={
            "candidate-a": {
                "rule_score": 0.8,
                "clip_score": 0.6,
                "siglip2_score": 0.7,
            },
            "candidate-b": {
                "rule_score": 0.2,
                "clip_score": 0.4,
                "siglip2_score": 0.3,
            },
        },
        split_by_source={"source-1": PreferenceSplit.TRAIN},
    )

    assert len(records) == 3
    assert {record.choice for record in records} == {PairwiseChoice.A}
    assert all(record.candidate_a_id == "candidate-a" for record in records)
    assert all(record.split == PreferenceSplit.TRAIN for record in records)


def test_evaluation_runner_reports_domain_bradley_terry_metrics() -> None:
    records = _synthetic_records()

    metrics = _evaluate_sections(
        {
            "ranking": {
                "bradley_terry_records": [
                    record.model_dump(mode="json") for record in records
                ],
                "bradley_terry_config": {
                    "bootstrap_samples": 20,
                    "minimum_pairs_per_split": 20,
                    "bootstrap_seed": 17,
                },
            }
        }
    )

    ranking = metrics["ranking"]
    assert ranking["domain_bt_pairwise_accuracy"] > 0.94
    assert ranking["domain_bt_log_loss"] < 0.06
    assert ranking["domain_bt_reviewer_fleiss_kappa"] > 0.70
    assert ranking["domain_bt_all_baselines_significantly_better"] == 1
    assert ranking["domain_bt_vs_rule_wins_significantly_better"] == 1
    assert ranking["domain_bt_vs_clip_significantly_better"] == 1
    assert ranking["domain_bt_vs_siglip2_significantly_better"] == 1
