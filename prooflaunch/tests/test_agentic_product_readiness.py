from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from prooflaunch_remix.agentic_product_readiness import (
    compile_agentic_product_readiness,
    validate_agentic_product_readiness,
)


ROOT = Path(__file__).resolve().parents[1]


class AgenticProductReadinessTests(unittest.TestCase):
    def test_compiler_keeps_unproven_launch_properties_as_gaps(self) -> None:
        receipt = compile_agentic_product_readiness(
            ROOT, generated_at="2026-08-02T00:00:00Z"
        )
        validate_agentic_product_readiness(receipt, ROOT)
        self.assertEqual(receipt["audit_item_count"], 12)
        sandbox_observed = (
            ROOT / "evidence/v10/tool-execution-sandbox-v1.json"
        ).is_file()
        self.assertEqual(receipt["passed_item_count"], 9 if sandbox_observed else 8)
        self.assertEqual(receipt["gap_item_count"], 3 if sandbox_observed else 4)
        by_id = {item["id"]: item for item in receipt["items"]}
        expected_passes = {
                "PR-01",
                "PR-02",
                "PR-03",
                "PR-04",
                "PR-05",
                "PR-07",
                "PR-08",
                "PR-10",
        }
        if sandbox_observed:
            expected_passes.add("PR-06")
        self.assertEqual(
            {item_id for item_id, item in by_id.items() if item["status"] == "pass"},
            expected_passes,
        )
        self.assertEqual(by_id["PR-11"]["status"], "gap")
        self.assertIn("zero qualifying human calibration labels", by_id["PR-11"]["finding"])
        self.assertIn("does not prove 4A preference", receipt["truth_boundary"])

    def test_validator_rejects_status_or_evidence_tamper(self) -> None:
        receipt = compile_agentic_product_readiness(
            ROOT, generated_at="2026-08-02T00:00:00Z"
        )
        tampered = copy.deepcopy(receipt)
        tampered["items"][0]["status"] = "gap"
        with self.assertRaisesRegex(ValueError, "digest"):
            validate_agentic_product_readiness(tampered, ROOT)

        stale = json.loads(json.dumps(receipt))
        stale["items"][0]["evidence"][0]["file_sha256"] = "0" * 64
        unsigned = dict(stale)
        unsigned.pop("content_sha256")
        import hashlib

        stale["content_sha256"] = hashlib.sha256(
            json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        with self.assertRaisesRegex(ValueError, "evidence digest"):
            validate_agentic_product_readiness(stale, ROOT)


if __name__ == "__main__":
    unittest.main()
