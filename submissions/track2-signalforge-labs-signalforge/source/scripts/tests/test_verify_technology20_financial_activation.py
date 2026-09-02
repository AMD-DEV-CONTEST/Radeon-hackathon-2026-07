import importlib.util
import unittest
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "verify_technology20_financial_activation",
    ROOT / "scripts" / "verify_technology20_financial_activation.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class Technology20FinancialReferenceTests(unittest.TestCase):
    def test_recomputes_simple_fcf_without_promoting_fcff(self) -> None:
        receipt = {
            "operation_id": "financial.free_cash_flow",
            "normalized_inputs": [
                {"input_id": "operating_cash_flow", "quantity": {"value": "30"}},
                {"input_id": "capital_expenditure", "quantity": {"value": "10"}},
            ],
        }
        self.assertEqual(
            MODULE.independently_recompute(receipt),
            {"free_cash_flow": Decimal("20")},
        )

    def test_recomputes_quality_of_earnings(self) -> None:
        receipt = {
            "operation_id": "financial.quality_of_earnings",
            "normalized_inputs": [
                {"input_id": "operating_cash_flow", "quantity": {"value": "30"}},
                {"input_id": "net_income", "quantity": {"value": "20"}},
            ],
        }
        self.assertEqual(
            MODULE.independently_recompute(receipt),
            {"accrual_gap": Decimal("10"), "cash_conversion": Decimal("1.5")},
        )


if __name__ == "__main__":
    unittest.main()
