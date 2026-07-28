"""
Integration test for the Orchestrator: full turn simulation using mock tools + mock LLM.
Validates the diagnosis → pushback → verify loop end-to-end.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.orchestrator import Orchestrator
from src.llm import MockLLMClient


class TestOrchestratorIntegration(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.orch = Orchestrator(
            codebase_path=self.tmpdir,
            llm_client=MockLLMClient(),
            mock_tools=True,
            db_path=os.path.join(self.tmpdir, "test_memory.db"),
            audit_log_path=os.path.join(self.tmpdir, "test_audit.jsonl"),
        )
        self.orch.start_session()

    def test_initial_diagnosis_returns_string(self):
        response = self.orch.handle_turn("My HIP matmul kernel is much slower than the CUDA version")
        self.assertIsInstance(response, str)
        self.assertGreater(len(response), 50)

    def test_diagnosis_includes_pattern(self):
        response = self.orch.handle_turn("GPU kernel is slow after HIP port")
        # Should mention something about the bottleneck
        self.assertTrue(
            any(word in response.lower() for word in [
                "memory", "coalescing", "occupancy", "bottleneck", "diagnosis", "pattern"
            ])
        )

    def test_pushback_changes_response(self):
        # First turn: diagnosis
        first = self.orch.handle_turn("My kernel is slow")
        # Pushback turn
        second = self.orch.handle_turn("That's not right — the memory access is fine")
        self.assertNotEqual(first, second)
        # The pushback response uses [Re-examination N] or [Revision N] prefixes
        self.assertTrue(
            any(word in second.lower() for word in [
                "re-examin", "revision", "evidence", "pushback", "data", "round",
                "examination", "original", "diagnosis", "reconsider", "still"
            ])
        )

    def test_pushback_capped_at_max_rounds(self):
        self.orch.handle_turn("My kernel is slow")
        for _ in range(4):  # exceed cap
            response = self.orch.handle_turn("That's still not right")
        # Should eventually offer benchmark fallback
        self.assertTrue(
            any(word in response.lower() for word in ["benchmark", "measure", "both"])
        )

    def test_benchmark_request_handled(self):
        self.orch.handle_turn("My kernel is slow")
        response = self.orch.handle_turn("benchmark it")
        self.assertTrue(
            any(word in response.lower() for word in ["benchmark", "result", "faster", "slower", "speedup"])
        )

    def test_memory_records_attempt(self):
        self.orch.handle_turn("kernel is slow")
        fp = self.orch.session.codebase_fingerprint
        history = self.orch.memory.get_all_for_codebase(fp)
        self.assertGreater(len(history), 0)

    def test_session_history_logged(self):
        self.orch.handle_turn("kernel is slow")
        self.orch.handle_turn("That's not right")
        turns = self.orch.session.history
        self.assertGreaterEqual(len(turns), 4)  # 2 user + 2 agent

    def test_audit_log_populated(self):
        self.orch.handle_turn("kernel is slow")
        log = self.orch.gate.get_audit_log()
        self.assertGreater(len(log), 0)

    def test_rejection_does_not_apply_diff(self):
        self.orch.handle_turn("kernel is slow")
        response = self.orch.handle_turn("reject")
        self.assertIn("nothing", response.lower())


if __name__ == "__main__":
    unittest.main()
