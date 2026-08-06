from __future__ import annotations

import json
import unittest
from pathlib import Path

from prooflaunch_remix.v10_contracts import V10ContractError
from prooflaunch_remix.v10_research_ledger import (
    EvidenceStrength,
    ExperimentReceipt,
    FalsifiableStudy,
    MetricDirection,
    MetricGate,
    ResearchDisposition,
    StudyBudget,
    innovation_combinations,
    negative_experiments,
    result_leaderboard,
)


ROOT = Path(__file__).resolve().parents[1]


def study(research_id: str, score: int = 5) -> FalsifiableStudy:
    return FalsifiableStudy(
        research_id,
        "A frozen objective hypothesis.",
        ("equal-budget control",),
        (
            MetricGate("success", MetricDirection.MIN, 0.8),
            MetricGate("regression", MetricDirection.MAX, 0.005),
        ),
        StudyBudget(10, 20, 0.0, 16),
        "stop on first hard-gate failure",
        ResearchDisposition.DIRECT_ADOPT,
        score,
        score,
        score,
    )


class ResearchLedgerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ledger = json.loads(
            (ROOT / "config/cortex_x_v10_research_ledger_v1.json").read_text()
        )

    def test_registry_is_complete_and_in_exact_todo_order(self) -> None:
        self.assertEqual(self.ledger["counts"]["research_sources"], 25)
        self.assertEqual(
            [item["todo_id"] for item in self.ledger["sources"]],
            [f"{value:04d}" for value in range(107, 132)],
        )

    def test_every_source_has_version_hardware_scope_and_failure(self) -> None:
        for item in self.ledger["sources"]:
            self.assertRegex(item["version_date"], r"^20\d\d-\d\d-\d\d$")
            self.assertTrue(item["hardware_scale"])
            self.assertTrue(item["original_task_scope"])
            self.assertTrue(item["known_failure_modes"])
            if item["official_implementation_url"]:
                self.assertEqual(len(item["implementation_revision"]), 40)

    def test_every_study_is_falsifiable_and_bounded(self) -> None:
        self.assertEqual(self.ledger["counts"]["falsifiable_studies"], 25)
        for item in self.ledger["studies"]:
            self.assertTrue(item["hypothesis"])
            self.assertGreaterEqual(len(item["controls"]), 1)
            self.assertGreaterEqual(len(item["metrics"]), 2)
            self.assertGreater(item["budget"]["gpu_minutes"], 0)
            self.assertTrue(item["stop_condition"])

    def test_subjective_only_metric_is_rejected(self) -> None:
        with self.assertRaises(V10ContractError):
            MetricGate("looks amazing", MetricDirection.MIN, 1.0, objective=False)

    def test_paper_or_code_metadata_cannot_be_an_experiment_receipt(self) -> None:
        with self.assertRaises(V10ContractError):
            ExperimentReceipt(
                "R1",
                "run-1",
                EvidenceStrength.CODE_INSPECTED,
                {"success": 1.0},
                True,
                False,
                "evidence/run.json",
            )

    def test_unexecuted_research_cannot_enter_result_leaderboard(self) -> None:
        self.assertEqual(result_leaderboard((study("R1"),), ()), ())
        self.assertEqual(innovation_combinations((study("R1"),), ()), ())

    def test_negative_receipt_is_retained_and_not_promoted(self) -> None:
        receipt = ExperimentReceipt(
            "R1",
            "run-1",
            EvidenceStrength.REPRODUCED,
            {"success": 0.2, "regression": 0.1},
            False,
            True,
            "evidence/run.json",
        )
        self.assertEqual(negative_experiments((receipt,)), (receipt,))
        self.assertEqual(result_leaderboard((study("R1"),), (receipt,)), ())

    def test_only_passed_executed_receipts_can_be_combined(self) -> None:
        studies = (study("R1", 5), study("R2", 4))
        receipts = tuple(
            ExperimentReceipt(
                item.research_id,
                f"run-{item.research_id}",
                EvidenceStrength.REPRODUCED,
                {"success": 0.9, "regression": 0.0},
                True,
                False,
                f"evidence/{item.research_id}.json",
            )
            for item in studies
        )
        self.assertEqual(innovation_combinations(studies, receipts), ("R1", "R2"))

    def test_frozen_ledger_claims_zero_live_reproduction(self) -> None:
        counts = self.ledger["counts"]
        self.assertEqual(counts["executed_receipts"], 0)
        self.assertEqual(counts["result_leaderboard"], 0)
        self.assertEqual(counts["promoted_combinations"], 0)


if __name__ == "__main__":
    unittest.main()
