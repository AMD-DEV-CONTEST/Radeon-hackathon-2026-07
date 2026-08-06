from __future__ import annotations

import copy
import unittest

from prooflaunch_remix.gtm_hybrid_quality_control import LANE_CONTRACTS
from prooflaunch_remix.gtm_omnichannel_craft_os import (
    GTMOmnichannelCraftError,
    compile_lane_craft_playbook,
    verify_lane_craft_playbook,
)


class GTMOmnichannelCraftOSTests(unittest.TestCase):
    def _playbook(self, category_id: str):
        contract = LANE_CONTRACTS[category_id]
        return compile_lane_craft_playbook(
            category_id,
            same_brief_task=f"Frozen task for {category_id}",
            effect_pk_question="Which side is directly more production-ready?",
            quality_axes=("idea", "craft", "delivery polish"),
            output_contract=contract["output_contract"],
            hard_gates=contract["hard_gates"],
            failure_signals=contract["failure_signals"],
        )

    def test_video_uses_director_picture_motion_audio_and_independent_reviewers(self) -> None:
        playbook = self._playbook("video_generation_production")
        verify_lane_craft_playbook(playbook)
        self.assertEqual(
            playbook["producer_role_ids"],
            ["short_video_director", "art_design_director", "audio_voice_producer"],
        )
        self.assertFalse(
            set(playbook["producer_role_ids"]) & set(playbook["reviewer_role_ids"])
        )
        self.assertEqual(playbook["work_order_count"], 12)
        self.assertTrue(playbook["review_loop"]["all_three_must_re_review_after_repair"])

    def test_all_lanes_compile_with_distinct_playbooks_and_no_external_action(self) -> None:
        playbooks = [self._playbook(category_id) for category_id in LANE_CONTRACTS]
        self.assertEqual(len(playbooks), 13)
        self.assertEqual(len({row["content_sha256"] for row in playbooks}), 13)
        self.assertEqual(sum(row["work_order_count"] for row in playbooks), 153)
        self.assertEqual(
            sum(row["selected_atomic_skill_assignment_count"] for row in playbooks),
            718,
        )
        self.assertTrue(
            all(
                row["harness"]["automatic_external_action_count"] == 0
                and row["harness"]["named_human_release_required"]
                for row in playbooks
            )
        )

    def test_tampered_review_authority_fails_closed(self) -> None:
        playbook = self._playbook("advertising_activation")
        tampered = copy.deepcopy(playbook)
        tampered["review_loop"]["model_review_can_release_or_promote"] = True
        with self.assertRaisesRegex(GTMOmnichannelCraftError, "digest"):
            verify_lane_craft_playbook(tampered)


if __name__ == "__main__":
    unittest.main()
