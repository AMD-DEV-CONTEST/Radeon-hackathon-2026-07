import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from incident_commander.analyzer import AIIncidentAnalyzer, IncidentAnalyzer
from incident_commander.llm import OpenAICompatibleClient
from incident_commander.server import runtime_status


class RuntimeStatusTests(unittest.TestCase):
    def test_offline_runtime_exposes_safe_fallback(self) -> None:
        status = runtime_status(IncidentAnalyzer())
        self.assertEqual(status["mode"], "offline-safe")
        self.assertEqual(status["safety_fallback"], "active")

    def test_ai_runtime_requires_matching_radeon_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory) / "runtime-evidence.json"
            evidence.write_text(
                json.dumps(
                    {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "model": "qwen3-8b",
                        "rocm_version": "7.2.1",
                        "gpu_architecture": "gfx1100",
                        "vram_mb": 49136,
                        "compute_units": 96,
                        "vllm_version": "0.16.1.dev",
                    }
                ),
                encoding="utf-8",
            )
            client = OpenAICompatibleClient(base_url="http://127.0.0.1:8000/v1", model="qwen3-8b")
            with patch.dict(os.environ, {"LIC_RUNTIME_EVIDENCE": str(evidence)}):
                status = runtime_status(AIIncidentAnalyzer(client))
        self.assertEqual(status["mode"], "local-radeon")
        self.assertEqual(status["model"], "qwen3-8b")
        self.assertEqual(status["safety_fallback"], "deterministic-baseline")
        self.assertEqual(status["runtime_evidence"]["gpu_architecture"], "gfx1100")

    def test_local_endpoint_without_evidence_is_unverified(self) -> None:
        client = OpenAICompatibleClient(base_url="http://127.0.0.1:8000/v1", model="qwen3-8b")
        with patch.dict(os.environ, {"LIC_RUNTIME_EVIDENCE": ""}):
            status = runtime_status(AIIncidentAnalyzer(client))
        self.assertEqual(status["mode"], "local-unverified")

    def test_ai_runtime_distinguishes_remote_api(self) -> None:
        client = OpenAICompatibleClient(base_url="https://example.com/v1", model="hosted-model")
        status = runtime_status(AIIncidentAnalyzer(client))
        self.assertEqual(status["mode"], "remote-api")


if __name__ == "__main__":
    unittest.main()
