import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1] / "summarize_technology20_evaluation.py"
)
SPEC = importlib.util.spec_from_file_location("technology20_summary", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class Technology20EvaluationSummaryTests(unittest.TestCase):
    def test_summary_is_aggregate_only_and_measures_gates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cases = root / "shard-00" / "cases"
            cases.mkdir(parents=True)
            payload = {
                "journey_id": "AAPL-fundamentals",
                "company_id": "sec-cik:0000320193",
                "question_id": "fundamentals",
                "runtime_passed": True,
                "required_sections_passed": True,
                "claim_authority_passed": True,
                "both_critics_approved": True,
                "required_receipts_passed": True,
                "expected_abstentions_passed": True,
                "visible_limitations": True,
                "contract_passed": True,
                "duration_ms": 1250.5,
                "model_calls": 6,
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "report": {
                    "private_prompt": "must not be copied",
                    "model_calls": [
                        {
                            "duration_ns": 2_000_000_000,
                            "ttft_ns": 250_000_000,
                            "completion_tokens": 20,
                            "failed": False,
                        }
                    ],
                },
            }
            (cases / "AAPL-fundamentals.json").write_text(json.dumps(payload))
            result = MODULE.summarize(root, 1)
            self.assertTrue(result["population_complete"])
            self.assertEqual(result["evaluation_kind"], "standalone")
            self.assertEqual(result["contract_pass_rate"], 1.0)
            self.assertEqual(result["by_question"]["fundamentals"]["cases"], 1)
            self.assertEqual(result["failed_gate_counts"], {})
            self.assertEqual(result["failure_signatures"], {})
            self.assertEqual(
                result["by_company"]["sec-cik:0000320193"]["gate_pass_rates"][
                    "required_receipts_passed"
                ],
                1.0,
            )
            self.assertEqual(
                result["packet_authority_integrity"]["packets_failed"], 0
            )
            self.assertEqual(
                result["model_call_performance"]["ttft_ms"]["p50"], 250.0
            )
            self.assertEqual(
                result["model_call_performance"][
                    "completion_tokens_per_second_end_to_end"
                ]["p50"],
                10.0,
            )
            self.assertNotIn("private_prompt", json.dumps(result))

    def test_gate_failures_are_visible_without_private_output_or_failure_code(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cases = root / "shard-00" / "cases"
            cases.mkdir(parents=True)
            payload = {
                "journey_id": "ADBE-cash-quality",
                "company_id": "sec-cik:0000796343",
                "question_id": "cash-quality",
                "runtime_passed": True,
                "required_sections_passed": True,
                "claim_authority_passed": True,
                "both_critics_approved": True,
                "required_receipts_passed": False,
                "expected_abstentions_passed": True,
                "visible_limitations": True,
                "contract_passed": False,
                "report": {
                    "prompt": "private",
                    "response": "private",
                },
            }
            (cases / "ADBE-cash-quality.json").write_text(json.dumps(payload))

            result = MODULE.summarize(root, 1)

            self.assertEqual(result["failure_codes"], {})
            self.assertEqual(result["failed_gate_counts"]["contract_passed"], 1)
            self.assertEqual(
                result["failed_gate_counts"]["required_receipts_passed"], 1
            )
            self.assertEqual(
                result["failure_signatures"][
                    "contract_passed+required_receipts_passed"
                ],
                1,
            )
            self.assertEqual(
                result["by_question"]["cash-quality"]["gate_pass_rates"][
                    "required_receipts_passed"
                ],
                0.0,
            )
            serialized = json.dumps(result)
            self.assertNotIn('"prompt": "private"', serialized)
            self.assertNotIn('"response": "private"', serialized)

    def test_packet_authority_integrity_detects_missing_receipt_without_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cases = root / "shard-00" / "cases"
            cases.mkdir(parents=True)
            payload = {
                "journey_id": "ADBE-cash-quality",
                "company_id": "sec-cik:0000796343",
                "question_id": "cash-quality",
                "report": {
                    "result": {
                        "packets": [
                            {
                                "evidence": [{"evidence_id": "evidence-1"}],
                                "calculation_receipts": [
                                    {"receipt_id": "receipt-present"}
                                ],
                                "numerical_context": {
                                    "variables": [
                                        {
                                            "variable_id": "variable-1",
                                            "receipt_refs": ["receipt-missing"],
                                        }
                                    ],
                                    "relations": [],
                                },
                                "findings": [
                                    {
                                        "evidence_refs": ["evidence-1"],
                                        "calculation_refs": ["receipt-present"],
                                        "numerical_refs": ["variable-1"],
                                    }
                                ],
                            }
                        ]
                    }
                },
            }
            (cases / "ADBE-cash-quality.json").write_text(json.dumps(payload))

            result = MODULE.summarize(root, 1)
            integrity = result["packet_authority_integrity"]

            self.assertEqual(integrity["packets_observed"], 1)
            self.assertEqual(integrity["packets_failed"], 1)
            self.assertEqual(
                integrity["missing_reference_counts"][
                    "numerical_variable_receipt"
                ],
                1,
            )
            self.assertNotIn("receipt-missing", json.dumps(integrity))

    def test_duplicate_journey_ids_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for shard in ("a", "b"):
                cases = root / shard / "cases"
                cases.mkdir(parents=True)
                (cases / "case.json").write_text(
                    json.dumps({"journey_id": "duplicate"})
                )
            with self.assertRaisesRegex(ValueError, "duplicate journey_id"):
                MODULE.summarize(root, 2)

    def test_peer_summary_uses_peer_gates_and_lane_groups(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cases = root / "shard-00" / "cases"
            cases.mkdir(parents=True)
            payload = {
                "journey_id": "microsoft-alphabet-boundary",
                "lane_id": "microsoft-alphabet",
                "question_id": "boundary",
                "runtime_passed": True,
                "required_sections_passed": True,
                "claim_authority_passed": True,
                "both_critics_approved": True,
                "metric_authority_passed": True,
                "unavailable_metrics_withheld": True,
                "visible_comparison_boundary": True,
                "no_unsupported_pair_ranking": True,
                "contract_passed": True,
            }
            (cases / "peer.json").write_text(json.dumps(payload))
            result = MODULE.summarize(root, 1)
            self.assertEqual(result["evaluation_kind"], "peer")
            self.assertEqual(
                result["by_lane"]["microsoft-alphabet"]["contract_pass_rate"], 1.0
            )
            self.assertNotIn("visible_limitations", result["gate_counts"])

    def test_mixed_population_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cases = root / "cases" / "cases"
            cases.mkdir(parents=True)
            (cases / "standalone.json").write_text(
                json.dumps({"journey_id": "standalone"})
            )
            (cases / "peer.json").write_text(
                json.dumps({"journey_id": "peer", "lane_id": "lane"})
            )
            with self.assertRaisesRegex(ValueError, "mixed standalone and peer"):
                MODULE.summarize(root, 2)


if __name__ == "__main__":
    unittest.main()
