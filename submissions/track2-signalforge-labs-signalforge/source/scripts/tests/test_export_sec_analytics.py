import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("sec_analytics", ROOT / "scripts" / "export_sec_analytics.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ExportSECAnalyticsTests(unittest.TestCase):
    def test_sql_path_escapes_single_quote(self):
        escaped = MODULE.sql_path(Path("folder/it's.jsonl"))
        self.assertTrue(escaped.startswith("'") and escaped.endswith("'"))
        self.assertIn("it''s.jsonl", escaped)

    def test_expected_tables_are_fixed(self):
        self.assertEqual(len(MODULE.TABLES), len(set(MODULE.TABLES)))
        self.assertIn("normalized_metrics", MODULE.TABLES)


if __name__ == "__main__":
    unittest.main()
