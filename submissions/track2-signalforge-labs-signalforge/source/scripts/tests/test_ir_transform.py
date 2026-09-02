from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "ir_transform.py"
SPEC = importlib.util.spec_from_file_location("ir_transform", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class IRTransformTests(unittest.TestCase):
    def test_html_parser_preserves_heading_locator_context(self) -> None:
        blocks = MODULE.extract_html(b"<h2>Strategy</h2><p>Cloud infrastructure demand remained strong.</p>")
        self.assertEqual([("Strategy", "Cloud infrastructure demand remained strong.", "html:paragraph=1", 0)], blocks)

    def test_html_parser_removes_navigation_boilerplate(self) -> None:
        blocks = MODULE.extract_html(b"<h2>FAQ</h2><p>Back to Top</p><p>Read more</p>")
        self.assertEqual([], blocks)

    def test_html_parser_removes_contact_and_editor_boilerplate(self) -> None:
        blocks = MODULE.extract_html(
            b"<h2>Release</h2>"
            b"<p>For more information, financial analysts and investors only: contact IR.</p>"
            b"<p>For more information, press only: contact media relations.</p>"
            b"<p>Note to editors: links were correct at publication.</p>"
            b"<p>Management emphasized responsible AI adoption.</p>"
        )
        self.assertEqual(
            [("Release", "Management emphasized responsible AI adoption.", "html:paragraph=1", 0)],
            blocks,
        )

    def test_html_parser_removes_operational_stock_lookup_sections(self) -> None:
        blocks = MODULE.extract_html(
            b"<h2>Lookup stock prices by date</h2>"
            b"<p>Prices display split-adjusted cost basis per share on that date.</p>"
            b"<h2>Strategy</h2><p>Management continues to invest in responsible AI systems.</p>"
        )
        self.assertEqual(
            [("Strategy", "Management continues to invest in responsible AI systems.", "html:paragraph=1", 0)],
            blocks,
        )

    def test_html_parser_preserves_table_cell_locators(self) -> None:
        blocks = MODULE.extract_html(
            b"<h2>Segments</h2><table><tr><th>Platform category and customer description</th>"
            b"<td>Cloud services include infrastructure and database products.</td></tr></table>"
        )
        self.assertEqual("html:table_cell=1", blocks[0][2])
        self.assertEqual("html:table_cell=2", blocks[1][2])

    def test_plain_text_preserves_speaker_and_role_context(self) -> None:
        blocks = MODULE.extract_text(
            b"Jane Example -- Chief Executive Officer\n\n"
            b"Management described stronger demand for the cloud platform and related services."
        )
        self.assertEqual("Speaker: Jane Example | Role: Chief Executive Officer", blocks[0][0])
        self.assertEqual("text:paragraph=2", blocks[0][2])

    def test_json_feed_preserves_stable_paths(self) -> None:
        blocks = MODULE.extract_json(
            b'{"items":[{"title":"Management described a durable cloud strategy for enterprise customers."}]}'
        )
        self.assertEqual("$.items[0].title", blocks[0][2].removeprefix("json:path="))

    def test_malformed_json_fails_visibly(self) -> None:
        with self.assertRaises(json.JSONDecodeError):
            MODULE.extract_json(b'{"items": [}')

    def test_malformed_pdf_fails_visibly(self) -> None:
        with self.assertRaises(Exception):
            MODULE.extract_pdf(b"not-a-pdf")

    def test_projection_replaces_financial_literals_but_preserves_year(self) -> None:
        projected, references = MODULE.silent_projection("In 2025 revenue was $12.4 billion and margin was 31%.")
        self.assertIn("2025", projected)
        self.assertNotIn("$12.4", projected)
        self.assertNotIn("31%", projected)
        self.assertEqual(2, len(references))

    def test_projection_handles_compacted_tables_and_plain_currency(self) -> None:
        projected, references = MODULE.silent_projection("Margins 47.6%46.0%, values 492M485M, and cash $12.")
        self.assertNotIn("47.6%", projected)
        self.assertNotIn("46.0%", projected)
        self.assertNotIn("$12", projected)
        self.assertNotIn("492M", projected)
        self.assertNotIn("485M", projected)
        self.assertEqual(5, len(references))

    def test_projection_masks_a_contextual_range_without_leaving_an_orphan_t(self) -> None:
        projected, references = MODULE.silent_projection(
            "Looking for 39 to 40 in constant currency."
        )

        self.assertEqual(
            "Looking for [FINANCIAL_VALUE_001] in constant currency.", projected
        )
        self.assertEqual(["FINANCIAL_VALUE_001"], references)

    def test_projection_preserves_year_ranges(self) -> None:
        projected, references = MODULE.silent_projection(
            "The archive covers 2021 to 2026 and product versions 3 to 4."
        )

        self.assertEqual(
            "The archive covers 2021 to 2026 and product versions 3 to 4.", projected
        )
        self.assertEqual([], references)

    def test_projection_still_masks_case_sensitive_compact_units(self) -> None:
        projected, references = MODULE.silent_projection(
            "Revenue was $6.2B and volume reached 3M units."
        )

        self.assertEqual(
            "Revenue was [FINANCIAL_VALUE_001] and volume reached [FINANCIAL_VALUE_002] units.",
            projected,
        )
        self.assertEqual(["FINANCIAL_VALUE_001", "FINANCIAL_VALUE_002"], references)

    def test_chunk_overlap_is_bounded(self) -> None:
        text = " ".join(["evidence"] * 200)
        chunks = MODULE.chunk_blocks([("Section", text, "html:paragraph=1", 0)], 500, 50)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(item[1]) <= 500 for item in chunks))


if __name__ == "__main__":
    unittest.main()
