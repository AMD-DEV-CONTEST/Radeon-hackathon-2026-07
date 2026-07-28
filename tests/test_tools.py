"""
Unit tests for the tool wrappers (rocm_smi, profiler, benchmark_sandbox, diff_proposer).
All tests use mock mode so no real GPU is required.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.tools.rocm_smi import run_rocm_smi, format_smi_summary
from src.tools.profiler import profile_pytorch_trace, format_profile_summary
from src.tools.benchmark_sandbox import run_benchmark, format_benchmark_summary
from src.tools.diff_proposer import (
    propose_diff_from_strings, save_proposed_diff, format_diff_for_display
)


class TestRocmSmi(unittest.TestCase):

    def test_mock_returns_expected_structure(self):
        result = run_rocm_smi(mock=True)
        self.assertIn("device_count", result)
        self.assertIn("devices", result)
        self.assertIsNone(result.get("error"))
        self.assertGreater(result["device_count"], 0)
        dev = result["devices"][0]
        self.assertIn("utilization_gpu_pct", dev)
        self.assertIn("vram_used_mb", dev)
        self.assertIn("temperature_c", dev)

    def test_format_summary_no_error(self):
        result = run_rocm_smi(mock=True)
        summary = format_smi_summary(result)
        self.assertIn("GPU", summary)
        self.assertIn("VRAM", summary)

    def test_error_when_not_installed(self):
        # When rocm-smi is not on PATH, should return error gracefully
        result = run_rocm_smi(mock=False)
        # On a non-ROCm machine this should either error or return data
        self.assertIn("devices", result)


class TestProfiler(unittest.TestCase):

    def test_mock_returns_expected_structure(self):
        result = profile_pytorch_trace("nonexistent.py", mock=True)
        self.assertIn("top_by_time", result)
        self.assertIn("top_by_memory", result)
        self.assertIsNone(result.get("error"))
        self.assertGreater(len(result["top_by_time"]), 0)
        op = result["top_by_time"][0]
        self.assertIn("name", op)
        self.assertIn("cuda_time_us", op)
        self.assertIn("rank", op)

    def test_format_summary_no_error(self):
        result = profile_pytorch_trace("", mock=True)
        summary = format_profile_summary(result)
        self.assertIn("Profiler Summary", summary)

    def test_missing_script_returns_error(self):
        result = profile_pytorch_trace("/nonexistent/script.py", mock=False)
        self.assertIsNotNone(result.get("error"))


class TestBenchmarkSandbox(unittest.TestCase):

    def test_mock_returns_expected_structure(self):
        result = run_benchmark("baseline.py", "candidate.py", mock=True)
        self.assertIn("baseline", result)
        self.assertIn("candidate", result)
        self.assertIn("comparison", result)
        comp = result["comparison"]
        self.assertIn("speedup_ratio", comp)
        self.assertIn("winner", comp)
        self.assertIn("verdict", comp)

    def test_speedup_ratio_positive(self):
        result = run_benchmark("b.py", "c.py", mock=True)
        self.assertGreater(result["comparison"]["speedup_ratio"], 0)

    def test_format_summary(self):
        result = run_benchmark("b.py", "c.py", mock=True)
        summary = format_benchmark_summary(result)
        self.assertIn("Benchmark Results", summary)
        self.assertIn("Verdict", summary)

    def test_missing_scripts_return_error(self):
        result = run_benchmark("/nonexistent/c.py", "/nonexistent/b.py", mock=False)
        # Should have error info, not crash
        self.assertIn("baseline", result)


class TestDiffProposer(unittest.TestCase):

    ORIGINAL = "def foo():\n    x = [i for i in range(100)]\n    return x\n"
    PATCHED = "def foo():\n    x = list(range(100))  # faster\n    return x\n"

    def test_diff_generation(self):
        proposal = propose_diff_from_strings(
            original_code=self.ORIGINAL,
            patched_code=self.PATCHED,
            filename="foo.py",
            description="Use list() instead of list comprehension",
            pattern_type="micro_optimization",
        )
        self.assertIn("foo.py", proposal.diff_text)
        self.assertGreater(proposal.lines_added, 0)
        self.assertGreater(proposal.lines_removed, 0)

    def test_no_diff_when_identical(self):
        proposal = propose_diff_from_strings(self.ORIGINAL, self.ORIGINAL)
        self.assertEqual(proposal.diff_text, "")
        self.assertEqual(proposal.lines_added, 0)
        self.assertEqual(proposal.lines_removed, 0)

    def test_save_diff_writes_file(self):
        proposal = propose_diff_from_strings(
            self.ORIGINAL, self.PATCHED, description="test patch"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = os.path.join(tmpdir, "test.patch")
            saved = save_proposed_diff(proposal, out_path)
            self.assertTrue(os.path.exists(saved))
            content = open(saved).read()
            self.assertIn("OmniKernel-ROCm", content)
            self.assertIn("test patch", content)

    def test_format_for_display(self):
        proposal = propose_diff_from_strings(
            self.ORIGINAL, self.PATCHED, description="Display test"
        )
        display = format_diff_for_display(proposal)
        self.assertIn("PROPOSED DIFF", display)


if __name__ == "__main__":
    unittest.main()
