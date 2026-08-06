import json
import tempfile
import unittest
from pathlib import Path

from incident_commander.evaluator import EvaluationError, evaluate, load_cases, main


class EvaluatorTests(unittest.TestCase):
    def test_scores_localization_identification_and_reason(self) -> None:
        ground_truth = [
            {
                "case_id": "t001",
                "localization": ["checkout-api"],
                "identification": ["database connection pool contention"],
                "reason": ["rc3 enabled the pricing lookup", "pool waiters increased to 137"],
            }
        ]
        predictions = [
            {
                "case_id": "t001",
                "localization": ["checkout-api"],
                "identification": ["database connection pool contention"],
                "reason": "The rc3 release enabled the pricing lookup, after which pool waiters increased to 137.",
            }
        ]

        result = evaluate(predictions, ground_truth)

        self.assertEqual(result["aggregate"]["localization"], 1.0)
        self.assertEqual(result["aggregate"]["identification"], 1.0)
        self.assertEqual(result["aggregate"]["reason"], 1.0)
        self.assertEqual(result["aggregate"]["overall"], 1.0)

    def test_missing_prediction_is_scored_as_zero(self) -> None:
        ground_truth = [
            {"case_id": "t001", "localization": "api", "identification": "timeout", "reason": ["checkpoint"]},
            {"case_id": "t002", "localization": "db", "identification": "saturation", "reason": ["checkpoint"]},
        ]
        predictions = [
            {"case_id": "t001", "localization": "api", "identification": "timeout", "reason": "checkpoint"}
        ]

        result = evaluate(predictions, ground_truth)

        self.assertEqual(result["aggregate"]["matched_cases"], 1)
        self.assertEqual(result["aggregate"]["missing_predictions"], 1)
        self.assertEqual(result["aggregate"]["overall"], 0.5)

    def test_loader_accepts_cases_envelope_and_rejects_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cases.json"
            path.write_text(json.dumps({"cases": [{"case_id": "one"}]}), encoding="utf-8")
            self.assertEqual(load_cases(path)[0]["case_id"], "one")

            path.write_text(json.dumps({"cases": [{"case_id": "one"}, {"case_id": "one"}]}), encoding="utf-8")
            with self.assertRaisesRegex(EvaluationError, "duplicate"):
                load_cases(path)

    def test_cli_writes_machine_readable_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prediction = root / "prediction.json"
            truth = root / "truth.json"
            output = root / "result.json"
            value = {
                "cases": [
                    {"case_id": "one", "localization": "api", "identification": "timeout", "reason": ["503 spike"]}
                ]
            }
            prediction.write_text(json.dumps(value), encoding="utf-8")
            truth.write_text(json.dumps(value), encoding="utf-8")

            exit_code = main(["--predictions", str(prediction), "--ground-truth", str(truth), "--output", str(output)])

            self.assertEqual(exit_code, 0)
            saved = json.loads(output.read_text(encoding="utf-8"))
            self.assertFalse(saved["official_score"])
            self.assertEqual(saved["aggregate"]["overall"], 1.0)


if __name__ == "__main__":
    unittest.main()
