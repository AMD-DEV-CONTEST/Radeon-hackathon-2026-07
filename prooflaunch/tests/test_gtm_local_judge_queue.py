from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from prooflaunch_remix.gtm_judge_calibration import JudgeCalibrationService, PUBLIC_NAME
from prooflaunch_remix.gtm_local_judge_queue import (
    LocalJudgeQueueError,
    build_case_blueprints,
    execute_local_predictions,
    mechanical_oracle,
    parse_model_judgement,
    seal_local_judge_queue,
)


ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "evidence/v10/gtm-lifecycle-closure-matrix-v1.json"
TOKENS = {slot: f"local-judge-test-reviewer-{slot}-000000" for slot in range(1, 6)}


class FakeJudge:
    def __init__(self, *, forced: bool | None = None) -> None:
        self.calls = 0
        self.forced = forced

    def complete(self, messages, **kwargs):
        self.calls += 1
        judge_input = json.loads(messages[-1]["content"])
        prediction = (
            judge_input["all_checks_satisfied"]
            if self.forced is None
            else self.forced
        )
        content = json.dumps({"pass": prediction, "reason_code": "bounded_test_reason"})
        return SimpleNamespace(
            content=content,
            usage={"prompt_tokens": 200, "completion_tokens": 12},
            receipt={
                "request_sha256": f"{self.calls:064x}",
                "normalized_response_sha256": f"{self.calls + 1000:064x}",
            },
        )


class LocalJudgeQueueTests(unittest.TestCase):
    def matrix(self):
        return json.loads(MATRIX.read_text(encoding="utf-8"))

    def test_blueprints_cover_all_dimensions_and_balance_fifty_fifty(self) -> None:
        blueprints, coverage = build_case_blueprints(self.matrix())
        self.assertEqual(len(blueprints), 100)
        self.assertEqual(len({row["artifact_sha256"] for row in blueprints}), 100)
        self.assertEqual(coverage["source_case_count"], 50)
        self.assertEqual(coverage["industry_count"], 20)
        self.assertEqual(coverage["scenario_combination_count"], 48)
        self.assertEqual(coverage["business_models"], ["b2b", "b2c"])
        self.assertEqual(coverage["oracle_positive_count"], 50)
        self.assertEqual(coverage["oracle_negative_count"], 50)
        for index in range(0, 100, 2):
            self.assertTrue(mechanical_oracle(blueprints[index]["dossier"]))
            self.assertFalse(mechanical_oracle(blueprints[index + 1]["dossier"]))
            self.assertEqual(
                blueprints[index]["failure_slice"],
                blueprints[index + 1]["failure_slice"],
            )

    def test_parser_requires_exact_bounded_binary_json(self) -> None:
        self.assertEqual(
            parse_model_judgement('{"pass":true,"reason_code":"all_clear"}'),
            (True, "all_clear"),
        )
        for raw in (
            "PASS",
            '{"pass":1,"reason_code":"all_clear"}',
            '{"pass":true,"reason_code":"ALL CLEAR"}',
            '{"pass":true,"reason_code":"ok","extra":1}',
        ):
            with self.assertRaises(LocalJudgeQueueError):
                parse_model_judgement(raw)

    def test_predictions_are_independent_balanced_and_fail_on_collapse(self) -> None:
        blueprints, _ = build_case_blueprints(self.matrix())
        client = FakeJudge()
        cases, rows = execute_local_predictions(blueprints, client, timeout_seconds=10)
        self.assertEqual(client.calls, 100)
        self.assertEqual(len(cases), len(rows), 100)
        self.assertEqual(sum(row["judge_prediction"] is True for row in cases), 50)
        self.assertEqual(sum(row["judge_prediction"] is False for row in cases), 50)
        with self.assertRaises(LocalJudgeQueueError):
            execute_local_predictions(blueprints, FakeJudge(forced=True), timeout_seconds=10)

    def test_sealed_queue_has_real_model_receipts_but_zero_human_labels(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            status = seal_local_judge_queue(
                lifecycle_matrix_path=MATRIX,
                model_name="test-local-model",
                model_digest="a" * 64,
                client=FakeJudge(),
                private_source_root=root / "private-source",
                bundle_root=root / "bundle",
                status_path=root / "status.json",
                assignment_seed="test-only-assignment-seed-v1",
                timeout_seconds=10,
            )
            self.assertEqual(status["observed_model_call_count"], 100)
            self.assertEqual(status["expected_human_label_count"], 300)
            self.assertEqual(status["real_human_label_count"], 0)
            self.assertFalse(status["judge_calibrated"])
            self.assertFalse(Path(status["source"]["path"]).is_absolute())
            self.assertEqual((root / "private-source").stat().st_mode & 0o077, 0)
            public = json.loads((root / "bundle" / PUBLIC_NAME).read_text())
            self.assertNotIn('"judge_prediction":', json.dumps(public))
            service = JudgeCalibrationService(root / "bundle", reviewer_tokens=TOKENS)
            self.assertEqual(service.status()["submitted_review_count"], 0)
            self.assertFalse(service.status()["judge_calibrated"])


if __name__ == "__main__":
    unittest.main()
