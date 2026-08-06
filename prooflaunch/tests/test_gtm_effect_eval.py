from __future__ import annotations

import json
import unittest
from dataclasses import replace
from pathlib import Path

from prooflaunch_remix.gtm_effect_eval import (
    BlindPair,
    Capability,
    CapabilityEvidence,
    CapabilityEvidenceLevel,
    CoreFailureClass,
    Deliverable,
    DeliverableRole,
    EffectContractError,
    EffectPromotionContract,
    JudgeCalibration,
    JudgeKind,
    MechanicalGate,
    MechanicalGateRecord,
    ObservedOutcome,
    OutcomeObservationSource,
    PreferenceChoice,
    PreferenceVote,
    RelationshipClaim,
    admit_observed_outcomes,
    build_blind_pair,
)


ROOT = Path(__file__).resolve().parents[1]


def deliverable(
    index: int,
    role: DeliverableRole,
    capability: Capability = Capability.STRATEGY,
    scenario_id: str | None = None,
) -> Deliverable:
    scenario = scenario_id or f"{capability.value}-critical"
    marker = f"{capability.value}-{role.value}-{index}"
    import hashlib

    return Deliverable(
        deliverable_id=marker,
        scenario_id=scenario,
        capability=capability,
        role=role,
        content_sha256=hashlib.sha256(marker.encode("utf-8")).hexdigest(),
        blind_artifact_locator=f"blind://{marker}",
        rights_locator=f"evidence://rights/{marker}",
        evidence_locators=(f"evidence://claims/{marker}",),
        claim_ids=(f"claim-{index}",),
        brand_profile_id="brand-v1",
        channel="controlled-channel",
        accessibility_locator=f"evidence://a11y/{marker}",
        experiment_trace_id=f"experiment-{marker}",
        clean_room_attested=True,
        method_reference_locators=("method://official-product-docs",),
    )


def mechanics(item: Deliverable, **overrides: bool) -> MechanicalGateRecord:
    values = {
        "rights_clear": True,
        "evidence_bound": True,
        "claims_grounded": True,
        "brand_conformant": True,
        "channel_valid": True,
        "accessibility_passed": True,
        "experiment_trace_complete": True,
    }
    values.update(overrides)
    return MechanicalGateRecord(
        deliverable_id=item.deliverable_id,
        gate_evidence_locators={
            gate: f"evidence://gate/{item.deliverable_id}/{gate.value}"
            for gate in MechanicalGate
        },
        **values,
    )


def human_capability(capability: Capability) -> CapabilityEvidence:
    return CapabilityEvidence(
        capability=capability,
        level=CapabilityEvidenceLevel.HUMAN_OBSERVED,
        evidence_locator=f"evidence://human/{capability.value}",
        observed_case_count=30,
        limitations=("Controlled sample; external validity remains unproven.",),
    )


def failure_counts(value: int = 50) -> dict[CoreFailureClass, int]:
    return {failure_class: value for failure_class in CoreFailureClass}


def one_capability_suite(
    *,
    capability: Capability = Capability.STRATEGY,
    pair_count: int = 30,
    candidate_wins: int = 24,
) -> dict[str, object]:
    outputs: list[Deliverable] = []
    records: list[MechanicalGateRecord] = []
    pairs: list[BlindPair] = []
    votes: list[PreferenceVote] = []
    for index in range(pair_count):
        candidate = deliverable(index, DeliverableRole.CANDIDATE, capability)
        baseline = deliverable(index, DeliverableRole.BASELINE, capability)
        pair = build_blind_pair(
            pair_id=f"pair-{capability.value}-{index}",
            candidate=candidate,
            baseline=baseline,
            randomization_key="sealed-randomization-key-v1",
        )
        outputs.extend((candidate, baseline))
        records.extend((mechanics(candidate), mechanics(baseline)))
        winner = (
            pair.candidate_side
            if index < candidate_wins
            else (
                PreferenceChoice.RIGHT
                if pair.candidate_side == PreferenceChoice.LEFT
                else PreferenceChoice.LEFT
            )
        )
        votes.extend(
            PreferenceVote(
                pair_id=pair.pair_id,
                rater_id=f"human-{rater}",
                choice=winner,
                judge_kind=JudgeKind.HUMAN,
                independent=True,
                conflict_disclosed=True,
            )
            for rater in range(3)
        )
        pairs.append(pair)
    return {
        "contract": EffectPromotionContract(required_capabilities=(capability,)),
        "deliverables": outputs,
        "mechanical_records": records,
        "pairs": pairs,
        "votes": votes,
        "failure_case_counts": failure_counts(),
        "capability_evidence": [human_capability(capability)],
        "evaluation_limitations": [
            "Blind comparative preference does not establish universal or causal lift."
        ],
    }


def evaluate(suite: dict[str, object]):
    contract = suite["contract"]
    assert isinstance(contract, EffectPromotionContract)
    return contract.evaluate(
        deliverables=suite["deliverables"],
        mechanical_records=suite["mechanical_records"],
        pairs=suite["pairs"],
        votes=suite["votes"],
        failure_case_counts=suite["failure_case_counts"],
        capability_evidence=suite["capability_evidence"],
        evaluation_limitations=suite["evaluation_limitations"],
        judge_calibration=suite.get("judge_calibration"),
    )


def outcome(**overrides: object) -> ObservedOutcome:
    values: dict[str, object] = {
        "outcome_id": "outcome-1",
        "capability": Capability.ANALYTICS,
        "experiment_id": "exp-2026-08-01-a",
        "metric_name": "qualified_conversion_rate",
        "observed_value": 0.12,
        "sample_denominator": 500,
        "attribution_window_start": "2026-08-01T00:00:00Z",
        "attribution_window_end": "2026-08-08T00:00:00Z",
        "baseline_id": "incumbent-v3",
        "observation_source": OutcomeObservationSource.FIRST_PARTY_EXPERIMENT,
    }
    values.update(overrides)
    return ObservedOutcome(**values)  # type: ignore[arg-type]


class DeliverableAndMechanicalGateTests(unittest.TestCase):
    def test_capabilities_cover_the_eight_effect_lanes(self) -> None:
        self.assertEqual(
            {item.value for item in Capability},
            {
                "strategy",
                "copy",
                "image",
                "video",
                "audio",
                "schedule",
                "seo_geo",
                "analytics",
            },
        )

    def test_clean_room_deliverable_is_structurally_valid(self) -> None:
        self.assertEqual(deliverable(1, DeliverableRole.CANDIDATE).structural_failures(), ())

    def test_invalid_content_digest_is_rejected(self) -> None:
        item = replace(deliverable(1, DeliverableRole.CANDIDATE), content_sha256="bad")
        self.assertTrue(any("SHA-256" in failure for failure in item.structural_failures()))

    def test_copied_reference_artifact_is_a_critical_rights_failure(self) -> None:
        item = replace(
            deliverable(1, DeliverableRole.CANDIDATE),
            copied_reference_asset_ids=("agency-work-1",),
        )
        findings = mechanics(item).critical_findings(item)
        self.assertTrue(any(finding.gate == MechanicalGate.RIGHTS for finding in findings))

    def _assert_false_gate(self, field: str, gate: MechanicalGate) -> None:
        item = deliverable(1, DeliverableRole.CANDIDATE)
        findings = mechanics(item, **{field: False}).critical_findings(item)
        self.assertTrue(any(finding.gate == gate for finding in findings))

    def test_rights_gate_is_zero_tolerance(self) -> None:
        self._assert_false_gate("rights_clear", MechanicalGate.RIGHTS)

    def test_evidence_gate_is_zero_tolerance(self) -> None:
        self._assert_false_gate("evidence_bound", MechanicalGate.EVIDENCE)

    def test_claim_gate_is_zero_tolerance(self) -> None:
        self._assert_false_gate("claims_grounded", MechanicalGate.CLAIM)

    def test_brand_gate_is_zero_tolerance(self) -> None:
        self._assert_false_gate("brand_conformant", MechanicalGate.BRAND)

    def test_channel_gate_is_zero_tolerance(self) -> None:
        self._assert_false_gate("channel_valid", MechanicalGate.CHANNEL)

    def test_accessibility_gate_is_zero_tolerance(self) -> None:
        self._assert_false_gate("accessibility_passed", MechanicalGate.ACCESSIBILITY)

    def test_experiment_trace_gate_is_zero_tolerance(self) -> None:
        self._assert_false_gate("experiment_trace_complete", MechanicalGate.EXPERIMENT_TRACE)

    def test_missing_gate_locator_is_critical(self) -> None:
        item = deliverable(1, DeliverableRole.CANDIDATE)
        record = replace(mechanics(item), gate_evidence_locators={})
        self.assertEqual(len(record.critical_findings(item)), len(MechanicalGate))


class BlindPairTests(unittest.TestCase):
    def test_public_packet_hides_roles_sources_and_private_ids(self) -> None:
        candidate = deliverable(1, DeliverableRole.CANDIDATE)
        baseline = deliverable(1, DeliverableRole.BASELINE)
        pair = build_blind_pair(
            pair_id="pair-1",
            candidate=candidate,
            baseline=baseline,
            randomization_key="secret",
        )
        packet = json.dumps(pair.public_packet(), sort_keys=True)
        self.assertNotIn(candidate.deliverable_id, packet)
        self.assertNotIn(baseline.deliverable_id, packet)
        self.assertNotIn("candidate", packet)
        self.assertNotIn("baseline", packet)

    def test_randomization_assigns_both_left_and_right(self) -> None:
        sides = set()
        for index in range(64):
            sides.add(
                build_blind_pair(
                    pair_id=f"pair-{index}",
                    candidate=deliverable(index, DeliverableRole.CANDIDATE),
                    baseline=deliverable(index, DeliverableRole.BASELINE),
                    randomization_key="sealed-key",
                ).candidate_side
            )
        self.assertEqual(sides, {PreferenceChoice.LEFT, PreferenceChoice.RIGHT})

    def test_randomization_is_reproducible_for_audit(self) -> None:
        candidate = deliverable(1, DeliverableRole.CANDIDATE)
        baseline = deliverable(1, DeliverableRole.BASELINE)
        first = build_blind_pair(
            pair_id="pair-1",
            candidate=candidate,
            baseline=baseline,
            randomization_key="sealed-key",
        )
        second = build_blind_pair(
            pair_id="pair-1",
            candidate=candidate,
            baseline=baseline,
            randomization_key="sealed-key",
        )
        self.assertEqual(first, second)

    def test_exact_duplicate_is_not_a_valid_pair(self) -> None:
        candidate = deliverable(1, DeliverableRole.CANDIDATE)
        baseline = replace(
            deliverable(1, DeliverableRole.BASELINE),
            content_sha256=candidate.content_sha256,
        )
        with self.assertRaises(EffectContractError):
            build_blind_pair(
                pair_id="pair-1",
                candidate=candidate,
                baseline=baseline,
                randomization_key="sealed-key",
            )

    def test_cross_scenario_pair_is_rejected(self) -> None:
        with self.assertRaises(EffectContractError):
            build_blind_pair(
                pair_id="pair-1",
                candidate=deliverable(1, DeliverableRole.CANDIDATE, scenario_id="a"),
                baseline=deliverable(1, DeliverableRole.BASELINE, scenario_id="b"),
                randomization_key="sealed-key",
            )


class EffectPromotionTests(unittest.TestCase):
    def test_passing_blind_effect_suite_promotes(self) -> None:
        report = evaluate(one_capability_suite())
        self.assertTrue(report.promoted, report.failures)
        self.assertTrue(report.four_a_effect_claimable)
        self.assertEqual(report.critical_failure_count, 0)

    def test_fewer_than_thirty_pairs_fails(self) -> None:
        report = evaluate(one_capability_suite(pair_count=29, candidate_wins=24))
        self.assertFalse(report.promoted)
        self.assertTrue(any("fewer than 30 pairs" in item for item in report.failures))

    def test_sixty_percent_point_estimate_still_fails_wilson_gate(self) -> None:
        report = evaluate(one_capability_suite(candidate_wins=18))
        result = report.scenario_results[0]
        self.assertEqual(result.win_rate, 0.60)
        self.assertLessEqual(result.wilson_lower_95 or 1, 0.50)
        self.assertFalse(report.promoted)

    def test_point_estimate_above_sixty_can_still_fail_wilson_gate(self) -> None:
        report = evaluate(one_capability_suite(candidate_wins=20))
        result = report.scenario_results[0]
        self.assertGreater(result.win_rate or 0, 0.60)
        self.assertLessEqual(result.wilson_lower_95 or 1, 0.50)
        self.assertFalse(report.promoted)

    def test_candidate_win_rate_below_sixty_fails(self) -> None:
        report = evaluate(one_capability_suite(candidate_wins=17))
        self.assertFalse(report.promoted)
        self.assertTrue(any("win rate below" in item for item in report.failures))

    def test_one_critical_mechanical_failure_blocks_promotion(self) -> None:
        suite = one_capability_suite()
        records = list(suite["mechanical_records"])
        records[0] = replace(records[0], rights_clear=False)
        suite["mechanical_records"] = records
        report = evaluate(suite)
        self.assertFalse(report.promoted)
        self.assertEqual(report.critical_failure_count, 1)

    def test_missing_mechanical_record_is_counted_as_critical(self) -> None:
        suite = one_capability_suite()
        suite["mechanical_records"] = suite["mechanical_records"][1:]
        report = evaluate(suite)
        self.assertFalse(report.promoted)
        self.assertEqual(report.critical_failure_count, 1)

    def test_each_failure_class_requires_fifty_cases(self) -> None:
        suite = one_capability_suite()
        counts = failure_counts()
        counts[CoreFailureClass.BRAND_DRIFT] = 49
        suite["failure_case_counts"] = counts
        report = evaluate(suite)
        self.assertFalse(report.promoted)
        self.assertTrue(any("brand_drift" in item for item in report.failures))

    def test_missing_failure_class_fails_closed(self) -> None:
        suite = one_capability_suite()
        counts = failure_counts()
        counts.pop(CoreFailureClass.ATTRIBUTION_CAUSALITY)
        suite["failure_case_counts"] = counts
        self.assertFalse(evaluate(suite).promoted)

    def test_mechanical_capability_cannot_claim_four_a_effect(self) -> None:
        suite = one_capability_suite()
        evidence = human_capability(Capability.STRATEGY)
        suite["capability_evidence"] = [
            replace(evidence, level=CapabilityEvidenceLevel.MECHANICAL)
        ]
        report = evaluate(suite)
        self.assertFalse(report.four_a_effect_claimable)
        self.assertFalse(report.promoted)

    def test_model_observed_capability_cannot_claim_four_a_effect(self) -> None:
        suite = one_capability_suite()
        evidence = human_capability(Capability.STRATEGY)
        suite["capability_evidence"] = [
            replace(evidence, level=CapabilityEvidenceLevel.MODEL_OBSERVED)
        ]
        self.assertFalse(evaluate(suite).promoted)

    def test_production_observed_capability_can_claim_effect(self) -> None:
        suite = one_capability_suite()
        evidence = human_capability(Capability.STRATEGY)
        suite["capability_evidence"] = [
            replace(evidence, level=CapabilityEvidenceLevel.PRODUCTION_OBSERVED)
        ]
        self.assertTrue(evaluate(suite).promoted)

    def test_observed_capability_requires_thirty_cases(self) -> None:
        suite = one_capability_suite()
        suite["capability_evidence"] = [
            replace(human_capability(Capability.STRATEGY), observed_case_count=29)
        ]
        self.assertFalse(evaluate(suite).promoted)

    def test_missing_capability_limitation_blocks_promotion(self) -> None:
        suite = one_capability_suite()
        suite["capability_evidence"] = [
            replace(human_capability(Capability.STRATEGY), limitations=())
        ]
        self.assertFalse(evaluate(suite).promoted)

    def test_missing_evaluation_limitations_blocks_promotion(self) -> None:
        suite = one_capability_suite()
        suite["evaluation_limitations"] = []
        self.assertFalse(evaluate(suite).promoted)

    def test_duplicate_vote_is_rejected(self) -> None:
        suite = one_capability_suite()
        votes = list(suite["votes"])
        votes.append(votes[0])
        suite["votes"] = votes
        self.assertTrue(any("duplicate vote" in item for item in evaluate(suite).failures))

    def test_non_independent_vote_is_rejected(self) -> None:
        suite = one_capability_suite()
        votes = list(suite["votes"])
        votes[0] = replace(votes[0], independent=False)
        suite["votes"] = votes
        self.assertFalse(evaluate(suite).promoted)

    def test_undisclosed_rater_conflict_is_rejected(self) -> None:
        suite = one_capability_suite()
        votes = list(suite["votes"])
        votes[0] = replace(votes[0], conflict_disclosed=False)
        suite["votes"] = votes
        self.assertFalse(evaluate(suite).promoted)

    def test_tied_pair_is_unresolved_and_blocks(self) -> None:
        suite = one_capability_suite()
        pairs = suite["pairs"]
        assert isinstance(pairs, list)
        first = pairs[0]
        assert isinstance(first, BlindPair)
        votes = [vote for vote in suite["votes"] if vote.pair_id != first.pair_id]
        opposite = (
            PreferenceChoice.RIGHT
            if first.candidate_side == PreferenceChoice.LEFT
            else PreferenceChoice.LEFT
        )
        votes.extend(
            PreferenceVote(
                first.pair_id,
                f"tie-{index}",
                first.candidate_side if index < 2 else opposite,
                JudgeKind.HUMAN,
                True,
                True,
            )
            for index in range(4)
        )
        suite["votes"] = votes
        self.assertTrue(any("tied preference" in item for item in evaluate(suite).failures))

    def test_low_inter_rater_agreement_blocks(self) -> None:
        suite = one_capability_suite()
        pairs = suite["pairs"]
        assert isinstance(pairs, list)
        first = pairs[0]
        assert isinstance(first, BlindPair)
        opposite = (
            PreferenceChoice.RIGHT
            if first.candidate_side == PreferenceChoice.LEFT
            else PreferenceChoice.LEFT
        )
        votes = list(suite["votes"])
        votes.extend(
            PreferenceVote(
                first.pair_id,
                f"dissenter-{index}",
                opposite,
                JudgeKind.HUMAN,
                True,
                True,
            )
            for index in range(2)
        )
        suite["votes"] = votes
        self.assertTrue(any("agreement too low" in item for item in evaluate(suite).failures))

    def test_abstention_rate_over_twenty_percent_blocks(self) -> None:
        suite = one_capability_suite()
        votes = list(suite["votes"])
        for pair in suite["pairs"]:
            votes.append(
                PreferenceVote(
                    pair.pair_id,
                    "abstainer",
                    PreferenceChoice.ABSTAIN,
                    JudgeKind.HUMAN,
                    True,
                    True,
                )
            )
        suite["votes"] = votes
        self.assertTrue(any("abstention rate" in item for item in evaluate(suite).failures))

    def test_uncalibrated_model_vote_cannot_enter_promotion_evidence(self) -> None:
        suite = one_capability_suite()
        pair = suite["pairs"][0]
        votes = list(suite["votes"])
        votes.append(
            PreferenceVote(
                pair.pair_id,
                "judge-v1",
                pair.candidate_side,
                JudgeKind.MODEL,
                True,
                True,
            )
        )
        suite["votes"] = votes
        self.assertTrue(any("calibration" in item for item in evaluate(suite).failures))

    def test_exactly_eighty_percent_tpr_or_tnr_is_not_enough(self) -> None:
        calibration = JudgeCalibration(100, 40, 10, 40, 10, "evidence://judge")
        self.assertFalse(calibration.promotion_eligible)
        self.assertEqual(calibration.true_positive_rate, 0.8)
        self.assertEqual(calibration.true_negative_rate, 0.8)

    def test_malformed_judge_counts_fail_closed_without_crashing(self) -> None:
        calibration = JudgeCalibration(100, "45", 5, 45, 5, "evidence://judge")  # type: ignore[arg-type]
        self.assertFalse(calibration.promotion_eligible)
        self.assertIsNone(calibration.true_positive_rate)

    def test_calibrated_model_vote_is_diagnostic_only_and_never_enters_preference(self) -> None:
        suite = one_capability_suite()
        pair = suite["pairs"][0]
        baseline_report = evaluate(suite)
        baseline_result = next(
            row
            for row in baseline_report.scenario_results
            if row.capability == pair.capability
            and row.scenario_id == pair.scenario_id
        )
        votes = list(suite["votes"])
        votes.append(
            PreferenceVote(
                pair.pair_id,
                "judge-v1",
                (
                    PreferenceChoice.RIGHT
                    if pair.candidate_side == PreferenceChoice.LEFT
                    else PreferenceChoice.LEFT
                ),
                JudgeKind.MODEL,
                True,
                True,
            )
        )
        suite["votes"] = votes
        suite["judge_calibration"] = JudgeCalibration(
            100, 45, 5, 45, 5, "evidence://judge-calibration"
        )
        report = evaluate(suite)
        self.assertTrue(report.promoted, report.failures)
        self.assertTrue(report.judge_calibrated)
        result = next(
            row
            for row in report.scenario_results
            if row.capability == pair.capability
            and row.scenario_id == pair.scenario_id
        )
        self.assertEqual(result.candidate_wins, baseline_result.candidate_wins)
        self.assertEqual(result.resolved_pair_count, baseline_result.resolved_pair_count)
        self.assertEqual(result.win_rate, baseline_result.win_rate)
        self.assertEqual(result.abstention_rate, baseline_result.abstention_rate)

    def test_default_contract_requires_all_eight_capabilities(self) -> None:
        suite = one_capability_suite()
        suite["contract"] = EffectPromotionContract()
        report = evaluate(suite)
        self.assertFalse(report.promoted)
        self.assertTrue(any("copy: capability evidence missing" in x for x in report.failures))

    def test_repeated_content_pair_cannot_inflate_thirty_pair_sample(self) -> None:
        suite = one_capability_suite()
        pairs = list(suite["pairs"])
        first = pairs[0]
        second = pairs[1]
        pairs[1] = replace(
            second,
            candidate_id=first.candidate_id,
            baseline_id=first.baseline_id,
        )
        suite["pairs"] = pairs
        report = evaluate(suite)
        self.assertFalse(report.promoted)
        self.assertTrue(any("inflate sample size" in item for item in report.failures))

    def test_all_eight_capabilities_can_pass_one_uniform_contract(self) -> None:
        combined: dict[str, list] = {
            "deliverables": [],
            "mechanical_records": [],
            "pairs": [],
            "votes": [],
            "capability_evidence": [],
        }
        for capability in Capability:
            suite = one_capability_suite(capability=capability)
            for key in combined:
                combined[key].extend(suite[key])
        report = EffectPromotionContract().evaluate(
            deliverables=combined["deliverables"],
            mechanical_records=combined["mechanical_records"],
            pairs=combined["pairs"],
            votes=combined["votes"],
            failure_case_counts=failure_counts(),
            capability_evidence=combined["capability_evidence"],
            evaluation_limitations=("Controlled blind benchmark limitations apply.",),
        )
        self.assertTrue(report.promoted, report.failures)
        self.assertEqual(len(report.scenario_results), 8)


class ObservedOutcomeTests(unittest.TestCase):
    def test_complete_observed_outcome_is_admitted(self) -> None:
        item = outcome()
        self.assertTrue(item.admissible_for_learning, item.learning_failures())
        self.assertEqual(admit_observed_outcomes([item]).admitted_outcome_ids, ("outcome-1",))

    def test_experiment_id_is_required(self) -> None:
        self.assertFalse(outcome(experiment_id="").admissible_for_learning)

    def test_positive_sample_denominator_is_required(self) -> None:
        self.assertFalse(outcome(sample_denominator=0).admissible_for_learning)

    def test_baseline_is_required(self) -> None:
        self.assertFalse(outcome(baseline_id="").admissible_for_learning)

    def test_attribution_window_must_be_increasing(self) -> None:
        item = outcome(attribution_window_end="2026-07-31T00:00:00Z")
        self.assertFalse(item.admissible_for_learning)

    def test_attribution_window_must_be_timezone_aware(self) -> None:
        item = outcome(attribution_window_start="2026-08-01T00:00:00")
        self.assertFalse(item.admissible_for_learning)

    def test_non_finite_observation_is_rejected(self) -> None:
        self.assertFalse(outcome(observed_value=float("nan")).admissible_for_learning)

    def test_correlation_may_not_be_written_as_causation(self) -> None:
        item = outcome(causal_language_used=True)
        self.assertTrue(any("causal language" in x for x in item.learning_failures()))

    def test_correlation_may_not_smuggle_a_causal_method(self) -> None:
        item = outcome(causal_method="randomized_controlled_trial")
        self.assertFalse(item.admissible_for_learning)

    def test_causal_claim_requires_accepted_identification(self) -> None:
        item = outcome(
            relationship_claim=RelationshipClaim.CAUSAL,
            causal_method="before_after",
            causal_assumptions_locator="evidence://assumptions",
        )
        self.assertFalse(item.admissible_for_learning)

    def test_identified_causal_outcome_can_be_admitted(self) -> None:
        item = outcome(
            relationship_claim=RelationshipClaim.CAUSAL,
            causal_language_used=True,
            causal_method="randomized_controlled_trial",
            causal_assumptions_locator="evidence://randomization-and-balance",
        )
        self.assertTrue(item.admissible_for_learning, item.learning_failures())

    def test_mixed_learning_batch_admits_only_complete_outcomes(self) -> None:
        good = outcome()
        bad = outcome(outcome_id="outcome-2", baseline_id="")
        report = admit_observed_outcomes([good, bad])
        self.assertEqual(report.admitted_outcome_ids, ("outcome-1",))
        self.assertIn("outcome-2", report.rejected)

    def test_duplicate_outcome_id_is_rejected(self) -> None:
        report = admit_observed_outcomes([outcome(), outcome()])
        self.assertEqual(report.admitted_outcome_ids, ())
        self.assertIn("duplicate outcome_id", report.rejected["outcome-1"])


class FrozenConfigTests(unittest.TestCase):
    def test_config_freezes_effect_not_feature_thresholds(self) -> None:
        payload = json.loads(
            (ROOT / "config" / "gtm_effect_gate_v1.json").read_text(encoding="utf-8")
        )
        self.assertEqual(payload["minimum_pairs_per_key_scenario"], 30)
        self.assertEqual(payload["minimum_candidate_win_rate"], 0.60)
        self.assertEqual(payload["wilson_lower_95_operator"], "strictly_greater_than")
        self.assertEqual(payload["minimum_failure_cases_per_class"], 50)
        self.assertEqual(payload["critical_failure_tolerance"], 0)
        self.assertEqual(len(payload["capabilities"]), 8)

    def test_config_keeps_every_capability_planned_until_observed(self) -> None:
        payload = json.loads(
            (ROOT / "config" / "gtm_effect_gate_v1.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            set(payload["capability_status"].values()),
            {"planned"},
        )
        self.assertIn("does not claim", payload["truth_boundary"])


if __name__ == "__main__":
    unittest.main()
