from __future__ import annotations

import json
import unittest
from pathlib import Path

from prooflaunch_remix.v10_competition_contract import (
    FULL_CAMPAIGN_PACK,
    OFFICIAL_SCORE_MAXIMA,
    REALTIME_DEMO_PACK,
    BaselineCandidate,
    HumanPreferenceCounts,
    ScoreDimensionEvidence,
    SubmissionPreflight,
    approve_claim,
    arbitrate_dimension_scores,
    blinded_order,
    mastering_claim,
    noncomparable_features,
    overlapping_task_set,
    score_self_check,
    select_top3_baselines,
    validate_pack,
)
from prooflaunch_remix.v10_contracts import V10ContractError, stable_digest


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config/cortex_x_v10_competition_contract_v3.json"
EVIDENCE = ROOT / "evidence/v10/competition-contract-v3-mechanical-fixture.json"


def score_row(dimension: str, maximum: int, points: float, *, observed: bool = True, proxy: bool = False) -> ScoreDimensionEvidence:
    return ScoreDimensionEvidence(
        dimension,
        points,
        maximum,
        "evidence/example.json" if observed else "",
        "a" * 64 if observed else "",
        observed,
        proxy,
    )


def baseline(name: str, rank: int, minutes: int = 20, *, approved: bool = True, executable: bool = True, tasks: tuple[str, ...] = ("plan", "approve")) -> BaselineCandidate:
    return BaselineCandidate(
        name,
        f"https://github.com/example/{name}",
        (hex(rank)[2:] * 40)[:40],
        "MIT",
        approved,
        tasks,
        executable,
        rank,
        minutes,
    )


class CompetitionContractTests(unittest.TestCase):
    def test_current_official_sources_deadline_and_all_fifty_rules_are_frozen(self) -> None:
        contract = json.loads(CONFIG.read_text(encoding="utf-8"))
        sources = {item["source_id"]: item for item in contract["official_sources"]}
        self.assertEqual(
            sources["amd-official-submission-readme"]["revision"],
            "d95240359c837717230b36bdab12df94f1669cf6",
        )
        self.assertEqual(
            sources["modelscope-event-299"]["content_sha256"],
            "ae96835c2edd086af3714268bab8316ac437768ea0f6e75edf65eb795e4ddaa0",
        )
        self.assertEqual(
            contract["deadlines"]["submission_deadline_utc8"],
            "2026-08-06T23:59:00+08:00",
        )
        self.assertEqual(
            [item["todo_id"] for item in contract["todo_rules"]],
            [f"{index:04d}" for index in range(1, 51)],
        )
        self.assertTrue(all(item["source_locator"] for item in contract["todo_rules"]))

    def test_four_dimension_self_check_is_exact_fail_closed_and_not_official_score(self) -> None:
        rows = tuple(
            score_row(dimension, maximum, maximum)
            for dimension, maximum in OFFICIAL_SCORE_MAXIMA.items()
        )
        report = score_self_check(rows)
        self.assertTrue(report.passed)
        self.assertEqual(report.total, 100)
        self.assertIn("not an official judge score", report.truth_boundary)
        proxied = tuple(
            score_row(
                dimension,
                maximum,
                maximum,
                proxy=dimension == "radeon_clarity_stability_diversity",
            )
            for dimension, maximum in OFFICIAL_SCORE_MAXIMA.items()
        )
        self.assertFalse(score_self_check(proxied).passed)
        self.assertEqual(score_self_check(proxied).total, 80)
        with self.assertRaises(V10ContractError):
            score_self_check(rows[:-1])

    def test_demo_inputs_campaign_packs_and_4k_language_are_non_deceptive(self) -> None:
        self.assertEqual(validate_pack(FULL_CAMPAIGN_PACK, realtime=False), FULL_CAMPAIGN_PACK)
        self.assertEqual(validate_pack(REALTIME_DEMO_PACK, realtime=True), REALTIME_DEMO_PACK)
        with self.assertRaises(V10ContractError):
            validate_pack(tuple(reversed(FULL_CAMPAIGN_PACK)), realtime=False)
        nonnative = mastering_claim(
            output_width=3840,
            output_height=2160,
            native_generation_observed=False,
        )
        self.assertIn("Mastered", nonnative)
        self.assertIn("native 4K generation is not claimed", nonnative)
        with self.assertRaises(V10ContractError):
            mastering_claim(output_width=1920, output_height=1080, native_generation_observed=False)

    def test_top3_selection_is_license_revision_hardware_overlap_and_budget_gated(self) -> None:
        rows = (
            baseline("a", 1),
            baseline("b", 2),
            baseline("c", 3),
            baseline("unapproved", 4, approved=False),
        )
        selected = select_top3_baselines(rows, run_budget_minutes=60)
        self.assertEqual(tuple(item.baseline_id for item in selected), ("a", "b", "c"))
        self.assertEqual(overlapping_task_set(selected), ("approve", "plan"))
        self.assertEqual(
            noncomparable_features(("plan", "image_pack", "video_pack"), ("plan",)),
            ("image_pack", "video_pack"),
        )
        with self.assertRaises(V10ContractError):
            select_top3_baselines(rows, run_budget_minutes=59)
        with self.assertRaises(V10ContractError):
            overlapping_task_set((baseline("x", 1, tasks=("x",)), baseline("y", 2, tasks=("y",))))

    def test_blind_review_uses_hashes_seed_raw_counts_wilson_and_rework_boundary(self) -> None:
        first = stable_digest({"artifact": "prooflaunch"})
        second = stable_digest({"artifact": "baseline"})
        self.assertEqual(blinded_order(first, second, seed=42), blinded_order(first, second, seed=42))
        result = HumanPreferenceCounts(130, 150, 145, 5, 5).report()
        self.assertTrue(result["passes_top3_preference"])
        self.assertTrue(result["passes_publishable"])
        self.assertGreater(result["preference_wilson_lower_95"], 0.65)
        with self.assertRaises(V10ContractError):
            HumanPreferenceCounts(10, 10, 9, 2, 5)

    def test_score_conflict_and_leadership_claim_require_independent_approval(self) -> None:
        self.assertEqual(arbitrate_dimension_scores((4.0, 4.5, 5.0)), 4.5)
        with self.assertRaises(V10ContractError):
            arbitrate_dimension_scores((1.0, 4.0, 5.0))
        self.assertEqual(arbitrate_dimension_scores((1.0, 4.0, 5.0), adjudicator="reviewer-4"), 4.0)
        self.assertTrue(
            approve_claim(
                "Top-3 on the frozen overlap set",
                comparison_passed=True,
                approval_id="approval-1",
                evidence_locator="evidence/top3.json",
            )
        )
        self.assertFalse(
            approve_claim(
                "Best GTM employee",
                comparison_passed=False,
                approval_id=None,
                evidence_locator=None,
            )
        )
        self.assertTrue(
            approve_claim(
                "Evidence-grounded campaign workflow",
                comparison_passed=False,
                approval_id=None,
                evidence_locator=None,
            )
        )

    def test_submission_preflight_separates_eligibility_materials_and_external_state(self) -> None:
        report = SubmissionPreflight(
            False,
            False,
            0,
            False,
            True,
            True,
            False,
            True,
            False,
            False,
        ).evaluate()
        self.assertFalse(report["eligible"])
        self.assertFalse(report["materials_complete"])
        self.assertFalse(report["submission_ready"])
        self.assertIn("cannot substitute", report["truth_boundary"])

    def test_generated_receipt_is_hash_bound_and_keeps_external_actions_zero(self) -> None:
        evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
        self.assertEqual(evidence["contract_sha256"], __import__("hashlib").sha256(CONFIG.read_bytes()).hexdigest())
        self.assertEqual(evidence["todo_coverage"]["count"], 50)
        self.assertTrue(evidence["todo_coverage"]["ordered"])
        self.assertTrue(evidence["todo_coverage"]["unique"])
        self.assertEqual(evidence["live_radeon_calls"], 0)
        self.assertEqual(evidence["official_submission_actions"], 0)
        self.assertFalse(evidence["submission_preflight"]["submission_ready"])


if __name__ == "__main__":
    unittest.main()
