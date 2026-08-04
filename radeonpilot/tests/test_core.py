"""Unit tests for RadeonPilot deterministic paths (run without a GPU)."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

os.environ["RADEONPILOT_MODE"] = "demo"

from radeonpilot import tools  # noqa: E402
from radeonpilot.memory import OpsMemory  # noqa: E402
from radeonpilot.orchestrator import OpsOrchestrator  # noqa: E402
from radeonpilot.rag import LocalRAG, tokenize  # noqa: E402


class ToolsTest(unittest.TestCase):
    def test_demo_environment_is_labelled_synthetic(self):
        result = tools.gpu_environment()
        self.assertTrue(result.ok)
        self.assertEqual(result.data["mode"], "demo")
        self.assertIn("SYNTHETIC", result.data["label"])

    def test_permission_gate_blocks_dangerous_action_for_operator(self):
        result = tools.permission_check("restart_endpoint", role="operator")
        self.assertTrue(result.ok)
        self.assertFalse(result.data["allowed"])

    def test_permission_gate_allows_dangerous_action_for_sre(self):
        result = tools.permission_check("restart_endpoint", role="sre")
        self.assertTrue(result.data["allowed"])

    def test_permission_gate_allows_safe_action(self):
        result = tools.permission_check("read_telemetry", role="operator")
        self.assertTrue(result.data["allowed"])

    def test_endpoint_status_reports_unreachable_without_server(self):
        result = tools.endpoint_status("http://127.0.0.1:1/v1")
        self.assertTrue(result.ok)
        self.assertFalse(result.data["reachable"])


class RagTest(unittest.TestCase):
    def test_tokenize_lowercases(self):
        self.assertEqual(tokenize("ROCm vLLM"), ["rocm", "vllm"])

    def test_search_returns_evidence(self):
        knowledge = Path(__file__).resolve().parent.parent / "data" / "knowledge"
        rag = LocalRAG(knowledge)
        results = rag.search("prefix caching vllm", limit=3)
        self.assertGreater(len(results), 0)
        self.assertTrue(all(item.source.endswith(".md") for item in results))
        self.assertTrue(all(item.metadata.get("document_id") for item in results))

    def test_empty_corpus_returns_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            rag = LocalRAG(tmp)
            self.assertEqual(rag.search("anything"), [])


class MemoryTest(unittest.TestCase):
    def test_turns_snapshots_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = OpsMemory(Path(tmp) / "m.sqlite3")
            session = "s1"
            turn = memory.next_turn(session)
            self.assertEqual(turn, 1)
            memory.add_turn(session, turn, "user", "hello")
            memory.snapshot(session, "environment", {"gpu": "gfx1100"})
            memory.audit(session, "test_event", "detail")
            self.assertEqual(len(memory.history(session)), 1)
            self.assertEqual(memory.latest_snapshot(session, "environment")["gpu"], "gfx1100")
            events = list(memory.audit_tail())
            self.assertTrue(any(event["event"] == "test_event" for event in events))
            memory.close()


class OrchestratorTest(unittest.TestCase):
    def test_demo_run_produces_labelled_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            knowledge = Path(__file__).resolve().parent.parent / "data" / "knowledge"
            orch = OpsOrchestrator(knowledge_path=knowledge, db_path=Path(tmp) / "o.sqlite3")
            self.assertEqual(orch.mode, "demo")
            run = orch.run("diagnose the endpoint")
            self.assertEqual(run.mode, "demo")
            self.assertIn("DEMO", run.summary)
            self.assertEqual(len(run.reports), 4)
            self.assertTrue(run.action_plan)
            self.assertFalse(run.runtime.get("radeon_attested"))
            orch.memory.close()

    def test_demo_run_persists_multi_turn_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            knowledge = Path(__file__).resolve().parent.parent / "data" / "knowledge"
            orch = OpsOrchestrator(knowledge_path=knowledge, db_path=Path(tmp) / "o.sqlite3")
            first = orch.run("first question")
            second = orch.run("follow-up question", session_id=first.session_id)
            self.assertEqual(first.session_id, second.session_id)
            history = orch.memory.history(first.session_id)
            self.assertGreaterEqual(len(history), 4)
            orch.memory.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
