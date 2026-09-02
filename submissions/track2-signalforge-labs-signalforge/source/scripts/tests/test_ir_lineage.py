from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "ir_lineage.py"
SPEC = importlib.util.spec_from_file_location("ir_lineage", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class IRLineageTests(unittest.TestCase):
    def test_missing_current_is_not_called_deleted(self) -> None:
        previous = [{"canonical_uri": "https://example.com/a", "document_id": "a", "content_sha256": "1", "retrieved_at": "old"}]
        records = MODULE.compare(previous, [])
        self.assertEqual("not_observed_in_current_run", records[0]["disposition"])

    def test_same_uri_with_new_hash_is_content_change(self) -> None:
        previous = [{"canonical_uri": "https://example.com/a", "document_id": "a", "content_sha256": "1", "retrieved_at": "old"}]
        current = [{"canonical_uri": "https://example.com/a", "document_id": "a", "content_sha256": "2", "retrieved_at": "new"}]
        records = MODULE.compare(previous, current)
        self.assertEqual("content_changed", records[0]["disposition"])
        self.assertEqual("a", records[0]["supersession"]["superseding_document_id"])

    def test_same_hash_at_new_uri_is_move_not_deletion(self) -> None:
        previous = [{"canonical_uri": "https://example.com/a", "document_id": "a", "content_sha256": "1", "retrieved_at": "old"}]
        current = [{"canonical_uri": "https://cdn.example.com/a", "document_id": "a2", "content_sha256": "1", "retrieved_at": "new"}]
        records = MODULE.compare(previous, current)
        self.assertEqual(["moved_uri", "moved_uri"], [item["disposition"] for item in records])
        by_uri = {item["canonical_uri"]: item for item in records}
        self.assertEqual("https://cdn.example.com/a", by_uri["https://example.com/a"]["moved_to_uri"])
        self.assertEqual("https://example.com/a", by_uri["https://cdn.example.com/a"]["moved_from_uri"])

    def test_same_hash_alias_is_not_misclassified_as_a_move(self) -> None:
        previous = [
            {"canonical_uri": "https://example.com/a", "document_id": "a", "content_sha256": "1", "retrieved_at": "old"},
        ]
        current = [
            {"canonical_uri": "https://example.com/a", "document_id": "a", "content_sha256": "1", "retrieved_at": "new"},
            {"canonical_uri": "https://example.com/alias", "document_id": "alias", "content_sha256": "1", "retrieved_at": "new"},
        ]
        records = MODULE.compare(previous, current)
        by_uri = {item["canonical_uri"]: item for item in records}
        self.assertEqual("unchanged", by_uri["https://example.com/a"]["disposition"])
        self.assertEqual("newly_observed", by_uri["https://example.com/alias"]["disposition"])

    def test_duplicate_canonical_uri_fails_closed(self) -> None:
        duplicate = [
            {"canonical_uri": "https://example.com/a", "document_id": "a", "content_sha256": "1", "retrieved_at": "one"},
            {"canonical_uri": "https://example.com/a", "document_id": "b", "content_sha256": "2", "retrieved_at": "two"},
        ]
        with self.assertRaises(ValueError):
            MODULE.compare(duplicate, [])

    def test_sec_duplicate_becomes_alias_only(self) -> None:
        ir = [{
            "document_id": "ir-1",
            "content_sha256": "abc",
            "canonical_uri": "https://ir.example.com/exhibit.pdf",
        }]
        sec = [{
            "document_id": "sec-1",
            "content_sha256": "abc",
            "source_uri": "https://www.sec.gov/Archives/exhibit.pdf",
        }]
        aliases = MODULE.resolve_sec_aliases(ir, sec)
        self.assertEqual("sec", aliases[0]["canonical_authority"])
        self.assertEqual("alias_only_do_not_embed_duplicate", aliases[0]["embedding_disposition"])

    def test_sec_alias_choice_is_deterministic(self) -> None:
        ir = [{"document_id": "ir-1", "content_sha256": "abc"}]
        sec = [
            {"document_id": "sec-z", "content_sha256": "abc", "source_uri": "https://www.sec.gov/z"},
            {"document_id": "sec-a", "content_sha256": "abc", "source_uri": "https://www.sec.gov/a"},
        ]
        forward = MODULE.resolve_sec_aliases(ir, sec)
        reverse = MODULE.resolve_sec_aliases(ir, list(reversed(sec)))
        self.assertEqual(forward, reverse)
        self.assertEqual("sec-a", forward[0]["sec_document_id"])


if __name__ == "__main__":
    unittest.main()
