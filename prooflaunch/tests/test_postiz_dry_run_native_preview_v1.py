from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/postiz-dry-run-native-preview-v1"


class PostizDryRunNativePreviewV1Tests(unittest.TestCase):
    def test_export_has_four_real_provider_shapes_and_no_execution(self) -> None:
        payload = json.loads((OUTPUT / "postiz-dry-run-requests.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["postiz_dry_run_request_count"], 4)
        self.assertEqual(payload["unsupported_slot_count"], 3)
        self.assertEqual(payload["external_request_count"], 0)
        self.assertFalse(payload["automatic_publish_enabled"])
        self.assertTrue(payload["human_approval_required"])
        self.assertEqual(payload["release_fact_contract_id"], "claim-trial-witness-check-release-v1")
        self.assertTrue(payload["last_mile_quality_checks"]["platform_copy_is_not_duplicated"])
        self.assertEqual({row["provider"] for row in payload["requests"]}, {"linkedin", "tiktok", "instagram"})
        contents = []
        for row in payload["requests"]:
            self.assertEqual(row["postiz_request"]["endpoint"], "/public/v1/posts")
            self.assertEqual(row["postiz_request"]["payload"]["type"], "schedule")
            self.assertFalse(row["release_guard"]["external_request_executed"])
            self.assertEqual(row["fact_contract"]["contract_id"], payload["release_fact_contract_id"])
            self.assertLessEqual(row["last_mile_contract"]["participation_seconds"], 30)
            self.assertTrue(row["last_mile_contract"]["single_action"])
            content = row["postiz_request"]["payload"]["posts"][0]["value"][0]["content"]
            contents.append(content)
            self.assertEqual(content.splitlines()[0], row["last_mile_contract"]["hook"])
            self.assertIn("Market response not observed.", content)
        self.assertEqual(len(contents), len(set(contents)))
        tiktok = next(row for row in payload["requests"] if row["provider"] == "tiktok")
        settings = tiktok["postiz_request"]["payload"]["posts"][0]["settings"]
        self.assertEqual(settings["privacy_level"], "SELF_ONLY")
        self.assertEqual(settings["content_posting_method"], "UPLOAD")
        self.assertTrue(settings["video_made_with_ai"])
        self.assertEqual(settings["title"], "Your AI wrote it. Make it testify.")

    def test_receipt_and_bindings_are_sealed(self) -> None:
        receipt = json.loads((OUTPUT / "receipt.json").read_text(encoding="utf-8"))
        unsigned = dict(receipt)
        supplied = unsigned.pop("content_sha256")
        canonical = json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        self.assertEqual(hashlib.sha256(canonical).hexdigest(), supplied)
        for row in receipt["bindings"]:
            path = ROOT / row["path"]
            self.assertTrue(path.is_file(), row["path"])
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), row["sha256"])

    def test_preview_contains_local_approval_and_truth_boundary(self) -> None:
        html = (OUTPUT / "index.html").read_text(encoding="utf-8")
        script = (OUTPUT / "approval.js").read_text(encoding="utf-8")
        self.assertEqual(html.count('class="release"'), 4)
        self.assertIn("ZERO EXTERNAL ACTIONS", html)
        self.assertIn("APPROVE LOCAL DRY RUN", html)
        self.assertIn("postiz-dry-run-requests.js", html)
        self.assertIn("execution_authority: 'none'", script)
        self.assertNotIn("fetch(", script)
        self.assertIn("window.PROOFLAUNCH_POSTIZ_DRY_RUN", script)
        for hook in (
            "If your AI refuses to delete your best homepage line, it is working for the prompt—not for you.",
            "Your AI wrote the line. Now make it testify.",
            "Your homepage does not need another rewrite. It needs a witness.",
            "No victory post today.",
        ):
            self.assertIn(hook, html)
        self.assertIn("Market response not observed.", html)
        self.assertNotIn("We deleted the sentence our launch needed most.", html)
        self.assertNotIn("POV: your best homepage line just got asked for one witness.", html)


if __name__ == "__main__":
    unittest.main()
