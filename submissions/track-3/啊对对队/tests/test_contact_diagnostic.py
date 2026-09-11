from __future__ import annotations

import unittest

from scripts.diagnose_contact_links import _resolve_contact_pair


class ContactDiagnosticTests(unittest.TestCase):
    def test_resolves_contact_when_robot_is_link_a(self) -> None:
        pair = _resolve_contact_pair(12, 14, {12: "left_finger"}, {14: "parcel"})

        self.assertEqual(pair, (12, 14))

    def test_resolves_contact_when_robot_is_link_b(self) -> None:
        pair = _resolve_contact_pair(14, 12, {12: "left_finger"}, {14: "parcel"})

        self.assertEqual(pair, (12, 14))

    def test_rejects_unmapped_contact_pair(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "unmapped link pair"):
            _resolve_contact_pair(1, 2, {12: "left_finger"}, {14: "parcel"})


if __name__ == "__main__":
    unittest.main()
