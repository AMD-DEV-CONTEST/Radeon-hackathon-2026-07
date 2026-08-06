from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import imageio.v2 as imageio
from PIL import Image

from prooflaunch_remix.realtime_preset_campaign import (
    RealtimePresetCampaignError,
    compile_realtime_preset_campaign,
)


ROOT = Path(__file__).resolve().parents[1]


class RealtimePresetCampaignTests(unittest.TestCase):
    def test_compiles_three_platform_images_and_three_six_scene_films(self) -> None:
        brief = json.loads(
            (ROOT / "config/frontier-gtm-brief-b2b-frozen.json").read_text(
                encoding="utf-8"
            )
        )
        with tempfile.TemporaryDirectory() as temporary:
            result = compile_realtime_preset_campaign(brief, temporary)
            self.assertEqual(result["schema"], "ProofLaunchRealtimePresetCampaignV8")
            orchestration = result["agent_orchestration"]
            self.assertEqual(orchestration["schema"], "ProofLaunchRealtimeCreativeCouncilV1")
            self.assertEqual(orchestration["candidate_blueprint_count"], 12)
            self.assertEqual(orchestration["blueprint_design_space"], 96_000_000)
            self.assertEqual(len(orchestration["node_receipts"]), 6)
            self.assertTrue(orchestration["deterministic_agent_node_execution_observed"])
            self.assertFalse(orchestration["frontier_model_agent_execution_observed"])
            self.assertEqual(orchestration["external_action_count"], 0)
            imagegen_skill = orchestration["imagegen_skill_contract"]
            self.assertEqual(imagegen_skill["skill_id"], "imagegen")
            self.assertEqual(imagegen_skill["capability_state"], "active")
            self.assertEqual(imagegen_skill["placement_brief_count"], 6)
            self.assertEqual(len({row["brief_sha256"] for row in imagegen_skill["placement_briefs"]}), 6)
            self.assertFalse(imagegen_skill["hard_gates"]["reused_visual_source_allowed"])
            finalists = orchestration["territories"]
            self.assertEqual(len(finalists), 3)
            for axis in ("hook", "narrative", "visual", "tone"):
                self.assertEqual(len({row["axis_signature"][axis] for row in finalists}), 3)
            assets = result["rendered_media"]["assets"]
            self.assertEqual(len(assets), 6)
            self.assertEqual(
                [asset["media_type"] for asset in assets],
                ["image/png", "image/png", "image/png", "video/mp4", "video/mp4", "video/mp4"],
            )
            for asset in assets:
                path = Path(temporary) / result["content_sha256"] / asset["filename"]
                self.assertTrue(path.is_file())
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), asset["content_sha256"])
            self.assertTrue((Path(temporary) / result["content_sha256"] / assets[0]["filename"]).read_bytes().startswith(b"\x89PNG"))
            for video_asset in assets[-3:]:
                video = Path(temporary) / result["content_sha256"] / video_asset["filename"]
                video_bytes = video.read_bytes()
                self.assertEqual(video_bytes[4:8], b"ftyp")
                self.assertIn(b"avc1", video_bytes)
                self.assertIn(b"mp4a", video_bytes)
                self.assertGreaterEqual(video_asset["duration_seconds"], 8)
                reader = imageio.get_reader(video)
                try:
                    metadata = reader.get_meta_data()
                    fps = float(metadata["fps"])
                    sampled_hashes = []
                    for shot_index in range(6):
                        second = (shot_index + 0.5) * video_asset["duration_seconds"] / 6
                        frame = reader.get_data(round(second * fps))
                        thumbnail = Image.fromarray(frame).resize((48, 48), Image.Resampling.LANCZOS)
                        sampled_hashes.append(hashlib.sha256(thumbnail.tobytes()).hexdigest())
                    self.assertEqual(len(set(sampled_hashes)), 6, video_asset["role"])
                finally:
                    reader.close()
            self.assertTrue(result["rendered_media"]["binary_video_rendering_observed"])
            self.assertFalse(result["rendered_media"]["video_model_inference_claimed"])
            self.assertTrue(result["rendered_media"]["image_model_inference_claimed"])
            self.assertTrue(result["rendered_media"]["model_master_inference_pre_generated"])
            self.assertFalse(result["rendered_media"]["live_image_model_inference_this_request"])
            self.assertTrue(result["rendered_media"]["live_multiformat_adaptation_observed"])
            self.assertEqual(result["rendered_media"]["video_shot_count"], 6)
            self.assertEqual(result["rendered_media"]["video_platform_cut_count"], 3)
            self.assertEqual(result["rendered_media"]["total_rendered_video_shots"], 18)
            self.assertTrue(result["rendered_media"]["procedural_stereo_sound_design_observed"])
            self.assertEqual(result["rendered_media"]["verified_model_master_asset_count"], 6)
            self.assertEqual(result["rendered_media"]["exclusive_procedural_visual_source_count"], 0)
            self.assertEqual(len(result["rendered_media"]["exclusive_image_master_receipts"]), 3)
            self.assertEqual(len(result["rendered_media"]["exclusive_video_master_receipts"]), 3)
            image_assets = [row for row in assets if row["media_type"] == "image/png"]
            self.assertEqual(len({row["surface_id"] for row in image_assets}), 3)
            self.assertEqual(len({row["visual_grammar_id"] for row in image_assets}), 3)
            self.assertEqual(len({row["copy_system_id"] for row in image_assets}), 3)
            video_assets = [row for row in assets if row["media_type"] == "video/mp4"]
            self.assertEqual(len({row["surface_id"] for row in video_assets}), 3)
            self.assertEqual(len({row["visual_grammar_id"] for row in video_assets}), 3)
            self.assertEqual(len({row["content_sha256"] for row in assets}), 6)
            self.assertEqual(len({row["copy_payload_sha256"] for row in assets}), 6)
            self.assertEqual(len({row["placement_id"] for row in assets}), 6)
            self.assertEqual(len({row["creative_source_id"] for row in assets}), 6)
            self.assertEqual(sum(len(row["shot_source_ids"]) for row in video_assets), 18)
            self.assertEqual(len({source for row in video_assets for source in row["shot_source_ids"]}), 18)
            self.assertTrue(all(row["final_asset_reuse_allowed"] is False for row in assets))
            self.assertTrue(all(row["same_surface_cross_modality_reuse_allowed"] is False for row in assets))
            exclusivity = result["rendered_media"]["platform_asset_exclusivity"]
            self.assertTrue(exclusivity["one_image_binary_per_surface"])
            self.assertTrue(exclusivity["one_copy_arc_per_output"])
            self.assertTrue(exclusivity["one_video_binary_per_surface"])
            self.assertEqual(exclusivity["cross_surface_binary_reuse_count"], 0)
            self.assertEqual(exclusivity["cross_surface_copy_reuse_count"], 0)
            self.assertEqual(exclusivity["same_surface_cross_modality_source_reuse_count"], 0)
            self.assertEqual(exclusivity["final_asset_placement_reuse_count"], 0)
            self.assertEqual(exclusivity["creative_source_reuse_count"], 0)
            self.assertEqual(exclusivity["unique_placement_count"], 6)
            self.assertEqual(exclusivity["unique_creative_source_count"], 6)
            self.assertEqual(exclusivity["unique_video_shot_source_count"], 18)
            self.assertEqual(
                result["rendered_media"]["agent_orchestration_sha256"],
                orchestration["content_sha256"],
            )
            self.assertEqual(len(result["final_production"]["video_system"]["six_shot_plan"]), 6)
            self.assertEqual(
                result["rendered_media"]["exclusive_image_master_receipts"][0]["content_sha256"],
                "cafa211e6274f83780fa67fdaff3e128e430a12f3b08a8fb038217025b6659d0",
            )
            self.assertEqual(
                [row["stage"] for row in result["production_sequence"]],
                ["brief", "strategy", "concept", "production", "audit", "release"],
            )
            self.assertEqual(result["quality_control"]["target_tier"], "production_review_candidate")
            self.assertTrue(result["quality_control"]["mechanical_preflight_passed"])
            self.assertFalse(result["quality_control"]["human_craft_approved"])
            self.assertEqual(result["final_audit"]["status"], "mechanical_preflight_pass")

    def test_b2c_recipe_uses_consumer_native_surfaces(self) -> None:
        brief = json.loads(
            (ROOT / "config/frontier-gtm-brief-b2c-frozen.json").read_text(
                encoding="utf-8"
            )
        )
        with tempfile.TemporaryDirectory() as temporary:
            result = compile_realtime_preset_campaign(brief, temporary)
        self.assertEqual(result["strategy"]["primary_distribution_surface"], "instagram")
        self.assertEqual(result["strategy"]["secondary_distribution_surface"], "tiktok")
        self.assertEqual(result["strategy"]["playbook_archetype"], "participation_ritual")
        self.assertIn("instagram_caption", result["final_production"]["channel_copy_system"])
        self.assertIn("tiktok_creator_prompt", result["final_production"]["channel_copy_system"])
        self.assertEqual(result["strategy"]["strategy_source"], "realtime_creative_council")
        self.assertEqual(
            result["final_production"]["image_system"]["visual_grammar_id"],
            result["strategy"]["visual_grammar_id"],
        )
        self.assertTrue(any(
            brief["product_truth"] in block
            for block in result["final_production"]["primary_native_text"]["body_blocks"]
        ))

    def test_recipes_compile_materially_distinct_strategy_and_platform_copy(self) -> None:
        baseline = json.loads(
            (ROOT / "config/frontier-gtm-brief-b2b-frozen.json").read_text(
                encoding="utf-8"
            )
        )
        technical = dict(baseline)
        technical.update({
            "brief_id": "technical-proof-recipe",
            "category": "technical evaluator proof system",
            "audience": "Technical evaluators responsible for rejecting unsafe agent systems",
        })
        founder = dict(baseline)
        founder.update({
            "brief_id": "founder-narrative-recipe",
            "lifecycle": "pre_pmf",
            "category": "founder-led GTM operating system",
            "audience": "Founder operators choosing the first repeatable growth motion",
        })
        with tempfile.TemporaryDirectory() as temporary:
            technical_result = compile_realtime_preset_campaign(technical, temporary)
            founder_result = compile_realtime_preset_campaign(founder, temporary)
        self.assertEqual(technical_result["strategy"]["playbook_archetype"], "technical_rejection_test")
        self.assertEqual(founder_result["strategy"]["playbook_archetype"], "founder_conviction")
        self.assertNotEqual(
            technical_result["final_production"]["campaign_platform"],
            founder_result["final_production"]["campaign_platform"],
        )
        self.assertNotEqual(
            technical_result["final_production"]["channel_copy_system"]["linkedin_post"],
            founder_result["final_production"]["channel_copy_system"]["linkedin_post"],
        )
        self.assertNotEqual(
            technical_result["strategy"]["visual_grammar_id"],
            founder_result["strategy"]["visual_grammar_id"],
        )
        self.assertNotEqual(
            technical_result["strategy"]["narrative_grammar_id"],
            founder_result["strategy"]["narrative_grammar_id"],
        )
        self.assertNotEqual(
            technical_result["strategy"]["tone_id"],
            founder_result["strategy"]["tone_id"],
        )
        self.assertNotEqual(
            technical_result["rendered_media"]["assets"][0]["content_sha256"],
            founder_result["rendered_media"]["assets"][0]["content_sha256"],
        )

    def test_closed_brief_rejects_missing_product_truth(self) -> None:
        brief = json.loads(
            (ROOT / "config/frontier-gtm-brief-b2b-frozen.json").read_text(
                encoding="utf-8"
            )
        )
        brief.pop("product_truth")
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(RealtimePresetCampaignError, "closed contract"):
                compile_realtime_preset_campaign(brief, temporary)


if __name__ == "__main__":
    unittest.main()
