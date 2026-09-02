import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "build_technology20_source_readiness",
    ROOT / "scripts" / "build_technology20_source_readiness.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class Technology20SourceReadinessTests(unittest.TestCase):
    def test_missing_sources_remain_explicit_and_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog_path = root / "catalog.json"
            audit_path = root / "audit.json"
            companies = [
                {
                    "company_id": f"company-{index}",
                    "display_name": f"Company {index}",
                    "primary_ticker": f"T{index}",
                }
                for index in range(20)
            ]
            catalog_path.write_text(
                json.dumps({"universe_id": "universe", "companies": companies}),
                encoding="utf-8",
            )
            audit_path.write_text(
                json.dumps(
                    {
                        "passed": True,
                        "as_of": "2026-07-24T00:00:00Z",
                        "company_freshness": [
                            {
                                "company_id": item["company_id"],
                                "status": "fresh",
                                "latest_periodic_form": "10-Q",
                                "latest_periodic_published_at": "2026-05-01T00:00:00Z",
                                "age_days": 84,
                            }
                            for item in companies
                        ],
                    }
                ),
                encoding="utf-8",
            )
            result = MODULE.build(catalog_path, audit_path)
            self.assertEqual(result["source_summary"]["sec_companyfacts_fresh"], 20)
            self.assertEqual(result["source_summary"]["market_price_missing"], 20)
            self.assertTrue(
                all(item["standalone_promotion_blocked"] for item in result["companies"])
            )


if __name__ == "__main__":
    unittest.main()
