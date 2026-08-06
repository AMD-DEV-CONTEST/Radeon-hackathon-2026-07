from __future__ import annotations

import unittest

from prooflaunch_remix.v10_contracts import V10ContractError
from prooflaunch_remix.v10_free_api_sprint import (
    FreeApiObservation,
    assert_public_synthetic_only,
    grade_gtm_content,
    rank_candidates,
)


VALID = """{
  "strategy": {"objective": "qualified pipeline"},
  "actions": [{"type": "draft", "owner": "agent"}],
  "claims": [{"claim": "Synthetic fixture only", "source": "fixture://brief"}],
  "approvals": [{"gate": "human_release", "required": true}],
  "metrics": [{"name": "qualified_leads", "target": 10}]
}"""


def observation(candidate: str, latency: float, content: str = VALID) -> FreeApiObservation:
    grades = grade_gtm_content(content)
    return FreeApiObservation(
        candidate,
        "case-01",
        "a" * 64,
        "b" * 64,
        "resolved/model",
        200,
        latency,
        content=content,
        **grades,
    )


class FreeApiSprintTests(unittest.TestCase):
    def test_strict_gtm_json_contract(self) -> None:
        self.assertTrue(all(grade_gtm_content(VALID).values()))
        self.assertTrue(all(grade_gtm_content(f"```json\n{VALID}\n```").values()))
        self.assertFalse(grade_gtm_content("not json")["schema_valid"])

    def test_empty_claims_are_allowed_but_ungrounded_claims_are_not(self) -> None:
        no_claim = VALID.replace(
            '[{"claim": "Synthetic fixture only", "source": "fixture://brief"}]',
            "[]",
        )
        bad_claim = VALID.replace('"fixture://brief"', '""')
        self.assertTrue(grade_gtm_content(no_claim)["claims_grounded"])
        self.assertFalse(grade_gtm_content(bad_claim)["claims_grounded"])

    def test_hard_gates_precede_latency(self) -> None:
        valid_slow = observation("valid-slow", 100.0)
        valid_fast = observation("valid-fast", 10.0)
        invalid = observation("invalid", 1.0, "{}")
        self.assertEqual(
            rank_candidates((valid_slow, invalid, valid_fast)),
            ("valid-fast", "valid-slow"),
        )

    def test_free_endpoint_data_boundary(self) -> None:
        assert_public_synthetic_only("public")
        assert_public_synthetic_only("synthetic")
        with self.assertRaises(V10ContractError):
            assert_public_synthetic_only("confidential")


if __name__ == "__main__":
    unittest.main()
