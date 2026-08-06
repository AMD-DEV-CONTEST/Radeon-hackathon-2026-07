from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/gtm-last-mile-release-copy-v1"


def assert_sealed(test: unittest.TestCase, path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256")
    canonical = json.dumps(
        unsigned,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    test.assertEqual(hashlib.sha256(canonical).hexdigest(), supplied)
    return payload


class GTMLastMileReleaseCopyV1Tests(unittest.TestCase):
    def test_release_copy_is_platform_native_and_contract_bound(self) -> None:
        payload = assert_sealed(self, OUTPUT / "release-copy.json")
        self.assertEqual(len(payload["platforms"]), 4)
        self.assertEqual(payload["checks"]["selected_hook_count"], 3)
        self.assertEqual(payload["checks"]["rejected_hook_count"], 9)
        self.assertFalse(payload["checks"]["external_market_effect_observed"])
        boundary = payload["contract"]["required_boundary_sentence"]
        captions = []
        for row in payload["platforms"].values():
            captions.append(row["caption"])
            self.assertEqual(row["caption"].splitlines()[0], row["hook"])
            self.assertIn(boundary, row["caption"])
            self.assertTrue(row["single_action"])
            self.assertLessEqual(row["participation_seconds"], 30)
        self.assertEqual(len(captions), len(set(captions)))

    def test_hook_tournament_rejects_unproved_and_generic_hooks(self) -> None:
        payload = json.loads((OUTPUT / "release-copy.json").read_text(encoding="utf-8"))
        selected = [row for row in payload["hook_tournament"] if row["decision"] == "selected"]
        rejected = [row for row in payload["hook_tournament"] if row["decision"] == "rejected"]
        self.assertEqual(len(selected), 3)
        self.assertEqual(len(rejected), 9)
        selected_text = "\n".join(row["text"] for row in selected)
        self.assertNotIn("world's most honest", selected_text)
        self.assertNotIn("change your marketing forever", selected_text)
        self.assertTrue(any("unproved superlative" in row["reason"] for row in rejected))
        self.assertTrue(any("deceptive outcome framing" in row["reason"] for row in rejected))

    def test_creative_audit_is_sealed_and_names_the_real_failures(self) -> None:
        audit = assert_sealed(self, OUTPUT / "creative-audit.json")
        failures = {row["axis"] for row in audit["before"] if row["status"] == "fail"}
        self.assertEqual(
            failures,
            {"audience_as_subject", "concept_density", "participation_friction", "surface_divergence"},
        )
        self.assertEqual(len(audit["research_basis"]), 3)


if __name__ == "__main__":
    unittest.main()
