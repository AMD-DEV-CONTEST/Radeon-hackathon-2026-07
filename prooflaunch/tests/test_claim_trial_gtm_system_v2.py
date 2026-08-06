from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/claim-trial-gtm-system-v2"


class ClaimTrialGTMSystemV2Tests(unittest.TestCase):
    def test_receipt_is_sealed_and_covers_the_last_mile(self) -> None:
        receipt = json.loads((OUTPUT / "receipt.json").read_text(encoding="utf-8"))
        unsigned = dict(receipt)
        supplied = unsigned.pop("content_sha256")
        canonical = json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        self.assertEqual(hashlib.sha256(canonical).hexdigest(), supplied)
        self.assertEqual(receipt["last_mile_job_count"], 6)
        self.assertEqual(receipt["verified_platform_candidate_count"], 26)
        self.assertEqual(receipt["comment_verdict_count"], 5)
        self.assertEqual(receipt["video_scene_count"], 6)
        self.assertEqual(receipt["video_render_status"], "rendered_local_4k_master")
        self.assertEqual(receipt["measurement_stage_count"], 5)
        self.assertEqual(receipt["external_action_count"], 0)
        self.assertEqual(receipt["human_review_count"], 0)
        self.assertEqual(receipt["named_product_win_count"], 0)

    def test_copy_is_platform_native_and_truth_bounded(self) -> None:
        copy = json.loads((OUTPUT / "platform-copy.json").read_text(encoding="utf-8"))
        self.assertEqual(copy["primary_channel"], "LinkedIn organic")
        self.assertIn("Our AI applied for a job it was not qualified for.", copy["launch_post"]["hook"])
        self.assertIn("No DM. No deck. No lead form.", copy["launch_post"]["cta"])
        self.assertEqual(copy["launch_post"]["publish_status"], "human_approval_required")
        self.assertFalse(copy["external_publish_executed"])
        self.assertFalse(copy["market_effect_observed"])

    def test_comment_loop_is_bounded_and_learns_only_from_use(self) -> None:
        loop = json.loads((OUTPUT / "comment-loop.json").read_text(encoding="utf-8"))
        self.assertEqual({row["id"] for row in loop["verdicts"]}, {"AUDIENCE", "TENSION", "CHANNEL", "EVIDENCE", "KILL_RULE"})
        self.assertTrue(loop["safety"]["human_approval_before_reply"])
        self.assertTrue(loop["safety"]["reject_confidential_material"])
        self.assertEqual(loop["learning_event"]["eligible_signal"], "Author confirms the diagnosis changed a real launch decision.")

    def test_real_video_master_is_integrated_but_not_overclaimed(self) -> None:
        video = json.loads((OUTPUT / "video-15s.json").read_text(encoding="utf-8"))
        master = video["rendered_master"]
        self.assertEqual(video["render_status"], "rendered_local_4k_master")
        self.assertEqual((master["width"], master["height"]), (2160, 3840))
        self.assertEqual(master["human_hook_review_status"], "pending")
        self.assertEqual(master["human_listening_review_status"], "pending")
        self.assertTrue((ROOT / master["path"]).is_file())
        html = (OUTPUT / "index.html").read_text(encoding="utf-8")
        self.assertIn("prooflaunch-performance-review-vertical-4k.mp4", html)
        self.assertIn("Rendered is not reviewed.", html)
        self.assertIn("mobile-fixes.css", html)

    def test_bound_files_match_receipt(self) -> None:
        receipt = json.loads((OUTPUT / "receipt.json").read_text(encoding="utf-8"))
        for row in receipt["files"] + receipt["source_bindings"]:
            path = ROOT / row["path"]
            self.assertTrue(path.is_file())
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), row["sha256"])


if __name__ == "__main__":
    unittest.main()
