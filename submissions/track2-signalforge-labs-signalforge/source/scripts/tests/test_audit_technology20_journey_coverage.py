import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "audit_technology20_journey_coverage",
    ROOT / "scripts" / "audit_technology20_journey_coverage.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class Technology20JourneyCoverageTests(unittest.TestCase):
    def write_inputs(
        self,
        root: Path,
        domains: list[str],
        split: str = "development",
    ) -> tuple[Path, Path]:
        companies = [
            {
                "company_id": f"company-{index}",
                "primary_ticker": f"T{index:02d}",
            }
            for index in range(20)
        ]
        catalog = root / "catalog.json"
        suite = root / "suite.json"
        catalog.write_text(
            json.dumps({"universe_id": "technology-20", "companies": companies}),
            encoding="utf-8",
        )
        cases = []
        for company in companies:
            for domain in domains:
                cases.append(
                    {
                        "journey_id": f"{company['company_id']}-{domain}",
                        "company_id": company["company_id"],
                        "question_id": domain,
                        "required_domains": [domain],
                    }
                )
        suite.write_text(
            json.dumps({"split": split, "cases": cases}),
            encoding="utf-8",
        )
        return catalog, suite

    def test_missing_domains_block_promotion_without_reading_sealed_data(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog, suite = self.write_inputs(
                root,
                ["accounting", "business", "evidence", "financial_quality", "market_behavior"],
            )
            report = MODULE.audit(catalog, suite)
            self.assertFalse(report["promotion_eligible"])
            self.assertEqual(report["missing_global_domains"], ["economics", "valuation"])
            self.assertEqual(report["companies_with_complete_domain_coverage"], 0)
            self.assertIn("does not read sealed cases", report["claim_boundary"])

    def test_complete_declared_coverage_is_eligible_when_structure_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog, suite = self.write_inputs(
                root,
                list(MODULE.REQUIRED_STANDALONE_DOMAINS),
            )
            report = MODULE.audit(catalog, suite)
            self.assertTrue(report["promotion_eligible"])
            self.assertEqual(report["missing_global_domains"], [])
            self.assertEqual(report["companies_with_complete_domain_coverage"], 20)
            self.assertEqual(report["problems"], [])

    def test_sealed_split_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog, suite = self.write_inputs(
                root,
                ["accounting"],
                split="sealed",
            )
            with self.assertRaisesRegex(ValueError, "development"):
                MODULE.audit(catalog, suite)


if __name__ == "__main__":
    unittest.main()
