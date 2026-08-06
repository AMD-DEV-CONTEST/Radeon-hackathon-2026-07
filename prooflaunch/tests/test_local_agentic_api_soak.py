from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RECEIPT_PATH = ROOT / "evidence/v10/local-agentic-api-soak-v1.json"


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


class LocalAgenticApiSoakEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.receipt = json.loads(RECEIPT_PATH.read_text(encoding="utf-8"))

    def test_receipt_is_content_addressed(self) -> None:
        self.assertEqual(
            self.receipt["schema"], "ProofLaunchLocalAgenticApiSoakV1"
        )
        unsigned = dict(self.receipt)
        supplied = unsigned.pop("content_sha256")
        self.assertEqual(supplied, hashlib.sha256(_canonical(unsigned)).hexdigest())

    def test_all_frozen_matrix_cases_cross_real_http_worker_boundary(self) -> None:
        execution = self.receipt["execution"]
        acceptance = self.receipt["acceptance"]
        self.assertEqual(self.receipt["source_matrix"]["case_count"], 456)
        self.assertEqual(execution["transport"], "real_loopback_http")
        self.assertEqual(execution["accepted_run_count"], 456)
        self.assertEqual(execution["awaiting_human_release_count"], 456)
        self.assertEqual(execution["unique_run_id_count"], 456)
        self.assertTrue(acceptance["all_456_cases_accepted"])
        self.assertTrue(acceptance["all_456_cases_prepared_to_human_gate"])
        self.assertTrue(acceptance["zero_worker_failures"])

    def test_restart_trace_and_truth_boundaries_are_fail_closed(self) -> None:
        execution = self.receipt["execution"]
        trace = self.receipt["trace_ledger"]
        boundary = self.receipt["truth_boundary"]
        self.assertEqual(execution["restart_count"], 1)
        self.assertTrue(execution["durable_run_recovered_after_restart"])
        self.assertEqual(trace["request_trace_count"], 914)
        self.assertEqual(trace["exception_trace_count"], 0)
        self.assertTrue(trace["hash_chain_valid"])
        self.assertFalse(trace["raw_content_retained"])
        self.assertEqual(execution["external_model_api_calls"], 0)
        self.assertEqual(execution["external_gpu_sessions"], 0)
        self.assertEqual(execution["external_publish_or_send_actions"], 0)
        self.assertFalse(boundary["production_deployment_observed"])
        self.assertFalse(boundary["radeon_local_key_inference_observed"])
        self.assertFalse(boundary["real_effect_observed"])
        self.assertFalse(boundary["causal_revenue_observed"])
        self.assertFalse(boundary["four_a_or_top_one_claim_eligible"])


if __name__ == "__main__":
    unittest.main()
