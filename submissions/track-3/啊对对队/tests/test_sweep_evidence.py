import csv
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from parcel_sorter.sweep_evidence import build_sweep_evidence


class SweepEvidenceTests(unittest.TestCase):
    def test_validates_and_hashes_complete_matrix(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory) / "sweep"
            root.mkdir()
            split = Path(directory) / "split.json"
            split.write_text("{}\n", encoding="utf-8")
            self._write_matrix(root)

            result = build_sweep_evidence(root, split, expected_steps=5)

            self.assertEqual(result["contract"]["cell_count"], 6)
            self.assertEqual(result["claim_scope"], "integration_smoke_only_not_model_selection")
            self.assertEqual(len(result["cells"]), 6)
            rgbd = next(
                cell
                for cell in result["cells"]
                if cell["modality"] == "rgb-d" and cell["seed"] == 11
            )
            self.assertIn("observation.images.overhead_depth_rgb", rgbd["visual_inputs"])
            self.assertTrue(rgbd["checkpoint"]["files"][0]["sha256"])

    def test_rejects_failed_or_incomplete_matrix(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory) / "sweep"
            root.mkdir()
            split = Path(directory) / "split.json"
            split.write_text("{}\n", encoding="utf-8")
            self._write_matrix(root, failed=("act", "rgb", 22))

            with self.assertRaisesRegex(ValueError, "sweep cell failed"):
                build_sweep_evidence(root, split, expected_steps=5)

    @staticmethod
    def _write_matrix(root: Path, failed: tuple[str, str, int] | None = None) -> None:
        rows = []
        for modality in ("rgb", "rgb-d"):
            for seed in (11, 22, 33):
                key = ("act", modality, seed)
                rows.append((*key, 1 if key == failed else 0))
                cell = root / f"act-{modality}-seed{seed}"
                checkpoint = cell / "checkpoints" / "000005" / "pretrained_model"
                checkpoint.mkdir(parents=True)
                (root / f"act-{modality}-seed{seed}.log").write_text(
                    "Radeon ROCm smoke\n", encoding="utf-8"
                )
                train_config = {
                    "steps": 5,
                    "seed": seed,
                    "policy": {"type": "act"},
                }
                visual = {"observation.images.overhead_rgb": {}}
                if modality == "rgb-d":
                    visual["observation.images.overhead_depth_rgb"] = {}
                policy_config = {
                    "use_amp": True,
                    "input_features": {
                        "observation.state": {},
                        **visual,
                    },
                }
                (checkpoint / "train_config.json").write_text(
                    json.dumps(train_config), encoding="utf-8"
                )
                (checkpoint / "config.json").write_text(
                    json.dumps(policy_config), encoding="utf-8"
                )
                (checkpoint / "model.safetensors").write_bytes(b"weights")

        with (root / "sweep_status.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(("model", "modality", "seed", "status"))
            writer.writerows(rows)


if __name__ == "__main__":
    unittest.main()
