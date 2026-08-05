import csv
import io
import json
import tempfile
import unittest
import subprocess
import sys
from pathlib import Path

from privateops.submission_evidence import build_submission_evidence, render_submission_csv


class SubmissionEvidenceTests(unittest.TestCase):
    def test_sync_script_runs_directly_from_repository_root(self):
        root = Path(__file__).resolve().parent.parent

        result = subprocess.run(
            [sys.executable, "scripts/sync_verified_evidence.py"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Synchronized 1 verified Radeon run.", result.stdout)

    def _root(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        evidence = root / "submission" / "evidence" / "rocm-verified"
        evidence.mkdir(parents=True)
        (evidence / "radeon-benchmark-run.json").write_text(
            json.dumps(
                {
                    "run_id": "bench-996f4f2233a5",
                    "created_at": "2026-08-03T12:53:02.309280+00:00",
                    "label": "Radeon Cloud verified run",
                    "provider_mode": "rocm-local",
                    "verified": True,
                    "gpu_name": "AMD Radeon Graphics",
                    "rocm_version": "7.2.1",
                    "model_name": "Qwen/Qwen2.5-7B-Instruct",
                    "rocminfo_excerpt": "Marketing Name: AMD Radeon Graphics\nName: gfx1100",
                    "latency_ms": 1511.072,
                    "tokens_per_second": 32.427,
                    "prompt_tokens": 45,
                    "completion_tokens": 49,
                    "notes": "Measured end-to-end through the loopback OpenAI-compatible endpoint.",
                }
            ),
            encoding="utf-8",
        )
        (evidence / "rocm-agent-live-latency-zh.txt").write_text("18.384639\n", encoding="utf-8")
        return root

    def test_builds_verified_record_from_immutable_sources(self):
        payload = build_submission_evidence(self._root())

        self.assertEqual(payload["status"], "verified_radeon_rocm_capture")
        self.assertEqual(payload["source"], "evidence/rocm-verified/radeon-benchmark-run.json")
        self.assertEqual(len(payload["runs"]), 1)
        run = payload["runs"][0]
        self.assertEqual(run["run_id"], "bench-996f4f2233a5")
        self.assertEqual(run["gpu_name"], "AMD Radeon Graphics")
        self.assertEqual(run["rocm_version"], "7.2.1")
        self.assertEqual(run["model_name"], "Qwen/Qwen2.5-7B-Instruct")
        self.assertEqual(run["latency_ms"], 1511.072)
        self.assertEqual(run["tokens_per_second"], 32.427)
        self.assertEqual(run["prompt_tokens"], 45)
        self.assertEqual(run["completion_tokens"], 49)
        self.assertEqual(run["agent_latency_ms"], 18384.639)
        self.assertTrue(run["verified"])

    def test_csv_contains_one_verified_run_and_agent_latency(self):
        payload = build_submission_evidence(self._root())

        rows = list(csv.DictReader(io.StringIO(render_submission_csv(payload))))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["verified"], "True")
        self.assertEqual(rows[0]["provider_mode"], "rocm-local")
        self.assertEqual(rows[0]["latency_ms"], "1511.072")
        self.assertEqual(rows[0]["tokens_per_second"], "32.427")
        self.assertEqual(rows[0]["agent_latency_ms"], "18384.639")


if __name__ == "__main__":
    unittest.main()
