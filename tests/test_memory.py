"""
Unit tests for the MemoryStore and PermissionGate.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.memory.store import MemoryStore, OptimizationAttempt, fingerprint_codebase
from src.permission_gate import PermissionGate, ActionType, ApprovalStatus


class TestMemoryStore(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test_memory.db")
        self.store = MemoryStore(db_path=self.db_path)

    def tearDown(self):
        self.store.close()

    def _make_attempt(self, pattern="memory_coalescing", fingerprint="abc123"):
        return OptimizationAttempt(
            codebase_fingerprint=fingerprint,
            pattern_type=pattern,
            hypothesis="Test hypothesis for memory coalescing.",
            diff_summary="Transpose input tensor before kernel.",
        )

    def test_record_and_retrieve(self):
        attempt = self._make_attempt()
        attempt_id = self.store.record_attempt(attempt)
        self.assertIsNotNone(attempt_id)
        self.assertGreater(attempt_id, 0)

        retrieved = self.store.get_attempt_by_id(attempt_id)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved["pattern_type"], "memory_coalescing")
        self.assertEqual(retrieved["codebase_fingerprint"], "abc123")

    def test_update_outcome(self):
        attempt_id = self.store.record_attempt(self._make_attempt())
        self.store.update_outcome(attempt_id, outcome="accepted", speedup_ratio=1.87, notes="18.7ms → 10ms")

        retrieved = self.store.get_attempt_by_id(attempt_id)
        self.assertEqual(retrieved["outcome"], "accepted")
        self.assertAlmostEqual(retrieved["measured_speedup_ratio"], 1.87, places=2)

    def test_get_history_for_pattern(self):
        for i in range(3):
            a = self._make_attempt(fingerprint="fp1")
            self.store.record_attempt(a)

        # Different fingerprint — should not appear
        self.store.record_attempt(self._make_attempt(fingerprint="fp2"))

        history = self.store.get_history_for_pattern("memory_coalescing", "fp1")
        self.assertEqual(len(history), 3)

    def test_get_all_for_codebase(self):
        for pattern in ["memory_coalescing", "lds_bank_conflict", "occupancy_limiter"]:
            self.store.record_attempt(self._make_attempt(pattern=pattern, fingerprint="fp_all"))

        all_attempts = self.store.get_all_for_codebase("fp_all")
        self.assertEqual(len(all_attempts), 3)

    def test_summarize_history_empty(self):
        summary = self.store.summarize_history("nonexistent_fp")
        self.assertIn("No prior", summary)

    def test_summarize_history_with_data(self):
        self.store.record_attempt(self._make_attempt())
        summary = self.store.summarize_history("abc123")
        self.assertIn("memory_coalescing", summary)
        self.assertIn("1 total", summary)

    def test_fingerprint_file(self):
        # Create a temp file and fingerprint it
        fpath = os.path.join(self.tmpdir, "workload.py")
        with open(fpath, "w") as f:
            f.write("import torch\n")
        fp = fingerprint_codebase(fpath)
        self.assertEqual(len(fp), 16)  # 16-char hex

    def test_fingerprint_directory(self):
        # Create a temp directory with a couple of .py files
        for name in ["a.py", "b.py"]:
            with open(os.path.join(self.tmpdir, name), "w") as f:
                f.write(f"# {name}\n")
        fp = fingerprint_codebase(self.tmpdir)
        self.assertEqual(len(fp), 16)


class TestPermissionGate(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.audit_path = os.path.join(self.tmpdir, "audit.jsonl")
        self.gate = PermissionGate(audit_log_path=self.audit_path)

    def test_can_read_by_default(self):
        self.assertTrue(self.gate.can_read("corpus/hip_guide.md"))
        self.assertTrue(self.gate.can_read("/any/path/script.py"))

    def test_can_propose_diff_always(self):
        self.assertTrue(self.gate.can_propose_diff())

    def test_cannot_save_diff_without_approval(self):
        self.assertFalse(self.gate.can_save_diff())

    def test_save_diff_requires_confirmation(self):
        self.assertTrue(self.gate.requires_confirmation(ActionType.SAVE_DIFF))

    def test_audit_log_written(self):
        self.gate.log_action(ActionType.READ_SMI, "system", ApprovalStatus.AUTO_ALLOWED)
        self.gate.log_action(ActionType.PROPOSE_DIFF, "workload.py", ApprovalStatus.AUTO_ALLOWED)

        log = self.gate.get_audit_log()
        self.assertEqual(len(log), 2)
        self.assertTrue(os.path.exists(self.audit_path))

    def test_audit_log_persisted_to_disk(self):
        self.gate.log_action(ActionType.READ_SMI, "gpu0", ApprovalStatus.AUTO_ALLOWED)
        disk_log = self.gate.load_audit_log_from_disk()
        self.assertEqual(len(disk_log), 1)
        self.assertEqual(disk_log[0]["action_type"], ActionType.READ_SMI.value)

    def test_request_and_approve(self):
        entry = self.gate.request_approval(ActionType.SAVE_DIFF, "workload.patch", "save optimized diff")
        self.assertEqual(entry.status, ApprovalStatus.PENDING.value)

        self.gate.approve_action(entry)
        self.assertEqual(entry.status, ApprovalStatus.APPROVED.value)

    def test_request_and_reject(self):
        entry = self.gate.request_approval(ActionType.SAVE_DIFF, "workload.patch", "test")
        self.gate.reject_action(entry)
        self.assertEqual(entry.status, ApprovalStatus.REJECTED.value)


if __name__ == "__main__":
    unittest.main()
