from __future__ import annotations

import unittest

from prooflaunch_remix.gtm_cross_platform_dedup_v2 import compile_cross_platform_dedup, verify_cross_platform_dedup


def r(record_id: str, text: str, **extra: object) -> dict:
    row = {"record_id": record_id, "platform": "linkedin", "source_url": f"https://example.com/{record_id}", "language": "en", "text": text}
    row.update(extra)
    return row


class GTMCrossPlatformDedupV2Tests(unittest.TestCase):
    def _decision(self, left: dict, right: dict) -> dict:
        payload = compile_cross_platform_dedup([left, right])
        verify_cross_platform_dedup(payload)
        return payload["pair_decisions"][0]

    def test_exact_repost_is_the_only_automatic_merge(self) -> None:
        decision = self._decision(r("a", "One exact public message"), r("b", "One exact public message", platform="x"))
        self.assertEqual(decision["decision"], "exact_mirror")
        self.assertTrue(decision["automatic_episode_merge_allowed"])

    def test_verified_translation_is_detected_but_not_auto_merged(self) -> None:
        receipt = ["a" * 64]
        left = r("a", "A product proof in English", language="en", verified_translation_text="the same canonical product proof", translation_receipt_sha256s=receipt)
        right = r("b", "Une preuve produit en français", language="fr", verified_translation_text="the same canonical product proof", translation_receipt_sha256s=receipt)
        decision = self._decision(left, right)
        self.assertEqual(decision["decision"], "translation_mirror")
        self.assertFalse(decision["automatic_episode_merge_allowed"])

    def test_video_clip_and_audio_edit_use_containment(self) -> None:
        left = r("a", "First cut", perceptual_frame_hashes=["f1", "f2", "f3", "f4", "f5"])
        right = r("b", "Edited clip", perceptual_frame_hashes=["f2", "f3", "f4", "f5"])
        self.assertEqual(self._decision(left, right)["decision"], "clip_or_light_media_edit")

    def test_light_rewrite_is_reviewed_and_distinct_content_stays_distinct(self) -> None:
        left = r("a", "Engineers compare five filters before selecting the safest industrial system")
        rewritten = r("b", "Engineers compare five filters before selecting a safe industrial system")
        decision = self._decision(left, rewritten)
        self.assertEqual(decision["decision"], "light_rewrite_or_repost")
        self.assertFalse(decision["automatic_episode_merge_allowed"])
        distinct = self._decision(left, r("c", "A hotel launches a family loyalty breakfast program"))
        self.assertEqual(distinct["decision"], "distinct")


if __name__ == "__main__":
    unittest.main()
