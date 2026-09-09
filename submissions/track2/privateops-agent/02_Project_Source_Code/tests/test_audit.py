import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from privateops.agent import PrivateOpsAgent
from privateops.models import ToolResult


class AuditTrailTests(unittest.TestCase):
    def _agent_with_entries(self, count=3):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        knowledge = root / "knowledge"
        knowledge.mkdir()
        agent = PrivateOpsAgent(knowledge_dir=knowledge, state_dir=root / "state")
        for index in range(count):
            agent.ask(f"summarize audit item {index}")
        return agent

    def test_delete_removes_exact_entry_and_preserves_other_order(self):
        agent = self._agent_with_entries()
        newest, middle, oldest = agent.audit.load(limit=None)

        deleted = agent.audit.delete(middle["audit_id"])

        self.assertTrue(deleted)
        self.assertEqual(
            [item["audit_id"] for item in agent.audit.load(limit=None)],
            [newest["audit_id"], oldest["audit_id"]],
        )
        self.assertNotIn(middle["audit_id"], str(agent.audit.export()))

    def test_delete_rejects_malformed_id_without_rewriting(self):
        agent = self._agent_with_entries(1)
        before = agent.audit.path.read_bytes()

        with self.assertRaisesRegex(ValueError, "audit ID"):
            agent.audit.delete("../../audit_trail.jsonl")

        self.assertEqual(agent.audit.path.read_bytes(), before)

    def test_delete_unknown_valid_id_returns_false_without_rewriting(self):
        agent = self._agent_with_entries(1)
        before = agent.audit.path.read_bytes()

        self.assertFalse(agent.audit.delete("audit-000000000000"))

        self.assertEqual(agent.audit.path.read_bytes(), before)

    def test_delete_replace_failure_preserves_original_ledger(self):
        agent = self._agent_with_entries(2)
        before = agent.audit.path.read_bytes()
        target = agent.audit.load(limit=None)[0]["audit_id"]

        with patch("privateops.audit.os.replace", side_effect=OSError("replace failed")):
            with self.assertRaisesRegex(OSError, "replace failed"):
                agent.audit.delete(target)

        self.assertEqual(agent.audit.path.read_bytes(), before)

    def test_audit_preserves_observed_startup_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            knowledge = root / "knowledge"
            knowledge.mkdir()
            agent = PrivateOpsAgent(knowledge_dir=knowledge, state_dir=root / "state")

            class FakeInspector:
                def collect(self, name):
                    return ToolResult(name, "completed", "Observed startup state.", {"entries": [{"name": "Updater"}]})

            agent.tools.system_inspector = FakeInspector()
            agent.ask("查看一下本机的开机自启有啥？", response_language="zh-CN")

            entry = agent.audit_trail()[0]
            self.assertEqual(entry["tool_results"][0]["name"], "startup_inventory")
            self.assertEqual(entry["tool_results"][0]["output"]["entries"][0]["name"], "Updater")

    def test_ask_records_audit_entry_with_evidence_and_permission(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            knowledge = root / "knowledge"
            knowledge.mkdir()
            (knowledge / "privacy.md").write_text(
                "PrivateOps exposes evidence, memory, and permission decisions for private AI operations.",
                encoding="utf-8",
            )
            agent = PrivateOpsAgent(knowledge_dir=knowledge, state_dir=root / "state")

            agent.ask("How does PrivateOps expose permission decisions?")
            audit_entries = agent.audit_trail()

            self.assertEqual(len(audit_entries), 1)
            entry = audit_entries[0]
            self.assertIn("permission decisions", entry["prompt"])
            self.assertEqual(entry["permission_level"], "safe")
            self.assertEqual(entry["provider"], "deterministic-local")
            self.assertEqual(entry["evidence_sources"], ["privacy.md"])
            self.assertIn("created_at", entry)
            self.assertTrue(entry["audit_id"].startswith("audit-"))

    def test_audit_trail_is_limited_to_recent_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            knowledge = root / "knowledge"
            knowledge.mkdir()
            agent = PrivateOpsAgent(knowledge_dir=knowledge, state_dir=root / "state")

            for index in range(5):
                agent.ask(f"summarize item {index}")

            audit_entries = agent.audit_trail(limit=3)

            self.assertEqual(len(audit_entries), 3)
            self.assertEqual(
                [entry["prompt"] for entry in audit_entries],
                ["summarize item 4", "summarize item 3", "summarize item 2"],
            )

    def test_export_redacts_secret_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            knowledge = root / "knowledge"
            knowledge.mkdir()
            agent = PrivateOpsAgent(knowledge_dir=knowledge, state_dir=root / "state")

            agent.ask("review password=abc123 without sharing it")
            exported = agent.audit.export()

            self.assertNotIn("abc123", str(exported))
            self.assertEqual(exported["schema_version"], "1.0")


if __name__ == "__main__":
    unittest.main()
