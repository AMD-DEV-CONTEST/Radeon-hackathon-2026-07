from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "run_model_matrix.py"
SPEC = importlib.util.spec_from_file_location("run_model_matrix", SOURCE)
assert SPEC and SPEC.loader
MATRIX = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MATRIX)


class ModelMatrixTests(unittest.TestCase):
    def test_example_declares_two_external_models(self) -> None:
        models = MATRIX.load_manifest(ROOT / "model-matrix.example.json")
        self.assertEqual([item["name"] for item in models], ["openpi", "opendm"])
        self.assertEqual(
            [item["expected_identity"]["provider"] for item in models],
            ["openpi-jax", "opendm-dm05"],
        )

    def test_manifest_requires_exactly_two_unique_models(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "matrix.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "models": [
                            {"name": "only-one", "base_url_env": "ONLY_URL"}
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "exactly two"):
                MATRIX.load_manifest(path)

    def test_health_freezes_required_and_expected_identity(self) -> None:
        payload = {
            "status": "ok",
            "protocol_version": 2,
            "policy_identity": {
                "provider": "opendm-dm05",
                "model_id": "model",
                "model_revision": "revision",
                "adapter_source_sha256": "a" * 64,
            },
        }
        self.assertIs(
            MATRIX.validate_health(payload, {"provider": "opendm-dm05"}),
            payload,
        )
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            MATRIX.validate_health(payload, {"provider": "openpi-jax"})

    def test_runner_contains_no_model_runtime(self) -> None:
        source = SOURCE.read_text(encoding="utf-8")
        for forbidden in ("import torch", "import jax", "transformers", "model_path"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
