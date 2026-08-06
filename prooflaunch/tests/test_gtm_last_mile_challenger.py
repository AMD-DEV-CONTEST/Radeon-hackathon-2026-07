from __future__ import annotations

import unittest

from prooflaunch_remix.gtm_last_mile_challenger import (
    LANE_FIELDS,
    challenger_failures,
    compile_receipt,
    extract_json_object,
    validate_receipt,
)


def candidate() -> dict[str, object]:
    payload: dict[str, object] = {}
    for lane, fields in LANE_FIELDS.items():
        payload[lane] = {
            field: f"Specific {field} for {lane} that an operator can inspect and execute tomorrow without an unsupported outcome claim."
            for field in fields
        }
    return payload


class GTMLastMileChallengerTests(unittest.TestCase):
    def test_extracts_fenced_json(self) -> None:
        value = extract_json_object("```json\n" + __import__("json").dumps(candidate()) + "\n```")
        self.assertEqual(set(value), set(LANE_FIELDS))

    def test_all_lanes_are_required(self) -> None:
        value = candidate()
        value.pop("geo")
        self.assertTrue(any("top-level lane mismatch" in item for item in challenger_failures(value)))

    def test_unsupported_status_claim_fails(self) -> None:
        value = candidate()
        value["integrated_gtm_strategy"]["diagnosis"] = "Guaranteed Top-1 result"
        self.assertTrue(challenger_failures(value))

    def test_receipt_preserves_no_promotion_boundary(self) -> None:
        value = candidate()
        receipt = compile_receipt(
            model_id="local/model",
            model_revision="abcdef123",
            model_manifest_sha256="a" * 64,
            attempts=[{"raw_output": __import__("json").dumps(value), "source": "test"}],
        )
        validate_receipt(receipt)
        self.assertTrue(receipt["accepted"])
        self.assertEqual(receipt["lane_count"], 11)
        self.assertFalse(receipt["human_review_completed"])
        self.assertFalse(receipt["winner_selected"])


if __name__ == "__main__":
    unittest.main()
