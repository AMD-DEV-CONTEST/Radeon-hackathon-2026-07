from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

from prooflaunch_remix.inference_gateway import InferenceGatewayCallError


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/run_local_gtm_creative_benchmark.py"
SPEC = importlib.util.spec_from_file_location("local_gtm_creative_benchmark", SCRIPT)
if SPEC is None or SPEC.loader is None:  # pragma: no cover - import contract
    raise RuntimeError("failed to load local GTM creative benchmark script")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class LocalGTMCreativeBenchmarkTests(unittest.TestCase):
    def test_frozen_matrix_covers_b2b_b2c_all_lifecycles_budgets_and_risk(self) -> None:
        cases = MODULE.SCENARIOS
        self.assertEqual(len(cases), 9)
        self.assertEqual({row["business_model"] for row in cases}, {"b2b", "b2c"})
        self.assertEqual(
            {row["lifecycle"] for row in cases},
            {"pre_pmf", "launch", "growth", "mature"},
        )
        self.assertEqual({row["budget"] for row in cases}, {"zero", "small", "scaled"})
        self.assertEqual(
            {row["industry_risk"] for row in cases},
            {"standard", "high_regulation"},
        )
        self.assertEqual(len({row["case_id"] for row in cases}), len(cases))
        self.assertEqual(sum(row["budget"] == "zero" for row in cases), 4)
        self.assertEqual(
            sum(row["industry_risk"] == "high_regulation" for row in cases),
            2,
        )

    def test_preflight_blocker_is_truthful_and_contains_no_false_execution(self) -> None:
        error = InferenceGatewayCallError(
            "local Ollama inference failed",
            {
                "schema": "ProofLaunchResilientInferenceGatewayV1",
                "provider": "ollama_local",
                "model": "qwen2.5-coder:1.5b",
                "model_digest": "d" * 64,
                "localhost_only": True,
                "cloud_api_calls": 0,
                "network_download_performed": False,
                "status": "blocked",
                "error_code": "network_error",
            },
        )
        status = MODULE._blocked_status(
            model_name="qwen2.5-coder:1.5b",
            model_digest="d" * 64,
            model_receipt_sha="r" * 64,
            error=error,
            output_dir=ROOT / "artifacts/local-gtm-creative-benchmark-test",
        )
        self.assertEqual(status["status"], "blocked_preflight")
        self.assertEqual(status["planned_case_count"], 9)
        self.assertEqual(status["planned_model_call_count"], 27)
        self.assertEqual(status["completed_case_count"], 0)
        self.assertEqual(status["completed_model_call_count"], 0)
        self.assertFalse(status["preflight"]["passed"])
        self.assertTrue(status["retry_when_accelerator_contention_clears"])
        self.assertFalse(status["network_download_performed"])
        self.assertEqual(status["cloud_api_calls"], 0)
        self.assertFalse(status["training_observed"])
        self.assertFalse(status["human_review_completed"])
        self.assertFalse(status["radeon_local_inference_observed"])
        self.assertFalse(status["automatic_external_action_enabled"])
        json.dumps(status, ensure_ascii=False, sort_keys=True)

    def test_negative_risk_descriptions_do_not_masquerade_as_effect_claims(self) -> None:
        serialized = json.dumps(MODULE.SCENARIOS, ensure_ascii=False).casefold()
        self.assertNotIn("guaranteed outcomes", serialized)
        self.assertNotIn("outcome guarantees", serialized)
        regulated = [
            row
            for row in MODULE.SCENARIOS
            if row["industry_risk"] == "high_regulation"
        ]
        self.assertEqual(len(regulated), 2)
        self.assertTrue(
            all("specialist review" in row["buying_context"] for row in regulated)
        )


if __name__ == "__main__":
    unittest.main()
