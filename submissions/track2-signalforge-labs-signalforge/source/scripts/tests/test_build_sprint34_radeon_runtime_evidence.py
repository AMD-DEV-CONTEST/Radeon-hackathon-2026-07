import argparse
import copy
import json
import tempfile
import unittest
from pathlib import Path

from scripts.build_sprint34_radeon_runtime_evidence import build


ROOT = Path(__file__).resolve().parents[2]


class Sprint34RadeonRuntimeEvidenceTests(unittest.TestCase):
    def args(self, root: Path) -> argparse.Namespace:
        return argparse.Namespace(
            local_journey=root / "evidence/dashboard-radeon-local-journey.json",
            local_startup=root / "evidence/runs/sprint34/local-startup.json",
            local_timing=root / "evidence/runs/sprint34/local-journey-timing.json",
            local_telemetry=root / "evidence/runs/sprint34/local-telemetry-summary.json",
            hybrid_journey=root / "evidence/dashboard-radeon-hybrid-journey.json",
            hybrid_startup=root / "evidence/runs/sprint34/hybrid-startup.json",
            hybrid_timing=root / "evidence/runs/sprint34/hybrid-journey-timing.json",
            hybrid_telemetry=root / "evidence/runs/sprint34/hybrid-telemetry-summary.json",
            failure_matrix=root / "evidence/runs/sprint34/failure-matrix.json",
            runtime_profile=root / "configs/runtime/gemma4-26b-q4-llama-rocm.json",
            source_identity="working-tree-pre-freeze",
            output=root / "unused.json",
            check=False,
        )

    def test_current_sanitized_evidence_passes(self) -> None:
        report = build(self.args(ROOT))
        self.assertEqual(report["decision"]["status"], "passed")
        self.assertEqual(
            report["journeys"]["local_only"]["providers"],
            ["local-rocm"],
        )
        self.assertEqual(
            report["journeys"]["hybrid_radeon_api"]["providers"],
            ["local-rocm", "radeon-vllm"],
        )
        self.assertEqual(report["failure_recovery"]["status"], "passed")
        self.assertFalse(report["privacy"]["sealed_population_opened"])

    def test_hybrid_without_radeon_provider_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            hybrid = json.loads(
                (ROOT / "evidence/dashboard-radeon-hybrid-journey.json").read_text()
            )
            hybrid["intelligence"]["providers"] = ["local-rocm"]
            path = root / "hybrid.json"
            path.write_text(json.dumps(hybrid))
            args = copy.copy(self.args(ROOT))
            args.hybrid_journey = path
            with self.assertRaisesRegex(ValueError, "both authorized providers"):
                build(args)


if __name__ == "__main__":
    unittest.main()
