from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from prooflaunch_remix.production_trace_ledger import (
    POLICY_VERSION,
    ProductionTraceLedger,
)


class ProductionTraceLedgerTests(unittest.TestCase):
    def test_trace_is_content_free_hash_chained_and_restart_durable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve() / "traces"
            ledger = ProductionTraceLedger(root, retention_days=90)
            ledger.append(
                method="POST",
                route="/v1/runs",
                status_code=202,
                duration_ms=12.3456,
                request_bytes=512,
                response_bytes=128,
                tenant_id="org-a",
                trace_id="trace-public-correlation-0001",
                exception_observed=False,
            )
            restarted = ProductionTraceLedger(root, retention_days=90)
            status = restarted.status(tenant_id="org-a")
            self.assertEqual(status["policy_version"], POLICY_VERSION)
            self.assertEqual(status["request_trace_count"], 1)
            self.assertEqual(status["method_counts"]["POST"], 1)
            self.assertEqual(status["status_class_counts"]["2xx"], 1)
            self.assertTrue(status["hash_chain_valid"])
            self.assertEqual(status["retention_days"], 90)
            self.assertFalse(status["raw_content_retained"])
            persisted = (root / "request-traces.jsonl").read_text(encoding="utf-8")
            self.assertNotIn("org-a", persisted)
            self.assertNotIn("trace-public-correlation-0001", persisted)

    def test_tamper_and_retention_drift_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve() / "traces"
            ledger = ProductionTraceLedger(root, retention_days=30)
            ledger.append(
                method="GET",
                route="/v1/health",
                status_code=200,
                duration_ms=1.0,
                request_bytes=0,
                response_bytes=64,
                tenant_id=None,
                trace_id="trace-public-correlation-0002",
                exception_observed=False,
            )
            path = root / "request-traces.jsonl"
            event = json.loads(path.read_text(encoding="utf-8"))
            event["status_code"] = 500
            path.write_text(json.dumps(event) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "hash chain"):
                ProductionTraceLedger(root, retention_days=30)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve() / "traces"
            ledger = ProductionTraceLedger(root, retention_days=30)
            ledger.append(
                method="GET",
                route="/v1/health",
                status_code=200,
                duration_ms=1.0,
                request_bytes=0,
                response_bytes=64,
                tenant_id=None,
                trace_id="trace-public-correlation-0003",
                exception_observed=False,
            )
            with self.assertRaisesRegex(ValueError, "retention"):
                ProductionTraceLedger(root, retention_days=31)

    def test_retention_outside_30_to_90_days_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve() / "traces"
            for days in (0, 29, 91, 365):
                with self.subTest(days=days):
                    with self.assertRaisesRegex(ValueError, "retention_days"):
                        ProductionTraceLedger(root / str(days), retention_days=days)


if __name__ == "__main__":
    unittest.main()
