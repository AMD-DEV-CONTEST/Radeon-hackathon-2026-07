from __future__ import annotations

import copy
from pathlib import Path
import tempfile
import unittest

from prooflaunch_remix.gtm_100_todo_execution_ledger_v2 import (
    GTM100TodoExecutionLedgerError,
    compile_todo_execution_ledger,
    parse_todo_spec,
    verify_todo_execution_ledger,
)


def _spec() -> str:
    return "\n".join(f"T{value:03d} Requirement {value}" for value in range(1, 101))


class GTM100TodoExecutionLedgerV2Tests(unittest.TestCase):
    def test_exact_sequence_is_required(self) -> None:
        self.assertEqual(len(parse_todo_spec(_spec())), 100)
        with self.assertRaisesRegex(GTM100TodoExecutionLedgerError, "exact"):
            parse_todo_spec(_spec().replace("T050", "T051", 1))

    def test_verified_requires_hashed_implementation_and_test(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "evidence.txt").write_text("proof", encoding="utf-8")
            payload = compile_todo_execution_ledger(_spec(), {"T001": {
                "status": "verified", "evidence_paths": ["evidence.txt"], "test_ids": ["test_t001"],
            }}, project_root=root)
            verify_todo_execution_ledger(payload)
            self.assertEqual(payload["status_counts"]["verified"], 1)
            self.assertFalse(payload["completion_claim_allowed"])

    def test_tampered_completion_credit_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            payload = compile_todo_execution_ledger(_spec(), {}, project_root=Path(temp))
            broken = copy.deepcopy(payload)
            broken["todos"][0]["completion_credit"] = 1
            broken.pop("content_sha256")
            import hashlib, json
            broken["content_sha256"] = hashlib.sha256(json.dumps(broken, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
            with self.assertRaisesRegex(GTM100TodoExecutionLedgerError, "completion credit"):
                verify_todo_execution_ledger(broken)


if __name__ == "__main__":
    unittest.main()
