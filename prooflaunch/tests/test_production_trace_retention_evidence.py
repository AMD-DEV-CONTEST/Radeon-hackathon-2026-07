from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / "evidence/v10/production-trace-retention-v1.json"


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class ProductionTraceRetentionEvidenceTests(unittest.TestCase):
    def test_local_retention_receipt_is_hash_bound_and_truthful(self) -> None:
        receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
        unsigned = dict(receipt)
        supplied = unsigned.pop("content_sha256")
        self.assertEqual(
            supplied,
            hashlib.sha256(_canonical(unsigned).encode("utf-8")).hexdigest(),
        )
        self.assertEqual(
            receipt["schema"], "ProofLaunchProductionTraceRetentionContractV1"
        )
        self.assertEqual(receipt["retention_days"], 90)
        self.assertTrue(receipt["local_restart_smoke_observed"])
        self.assertEqual(receipt["local_request_trace_count"], 1)
        self.assertTrue(receipt["hash_chain_valid"])
        self.assertTrue(receipt["valid_request_boundary_instrumented"])
        self.assertFalse(receipt["raw_content_retained"])
        self.assertFalse(receipt["remote_required_check_observed"])
        self.assertFalse(receipt["production_deployment_observed"])
        self.assertFalse(receipt["production_trace_coverage_observed"])
        for relative, expected in receipt["source_file_sha256"].items():
            self.assertEqual(
                hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(), expected
            )
        self.assertIn("does not prove", receipt["truth_boundary"])


if __name__ == "__main__":
    unittest.main()
