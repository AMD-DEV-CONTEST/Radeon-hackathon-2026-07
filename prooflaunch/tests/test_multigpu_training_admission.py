from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERIFIER = ROOT / "scripts" / "verify_multigpu_training_admission.py"


def _make_run(
    root: Path,
    name: str,
    *,
    world_size: int,
    parallelism: str,
    throughput: float,
    eval_loss: float,
    seed: int = 42,
) -> Path:
    run = root / name
    receipts = run / "distributed-ranks"
    receipts.mkdir(parents=True)
    receipt_index = []
    for rank in range(world_size):
        receipt_path = receipts / f"rank-{rank:04d}.json"
        receipt_path.write_text(
            json.dumps(
                {
                    "global_rank": rank,
                    "training_complete": True,
                }
            ),
            encoding="utf-8",
        )
        raw = receipt_path.read_bytes()
        receipt_index.append(
            {
                "rank": rank,
                "path": str(receipt_path),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    manifest = {
        "schema": "ProofLaunchGemma4EmotionDistributedTrainingV1",
        "model": {"id": "m", "revision": "a" * 40},
        "dataset": {
            "id": "d",
            "revision": "b" * 40,
            "train_count": 100,
            "validation_count": 20,
        },
        "hardware": {
            "world_size": world_size,
            "parallelism": parallelism,
            "rank_receipts": receipt_index,
        },
        "optimization": {
            "run_profile": "candidate",
            "seed": seed,
            "dtype": "bfloat16",
            "attention": "sdpa",
            "effective_global_batch_size": 16,
            "lora_rank": 16,
            "lora_target_count": 24,
        },
        "train_metrics": {
            "train_samples_per_second": throughput,
        },
        "final_validation_metrics": {"eval_loss": eval_loss},
    }
    path = run / "distributed-training-manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


class MultiGpuTrainingAdmissionTests(unittest.TestCase):
    def _command(
        self,
        single: Path,
        multi: list[Path],
        output: Path,
    ) -> list[str]:
        command = [
            sys.executable,
            str(VERIFIER),
            "--single-manifest",
            str(single),
        ]
        for path in multi:
            command.extend(["--multi-manifest", str(path)])
        command.extend(["--output", str(output)])
        return command

    def test_admits_equivalent_stable_speedup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            single = _make_run(
                root,
                "single",
                world_size=1,
                parallelism="single",
                throughput=10.0,
                eval_loss=1.0,
            )
            multi = [
                _make_run(
                    root,
                    f"multi-{index}",
                    world_size=2,
                    parallelism="ddp",
                    throughput=16.0 + index / 10,
                    eval_loss=1.01,
                )
                for index in range(3)
            ]
            output = root / "admission.json"
            result = subprocess.run(
                self._command(single, multi, output),
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                json.loads(output.read_text())["status"],
                "passed",
            )

    def test_blocks_comparison_drift_and_slowdown(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            single = _make_run(
                root,
                "single",
                world_size=1,
                parallelism="single",
                throughput=10.0,
                eval_loss=1.0,
            )
            multi = [
                _make_run(
                    root,
                    f"multi-{index}",
                    world_size=2,
                    parallelism="ddp",
                    throughput=11.0,
                    eval_loss=1.1,
                    seed=99 if index == 2 else 42,
                )
                for index in range(3)
            ]
            output = root / "admission.json"
            result = subprocess.run(
                self._command(single, multi, output),
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 1)
            report = json.loads(output.read_text())
            self.assertEqual(report["status"], "blocked")
            self.assertIn("comparison_contract_drift", report["blockers"])
            self.assertIn("speedup_below_floor", report["blockers"])
            self.assertIn("eval_loss_regression", report["blockers"])


if __name__ == "__main__":
    unittest.main()
