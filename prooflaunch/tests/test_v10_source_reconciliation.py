from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "audit_v10_source_reconciliation.py"
SPEC = importlib.util.spec_from_file_location(
    "audit_v10_source_reconciliation",
    SCRIPT,
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
DEFAULT_FIRST_300 = MODULE.DEFAULT_FIRST_300
DEFAULT_SECOND_1200 = MODULE.DEFAULT_SECOND_1200
build_audit = MODULE.build_audit
CANONICAL = ROOT / "docs" / "CORTEX_X_V10_1500_TODO.md"
EVIDENCE = (
    ROOT / "evidence" / "v10" / "source-reconciliation-300-plus-1200.json"
)


class V10SourceReconciliationTests(unittest.TestCase):
    def test_user_sources_are_exactly_1200_then_300(self) -> None:
        audit = build_audit(
            DEFAULT_FIRST_300,
            DEFAULT_SECOND_1200,
            CANONICAL,
        )
        self.assertEqual(audit["status"], "pass")
        self.assertEqual(
            audit["sources"]["secondAttachment1200"]["rangeAudit"][
                "observedCount"
            ],
            1200,
        )
        self.assertEqual(
            audit["sources"]["firstAttachment300"]["rangeAudit"][
                "observedCount"
            ],
            300,
        )
        self.assertTrue(audit["combinedRangeAudit"]["strictlyOrderedAndContiguous"])
        self.assertEqual(audit["combinedRangeAudit"]["observedStart"], 1)
        self.assertEqual(audit["combinedRangeAudit"]["observedEnd"], 1500)
        self.assertTrue(audit["comparison"]["orderExact"])
        self.assertEqual(audit["comparison"]["textMismatchCount"], 0)
        self.assertEqual(
            audit["completionEffect"]["todosClosedByThisAudit"],
            0,
        )

    def test_sealed_evidence_hash_and_source_hashes_are_valid(self) -> None:
        payload = json.loads(EVIDENCE.read_text(encoding="utf-8"))
        expected_audit_hash = payload.pop("auditSha256")
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        self.assertEqual(hashlib.sha256(canonical).hexdigest(), expected_audit_hash)
        self.assertEqual(payload["status"], "pass")
        for key in ("firstAttachment300", "secondAttachment1200"):
            source = payload["sources"][key]
            source_path = Path(source["path"])
            self.assertTrue(source_path.is_file())
            self.assertEqual(
                hashlib.sha256(source_path.read_bytes()).hexdigest(),
                source["sha256"],
            )


if __name__ == "__main__":
    unittest.main()
