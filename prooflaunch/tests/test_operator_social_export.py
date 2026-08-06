from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from prooflaunch_remix.ledger import canonical_json
from prooflaunch_remix.operator_social_export import (
    OPERATOR_ATTESTATION,
    OperatorSocialExportError,
    compile_operator_social_export,
)


class OperatorSocialExportTests(unittest.TestCase):
    def test_normalizes_public_ndjson_and_rejects_private_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "zeeschuimer.ndjson"
            rows = [
                {
                    "data": {
                        "id": "public-1",
                        "url": "https://www.tiktok.com/@brand/video/1",
                        "create_time": 1785456000,
                        "desc": "A public launch post",
                        "play_count": 1200,
                        "digg_count": 85,
                        "comment_count": 14,
                        "share_count": 7,
                    }
                },
                {
                    "data": {
                        "id": "private-1",
                        "privacy": "friends",
                        "text": "must not enter output",
                    }
                },
                {"data": {"text": "missing identity"}},
            ]
            path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
            payload = compile_operator_social_export(
                path,
                platform="tiktok",
                operator_attestation=OPERATOR_ATTESTATION,
                observed_at=datetime(2026, 8, 4, tzinfo=timezone.utc),
            )
        self.assertEqual(payload["input_row_count"], 3)
        self.assertEqual(payload["accepted_public_item_count"], 1)
        self.assertEqual(payload["private_item_rejected_count"], 1)
        self.assertEqual(payload["invalid_item_rejected_count"], 1)
        self.assertEqual(payload["recent_item_count_90d"], 1)
        self.assertEqual(payload["items"][0]["metrics"]["view_count"], 1200)
        self.assertFalse(payload["raw_content_training_admitted"])
        self.assertEqual(payload["automatic_learning_memory_write_count"], 0)
        self.assertFalse(
            payload["authentication_captcha_paywall_or_rate_limit_bypass_attempted"]
        )
        supplied = payload.pop("content_sha256")
        self.assertEqual(
            supplied, hashlib.sha256(canonical_json(payload).encode()).hexdigest()
        )

    def test_exact_attestation_is_required(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "export.json"
            path.write_text('[{"id":"1"}]', encoding="utf-8")
            with self.assertRaisesRegex(OperatorSocialExportError, "attestation"):
                compile_operator_social_export(
                    path,
                    platform="instagram",
                    operator_attestation="approved",
                )

    def test_rejects_unsupported_extension(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "export.txt"
            path.write_text('{"id":"1"}', encoding="utf-8")
            with self.assertRaisesRegex(OperatorSocialExportError, "must use"):
                compile_operator_social_export(
                    path,
                    platform="instagram",
                    operator_attestation=OPERATOR_ATTESTATION,
                )


if __name__ == "__main__":
    unittest.main()
