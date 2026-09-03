from __future__ import annotations

import unittest

from mantis_rocm_bridge.rocm import collect_rocm_receipt


class RocmReceiptTests(unittest.TestCase):
    def test_receipt_is_bounded_and_has_strict_verdict(self) -> None:
        receipt = collect_rocm_receipt()
        self.assertEqual(receipt["schema_version"], 1)
        self.assertIn("torch", receipt)
        self.assertIsInstance(receipt["strict_rocm_pass"], bool)
        self.assertNotIn("environment", receipt)


if __name__ == "__main__":
    unittest.main()

