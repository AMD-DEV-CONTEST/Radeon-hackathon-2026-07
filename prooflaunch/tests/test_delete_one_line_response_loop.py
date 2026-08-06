from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/delete-one-line-response-loop-v1/response-learning-contract.json"


class DeleteOneLineResponseLoopTests(unittest.TestCase):
    def test_response_loop_separates_learning_from_vanity_and_fails_closed(self) -> None:
        payload = json.loads(OUTPUT.read_text(encoding="utf-8"))
        unsigned = dict(payload)
        supplied = unsigned.pop("content_sha256")
        canonical = json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        self.assertEqual(hashlib.sha256(canonical).hexdigest(), supplied)
        self.assertEqual(len(payload["signal_classes"]), 6)
        self.assertEqual(len(payload["platform_reply_cards"]), 5)
        by_id = {row["id"]: row for row in payload["signal_classes"]}
        self.assertTrue(by_id["reproducible_false_rejection"]["learning_eligible"])
        self.assertFalse(by_id["generic_praise_or_vanity"]["learning_eligible"])
        gate = payload["learning_write_gate"]
        self.assertFalse(gate["automatic_memory_write"])
        self.assertFalse(gate["automatic_strategy_mutation"])
        self.assertFalse(gate["automatic_reply"])
        self.assertFalse(gate["automatic_direct_message"])
        self.assertIsNone(payload["observation_state"]["responses_observed"])
        self.assertFalse(payload["observation_state"]["production_effect_observed"])
        for binding in payload["source_bindings"]:
            path = ROOT / binding["path"]
            self.assertTrue(path.is_file())
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), binding["sha256"])


if __name__ == "__main__":
    unittest.main()
