import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "build_peer_boundary_matrix", ROOT / "scripts" / "build_peer_boundary_matrix.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class PeerBoundaryMatrixTests(unittest.TestCase):
    def setUp(self):
        self.source_path = (
            ROOT / "fixtures" / "productscope" / "technology20-peer-evaluation.json"
        )
        self.source_bytes = self.source_path.read_bytes()
        self.source = json.loads(self.source_bytes)
        self.matrix = MODULE.build_matrix(
            self.source, MODULE.sha256_bytes(self.source_bytes)
        )

    def test_matrix_covers_all_lanes_and_metrics_without_values(self):
        self.assertEqual(len(self.matrix["lanes"]), 5)
        expected_metrics = sum(
            len(lane.get("receipts", [])) + len(lane.get("abstentions", []))
            for lane in self.source["lanes"]
        )
        actual_metrics = sum(len(lane["metrics"]) for lane in self.matrix["lanes"])
        self.assertEqual(actual_metrics, expected_metrics)
        self.assertNotIn('"value"', json.dumps(self.matrix, sort_keys=True))

    def test_receipt_operands_expose_every_required_boundary(self):
        required = {
            "security_id",
            "security_class_state",
            "definition_id",
            "taxonomy_concept",
            "unit",
            "currency",
            "scale",
            "sign_policy",
            "dimensional_identity",
            "segment_scope",
            "accounting_perimeter",
            "period_type",
            "fiscal_start",
            "fiscal_end",
            "filing_date",
            "market_observation_state",
            "market_observation_date",
        }
        operands = [
            operand
            for lane in self.matrix["lanes"]
            for metric in lane["metrics"]
            for operand in metric["operands"]
        ]
        self.assertTrue(operands)
        for operand in operands:
            self.assertTrue(required.issubset(operand))
            self.assertEqual(operand["security_class_state"], "not_activated")
            self.assertEqual(operand["market_observation_state"], "not_activated")
            self.assertIsNone(operand["market_observation_date"])

    def test_output_is_deterministic(self):
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first.json"
            second = Path(directory) / "second.json"
            payload = MODULE.canonical_json(self.matrix)
            first.write_bytes(payload)
            second.write_bytes(payload)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(
                MODULE.sha256_bytes(first.read_bytes()),
                MODULE.sha256_bytes(second.read_bytes()),
            )

    def test_committed_projection_matches_governed_receipts(self):
        committed = (
            ROOT
            / "fixtures"
            / "productscope"
            / "technology20-peer-boundary-matrix.json"
        )
        self.assertEqual(committed.read_bytes(), MODULE.canonical_json(self.matrix))


if __name__ == "__main__":
    unittest.main()
