import json
import tempfile
import unittest
from pathlib import Path

from privateops.radeon_evidence import RadeonEvidenceStore


class RadeonEvidenceStoreTests(unittest.TestCase):
    def _evidence_root(self, root: Path, provider_mode: str = "rocm-local") -> Path:
        evidence = root / "evidence"
        verified = evidence / "rocm-verified"
        verified.mkdir(parents=True)
        (evidence / "README.md").write_text(
            "Captured from Radeon Cloud instance `u-test-verified`.\n",
            encoding="utf-8",
        )
        (verified / "radeon-benchmark-run.json").write_text(
            json.dumps(
                {
                    "run_id": "bench-test",
                    "created_at": "2026-08-03T12:53:02+00:00",
                    "verified": True,
                    "provider_mode": provider_mode,
                    "gpu_name": "AMD Radeon Graphics",
                    "rocm_version": "7.2.1",
                    "model_name": "Qwen/Qwen2.5-7B-Instruct",
                    "latency_ms": 1511.072,
                    "tokens_per_second": 32.427,
                    "prompt_tokens": 45,
                    "completion_tokens": 49,
                }
            ),
            encoding="utf-8",
        )
        (verified / "rocm-verified-diagnostics.txt").write_text(
            "\n".join(
                [
                    "PrivateOps Radeon Cloud verified evidence",
                    "2026-08-03T12:55:14+00:00",
                    "GPU[0] : VRAM Total Memory (B): 51522830336",
                    "GPU[0] : GFX Version: gfx1100",
                    "torch=2.9.1+gitff65f5b",
                    "hip=7.2.53211-e1a6bc5663",
                    "=== vllm ===",
                    "0.16.1.dev0+rocm721",
                    "=== app status ===",
                    json.dumps(
                        {
                            "provider_mode": provider_mode,
                            "model_endpoint": "http://127.0.0.1:8000/v1/chat/completions",
                            "model_name": "Qwen/Qwen2.5-7B-Instruct",
                            "provider": "openai-compatible-rocm",
                            "core_inference_location": "same-instance loopback",
                        }
                    ),
                    "=== benchmark ===",
                ]
            ),
            encoding="utf-8",
        )
        (verified / "rocm-agent-live-latency-zh.txt").write_text("18.384639\n", encoding="utf-8")
        (verified / "rocm-agent-live-response-zh.json").write_text("{}", encoding="utf-8")
        (verified / "rocm-audit-export.json").write_text("{}", encoding="utf-8")
        return evidence

    def test_summary_returns_cross_checked_verified_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary = RadeonEvidenceStore(self._evidence_root(Path(tmp))).summary()

        self.assertTrue(summary["available"])
        self.assertEqual(summary["instance_id"], "u-test-verified")
        self.assertEqual(summary["gpu"], {
            "name": "AMD Radeon Graphics",
            "architecture": "gfx1100",
            "vram_bytes": 51522830336,
        })
        self.assertEqual(summary["runtime"]["rocm_version"], "7.2.1")
        self.assertEqual(summary["runtime"]["pytorch_version"], "2.9.1+gitff65f5b")
        self.assertEqual(summary["runtime"]["vllm_version"], "0.16.1.dev0+rocm721")
        self.assertEqual(summary["model"]["endpoint"], "http://127.0.0.1:8000/v1/chat/completions")
        self.assertEqual(summary["model"]["location"], "same-instance loopback")
        self.assertEqual(summary["metrics"]["latency_ms"], 1511.072)
        self.assertEqual(summary["metrics"]["tokens_per_second"], 32.427)
        self.assertEqual(summary["metrics"]["agent_latency_ms"], 18384.639)
        self.assertGreaterEqual(len(summary["sources"]), 5)
        self.assertTrue(all(not Path(item["path"]).is_absolute() for item in summary["sources"]))

    def test_missing_evidence_never_claims_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary = RadeonEvidenceStore(Path(tmp) / "missing").summary()

        self.assertEqual(summary, {"available": False, "reason": "evidence_missing"})

    def test_inconsistent_provider_mode_never_claims_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary = RadeonEvidenceStore(
                self._evidence_root(Path(tmp), provider_mode="development")
            ).summary()

        self.assertEqual(summary, {"available": False, "reason": "evidence_inconsistent"})


if __name__ == "__main__":
    unittest.main()
