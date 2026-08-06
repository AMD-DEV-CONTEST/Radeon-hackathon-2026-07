from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from prooflaunch_remix.v10_todo_evidence import (
    CLOSURE_DEFINITIONS,
    apply_verified_todo_closures,
)


ROOT = Path(__file__).resolve().parents[1]


class TodoEvidenceClosureTests(unittest.TestCase):
    def test_closure_allowlist_is_unique_and_source_bound(
        self,
    ) -> None:
        ids = [item.todo_id for item in CLOSURE_DEFINITIONS]
        self.assertEqual(len(ids), 972)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(1 <= int(todo_id) <= 1500 for todo_id in ids))
        self.assertEqual(ids, sorted(ids))

    def test_verified_closure_never_marks_unlisted_tasks_passed(self) -> None:
        current_report = json.loads(
            (ROOT / "evidence/v10/local-test-report.json").read_text(
                encoding="utf-8"
            )
        )
        required_tests = {
            test_id
            for definition in CLOSURE_DEFINITIONS
            for test_id in definition.test_ids
        }
        if current_report.get("status") != "passed" or not required_tests.issubset(
            set(current_report.get("passed_tests", ()))
        ):
            self.skipTest("bootstrap the local receipt with the new named tests")
        with tempfile.TemporaryDirectory() as directory:
            report_path = Path(directory) / "closure.json"
            manifest_path = Path(directory) / "program.json"
            report = apply_verified_todo_closures(
                ROOT,
                manifest_output=manifest_path,
                report_output=report_path,
                generated_at="2026-07-29T00:00:00+00:00",
            )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(report["closed_count"], 972)
        self.assertEqual(report["status_counts"]["passed"], 972)
        self.assertEqual(report["status_counts"]["not_started"], 528)
        self.assertEqual(
            [
                item["todo_id"]
                for item in manifest["todos"]
                if item["status"] == "passed"
            ],
            [item.todo_id for item in CLOSURE_DEFINITIONS],
        )
        self.assertFalse(
            any(
                item["status"] == "passed"
                for item in manifest["todos"]
                if item["todo_id"] not in {
                    definition.todo_id
                    for definition in CLOSURE_DEFINITIONS
                }
            )
        )


if __name__ == "__main__":
    unittest.main()
