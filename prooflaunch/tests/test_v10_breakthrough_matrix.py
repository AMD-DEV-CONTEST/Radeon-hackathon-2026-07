from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from prooflaunch_remix.v10_breakthrough_matrix import (
    BREAKTHROUGHS,
    build_breakthrough_matrix,
)
from prooflaunch_remix.v10_contracts import (
    BreakthroughEvidenceBundle,
    EvidenceAxis,
    EvidenceClass,
    EvidencePointer,
)


ROOT = Path(__file__).resolve().parents[1]


def pointer(evidence_class: EvidenceClass) -> EvidencePointer:
    return EvidencePointer(
        EvidenceAxis.EVIDENCE,
        "evidence://test",
        "a" * 64,
        evidence_class,
        "test pointer",
    )


class BreakthroughEvidencePolicyTests(unittest.TestCase):
    def test_twenty_lens_synthesis_has_exact_balanced_primary_sources(self) -> None:
        payload = json.loads(
            (ROOT / "evidence/v10/20-lens-synthesis.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(len(payload["researcher_lenses"]), 10)
        self.assertEqual(len(payload["product_technology_lenses"]), 10)
        ids = [
            item["id"]
            for group in (
                payload["researcher_lenses"],
                payload["product_technology_lenses"],
            )
            for item in group
        ]
        self.assertEqual(ids, [f"R{i:02d}" for i in range(1, 11)] + [
            f"P{i:02d}" for i in range(1, 11)
        ])
        self.assertTrue(
            all(
                item["source"].startswith("https://")
                for group in (
                    payload["researcher_lenses"],
                    payload["product_technology_lenses"],
                )
                for item in group
            )
        )
        self.assertIn("No person or organization", payload["truth_boundary"])

    def test_proxy_placeholder_does_not_satisfy_required_section(self) -> None:
        observed = (pointer(EvidenceClass.OBSERVED),)
        proxy = (pointer(EvidenceClass.PROXY),)
        bundle = BreakthroughEvidenceBundle(
            "BT25",
            code=observed,
            configuration=observed,
            data_rights=proxy,
            logs=observed,
            ablations=proxy,
            radeon_traces=proxy,
            product_tests=proxy,
            effect_tests=proxy,
        )
        self.assertEqual(
            bundle.missing_sections(),
            (
                "data_rights",
                "ablations",
                "radeon_traces",
                "product_tests",
                "effect_tests",
            ),
        )

    def test_matrix_defines_exact_twelve_contiguous_bets(self) -> None:
        self.assertEqual(
            [item.bet_id for item in BREAKTHROUGHS],
            [f"BT{number}" for number in range(25, 37)],
        )
        self.assertEqual(
            sum(item.gpu_budget_hours for item in BREAKTHROUGHS),
            40,
        )

    def test_matrix_holds_every_bet_without_external_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in (
                "config/cortex_x_v10_training_plan.json",
                "tests/test_v10_breakthroughs.py",
                "notebooks/prooflaunch_cortex_x_v10_radeon.ipynb",
            ):
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("{}", encoding="utf-8")
            report = root / "evidence/v10/local-test-report.json"
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text(
                json.dumps({"status": "passed"}),
                encoding="utf-8",
            )
            for definition in BREAKTHROUGHS:
                for relative in definition.implementation_files:
                    target = root / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text("reference", encoding="utf-8")
            payload = build_breakthrough_matrix(
                root,
                generated_at="2026-07-29T00:00:00+00:00",
            )
        self.assertEqual(payload["summary"]["bet_count"], 12)
        self.assertEqual(
            payload["summary"]["verdict_counts"],
            {"promote": 0, "hold": 12, "reject": 0},
        )
        self.assertFalse(payload["summary"]["promotion_floor_met"])
        self.assertTrue(
            all(
                item["decision"]["verdict"] == "hold"
                for item in payload["bets"]
            )
        )


if __name__ == "__main__":
    unittest.main()
