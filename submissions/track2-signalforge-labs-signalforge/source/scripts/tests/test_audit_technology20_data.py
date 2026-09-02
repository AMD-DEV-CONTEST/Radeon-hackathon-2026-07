import importlib.util
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "audit_technology20_data", ROOT / "scripts" / "audit_technology20_data.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class Technology20DataAuditTests(unittest.TestCase):
    def test_parse_time_normalizes_utc(self) -> None:
        parsed = MODULE.parse_time("2026-07-24T10:32:53Z")
        self.assertEqual(parsed.tzinfo, MODULE.timezone.utc)

    def test_freshness_policy_is_versioned(self) -> None:
        self.assertEqual(MODULE.FRESHNESS_POLICY, "sec-periodic-filing-age-180d/v1")

    def test_semantic_mapping_policy_is_versioned(self) -> None:
        self.assertEqual(
            MODULE.SEMANTIC_MAPPING_POLICY,
            "sec-companyfacts-semantic-mapping-review/v1",
        )

    def test_audit_schema_records_semantic_assurance_version(self) -> None:
        self.assertEqual(
            MODULE.SCHEMA_VERSION,
            "signalforge/technology20-data-authority-audit/v2",
        )

    def test_period_shape_distinguishes_duration_and_instant(self) -> None:
        start = datetime(2025, 1, 1, tzinfo=timezone.utc)
        end = datetime(2025, 12, 31, tzinfo=timezone.utc)
        self.assertTrue(MODULE.period_shape_valid("duration", start, end))
        self.assertFalse(MODULE.period_shape_valid("duration", end, end))
        self.assertTrue(MODULE.period_shape_valid("instant", end, end))
        self.assertFalse(MODULE.period_shape_valid("instant", start, end))

    def test_normalized_lineage_requires_exact_authority_join(self) -> None:
        available = datetime(2026, 1, 1, tzinfo=timezone.utc)
        item = {"company_id": "company-1", "source_fact_ids": ["fact-1", "fact-2"]}
        authority = {
            "fact-1": ("company-1", "USD", "duration", available),
            "fact-2": ("company-1", "USD", "duration", available),
        }
        self.assertTrue(
            MODULE.normalized_source_lineage_valid(
                item, "USD", "duration", available, authority
            )
        )
        for field, replacement in (
            (0, "company-2"),
            (1, "shares"),
            (2, "instant"),
            (3, datetime(2026, 1, 2, tzinfo=timezone.utc)),
        ):
            invalid = dict(authority)
            value = list(invalid["fact-2"])
            value[field] = replacement
            invalid["fact-2"] = tuple(value)
            self.assertFalse(
                MODULE.normalized_source_lineage_valid(
                    item, "USD", "duration", available, invalid
                )
            )
        self.assertFalse(
            MODULE.normalized_source_lineage_valid(
                item, "USD", "duration", available, {"fact-1": authority["fact-1"]}
            )
        )

    def test_records_rejects_invalid_json_with_line_number(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as directory:
            path = Path(directory) / "bad.jsonl"
            path.write_text('{"ok": true}\nnot-json\n', encoding="utf-8")
            iterator = MODULE.records(path)
            self.assertEqual(next(iterator), {"ok": True})
            with self.assertRaisesRegex(ValueError, r"bad\.jsonl:2"):
                next(iterator)


if __name__ == "__main__":
    unittest.main()
