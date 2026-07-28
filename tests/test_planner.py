"""
Unit tests for the Planner: diagnose, hypothesize, verify, and reexamine.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.planner import (
    Planner, Hypothesis, Evidence,
    BottleneckPattern, ConfidenceLevel
)
from src.llm import MockLLMClient


MOCK_SMI_DATA = {
    "device_count": 1,
    "devices": [{
        "id": 0, "name": "AMD Radeon (mock)",
        "utilization_gpu_pct": 38,
        "utilization_mem_pct": 70,
        "vram_total_mb": 24576,
        "vram_used_mb": 16000,
        "temperature_c": 72,
        "power_draw_w": 290.0,
        "clock_gpu_mhz": 2300,
        "clock_mem_mhz": 2400,
    }],
    "error": None,
}

MOCK_PROFILE_DATA = {
    "top_by_time": [
        {"rank": 1, "name": "aten::copy_", "cpu_time_us": 3200, "cuda_time_us": 42000, "cuda_memory_usage_kb": 4096, "count": 64},
        {"rank": 2, "name": "aten::mul", "cpu_time_us": 800, "cuda_time_us": 8000, "cuda_memory_usage_kb": 2048, "count": 8},
    ],
    "top_by_memory": [
        {"rank": 1, "name": "aten::copy_", "cuda_time_us": 42000, "cuda_memory_usage_kb": 4096, "count": 64},
    ],
    "total_cpu_time_us": 5000,
    "total_cuda_time_us": 52000,
    "error": None,
}

MOCK_BENCH_ACCEPTED = {
    "comparison": {
        "speedup_ratio": 2.1,
        "latency_delta_ms": -12.4,
        "winner": "candidate",
        "verdict": "candidate is 2.10x faster (12.4ms improvement)",
    },
    "error": None,
}

MOCK_BENCH_REGRESSED = {
    "comparison": {
        "speedup_ratio": 0.82,
        "latency_delta_ms": 4.1,
        "winner": "baseline",
        "verdict": "candidate is 1.22x SLOWER (4.1ms regression)",
    },
    "error": None,
}


class TestPlannerHeuristicOnly(unittest.TestCase):
    """Tests for the heuristic-only path (no LLM required)."""

    def setUp(self):
        self.planner = Planner(llm_client=None)

    def test_diagnose_returns_hypothesis(self):
        h = self.planner.diagnose(
            smi_data=MOCK_SMI_DATA,
            profile_data=MOCK_PROFILE_DATA,
        )
        self.assertIsInstance(h, Hypothesis)
        self.assertIsNotNone(h.pattern_type)
        self.assertIsNotNone(h.diagnosis)
        self.assertIsNotNone(h.proposed_fix)
        self.assertIsNotNone(h.confidence)

    def test_diagnose_low_utilization_detects_memory_bound(self):
        # 38% GPU utilization → should lean towards memory-bound
        h = self.planner.diagnose(smi_data=MOCK_SMI_DATA, profile_data=None)
        self.assertEqual(h.pattern_type, BottleneckPattern.MEMORY_BOUND.value)

    def test_diagnose_includes_evidence(self):
        h = self.planner.diagnose(smi_data=MOCK_SMI_DATA, profile_data=MOCK_PROFILE_DATA)
        self.assertGreater(len(h.evidence), 0)
        sources = [e.source for e in h.evidence]
        self.assertIn("rocm-smi", sources)
        self.assertIn("torch.profiler", sources)

    def test_hypothesize_does_not_crash(self):
        h = self.planner.diagnose(smi_data=MOCK_SMI_DATA)
        h2 = self.planner.hypothesize(h)
        self.assertIsInstance(h2, Hypothesis)

    def test_verify_accepted(self):
        h = self.planner.diagnose(smi_data=MOCK_SMI_DATA)
        h_verified = self.planner.verify(h, MOCK_BENCH_ACCEPTED)
        self.assertTrue(h_verified.verified)
        self.assertIn("CONFIRMED", h_verified.verification_notes)

    def test_verify_regressed(self):
        h = self.planner.diagnose(smi_data=MOCK_SMI_DATA)
        h_verified = self.planner.verify(h, MOCK_BENCH_REGRESSED)
        self.assertFalse(h_verified.verified)
        self.assertIn("REGRESS", h_verified.verification_notes)

    def test_reexamine_returns_tuple(self):
        h = self.planner.diagnose(smi_data=MOCK_SMI_DATA)
        revised, text = self.planner.reexamine(
            hypothesis=h,
            pushback="That doesn't seem right",
            smi_data=MOCK_SMI_DATA,
            profile_data=MOCK_PROFILE_DATA,
        )
        self.assertIsInstance(revised, Hypothesis)
        self.assertIsInstance(text, str)
        self.assertGreater(len(text), 20)

    def test_hypothesis_to_prompt_text(self):
        h = self.planner.diagnose(smi_data=MOCK_SMI_DATA)
        text = h.to_prompt_text()
        self.assertIn("Diagnosis", text)
        self.assertIn("Pattern", text)
        self.assertIn("Proposed Fix", text)


class TestPlannerWithMockLLM(unittest.TestCase):
    """Tests for the LLM-backed path using MockLLMClient."""

    def setUp(self):
        self.planner = Planner(llm_client=MockLLMClient())

    def test_llm_diagnose_returns_hypothesis(self):
        h = self.planner.diagnose(
            smi_data=MOCK_SMI_DATA,
            profile_data=MOCK_PROFILE_DATA,
            rag_context="Memory coalescing patterns...",
            user_description="My HIP kernel is 3x slower",
        )
        self.assertIsInstance(h, Hypothesis)
        self.assertIsNotNone(h.pattern_type)

    def test_llm_reexamine_returns_revised(self):
        h = self.planner.diagnose(smi_data=MOCK_SMI_DATA, profile_data=MOCK_PROFILE_DATA)
        revised, response = self.planner.reexamine(
            hypothesis=h,
            pushback="I already have contiguous tensors",
            smi_data=MOCK_SMI_DATA,
            profile_data=MOCK_PROFILE_DATA,
        )
        self.assertIsInstance(revised, Hypothesis)
        self.assertGreater(len(response), 10)


class TestEvidenceExtraction(unittest.TestCase):

    def setUp(self):
        self.planner = Planner(llm_client=None)

    def test_extracts_smi_evidence(self):
        evidence = self.planner._extract_evidence(smi_data=MOCK_SMI_DATA, profile_data=None)
        sources = [e.source for e in evidence]
        self.assertIn("rocm-smi", sources)
        obs = [e.observation for e in evidence]
        self.assertTrue(any("38%" in o for o in obs))

    def test_extracts_profile_evidence(self):
        evidence = self.planner._extract_evidence(smi_data=None, profile_data=MOCK_PROFILE_DATA)
        sources = [e.source for e in evidence]
        self.assertIn("torch.profiler", sources)

    def test_empty_data_returns_empty_list(self):
        evidence = self.planner._extract_evidence(smi_data=None, profile_data=None)
        self.assertEqual(len(evidence), 0)

    def test_error_data_skipped(self):
        bad_smi = {"device_count": 0, "devices": [], "error": "not found"}
        evidence = self.planner._extract_evidence(smi_data=bad_smi, profile_data=None)
        self.assertEqual(len(evidence), 0)


if __name__ == "__main__":
    unittest.main()
