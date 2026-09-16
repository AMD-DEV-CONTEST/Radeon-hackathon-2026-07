from __future__ import annotations

import tempfile
from copy import deepcopy
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

from src.agent.critic import PlanCritic
from src.agent.intent import IntentRouter
from src.agent.orchestrator import PhotographerAgent
from src.agent.planner import PhotographyPlanner
from src.agent.field_plan import PHOTO_PLAN_SCHEMA
from src.tools.composition_checker import check_composition
from src.tools.coaching_overlay import _filter_avoid_regions, render_coaching_overlay
from src.tools.scene_analyzer import SceneAnalyzer
from src.tools.scene_analyzer import _labels_use_visible_props


ANALYSIS = {
    "scene": "A family portrait in a public park.",
    "subject": "An adult and child interacting naturally.",
    "environment": "Green grass and trees create layered outdoor context.",
    "relationship": "The people are the focus while the park supplies a sense of place.",
    "composition": "The pair sits near a third with open space and visible background depth.",
            "recommendation": "Use a lower camera position, soft side light, and a clean medium frame.",
            "people_boxes": [[300, 180, 520, 900], [500, 300, 680, 900]],
            "action_labels": [
                {
                    "person_indices": [0],
                    "anchor": "head",
                    "text": "Adult turns toward child",
                },
                {
                    "person_indices": [1],
                    "anchor": "head",
                    "text": "Child looks up",
                },
                {
                    "person_indices": [0, 1],
                    "anchor": "between",
                    "text": "Hold hands naturally",
                },
            ],
            "recommended_crop": [180, 80, 850, 950],
            "avoid_regions": [[800, 100, 980, 400]],
            "camera_move": "left",
            "subject_move": "right",
            "light_direction": "soft",
            "body_pose": {
                "body_rotation": "Turn the body 15 degrees toward the camera",
                "shoulder": "Lower the shoulders instead of shrugging",
                "head_direction": "Turn the head gently toward the camera",
            },
            "hands": {"object": "none", "position": "Hold hands naturally"},
            "gaze": {"direction": "Look at each other", "expression": "Smile naturally"},
            "photographer": {
                "position": "To the subjects' front-left",
                "distance": "2 to 3 meters",
                "angle": "Keep the camera level",
                "height": "Near the child's eye level",
                "background": "Avoid tourists and preserve the grass and trees",
                "purpose": "Preserve the family interaction and park context",
            },
}


class FakeVision:
    def analyze(self, image_path: str | Path, prompt: str | None = None) -> dict:
        return {
            **ANALYSIS,
            "_metrics": {
                "gpu": "AMD Radeon Graphics",
                "inference_seconds": 1.25,
                "hip": "7.2",
            },
        }

    def review_preview(
        self,
        reference_path: str | Path,
        preview_path: str | Path,
        user_request: str,
        plan: dict,
    ) -> dict:
        return {
            "subject_consistency": "The subject type is preserved.",
            "environment_consistency": "The park remains recognizable.",
            "pose_and_action_alignment": "The requested action is visible.",
            "composition_and_lighting_alignment": "The direction is followed.",
            "artifact_check": "No blocking artifact.",
            "issues": [],
            "verdict": "pass",
            "review_seconds": 0.1,
        }


class RetryVision(FakeVision):
    def __init__(self, always_missing: bool = False) -> None:
        self.calls = 0
        self.always_missing = always_missing

    def analyze(self, image_path: str | Path, prompt: str | None = None) -> dict:
        self.calls += 1
        result = super().analyze(image_path, prompt)
        if self.calls == 1 or self.always_missing:
            result["composition"] = ""
            result["recommendation"] = ""
        return result


class FakeSegmenter:
    def segment(self, image: Image.Image, primary_boxes: list[list[int]]) -> dict:
        mask = Image.new("L", image.size, 0)
        draw = ImageDraw.Draw(mask)
        for box in primary_boxes:
            x1 = int(box[0] * image.width / 1000)
            y1 = int(box[1] * image.height / 1000)
            x2 = int(box[2] * image.width / 1000)
            y2 = int(box[3] * image.height / 1000)
            draw.ellipse((x1, y1, x2, y2), fill=255)
        return {
            "status": "generated",
            "masks": [mask],
            "model": "fake-person-segmenter",
            "people_matched": 1,
            "inference_seconds": 0.01,
        }


class AgentCoreTests(unittest.TestCase):
    def test_phone_prop_requires_phone_hand_label(self) -> None:
        self.assertFalse(
            _labels_use_visible_props(
                [
                    {
                        "person_indices": [0],
                        "anchor": "hands",
                        "text": "Let both hands hang",
                    }
                ],
                ["phone", "backpack"],
            )
        )
        self.assertTrue(
            _labels_use_visible_props(
                [
                    {
                        "person_indices": [0],
                        "anchor": "hands",
                        "text": "Lower the phone",
                    }
                ],
                ["phone", "backpack"],
            )
        )

    def test_distraction_regions_do_not_cover_primary_people(self) -> None:
        kept, suppressed = _filter_avoid_regions(
            [[0, 300, 120, 800], [200, 350, 420, 740]],
            [[245, 195, 900, 840]],
        )
        self.assertEqual(kept, [[0, 300, 120, 800]])
        self.assertEqual(suppressed, 1)

    def test_overlay_prefers_vlm_action_labels(self) -> None:
        analysis = {
            **ANALYSIS,
            "subject": "A single woman holding a smartphone.",
            "relationship": "One foreground subject.",
            "people_boxes": [[250, 150, 800, 950]],
            "action_labels": [
                {
                    "person_indices": [0],
                    "anchor": "hands",
                    "text": "Lower the phone",
                },
                {
                    "person_indices": [0],
                    "anchor": "head",
                    "text": "Look toward the camera",
                },
            ],
        }
        plan = PhotographyPlanner().plan(
            analysis,
            "Teach me to recreate this photo",
            IntentRouter().route("shoot"),
        )
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.jpg"
            output = Path(directory) / "overlay.png"
            Image.new("RGB", (640, 480), (70, 90, 80)).save(source)
            result = render_coaching_overlay(
                source,
                analysis,
                plan,
                output,
                segmenter=FakeSegmenter(),
            )
        self.assertEqual(result["action_tag_source"], "vlm")
        self.assertEqual(
            result["action_tags"],
            ["Lower the phone", "Look toward the camera"],
        )

    def test_overlay_fills_phone_label_after_vlm_prop_conflict(self) -> None:
        analysis = {
            **ANALYSIS,
            "subject": "A single woman holding a smartphone.",
            "relationship": "One foreground subject.",
            "people_boxes": [[250, 150, 800, 950]],
            "visible_props": ["smartphone"],
            "action_labels": [
                {
                    "person_indices": [0],
                    "anchor": "body",
                    "text": "Lower shoulders and turn slightly",
                },
                {
                    "person_indices": [0],
                    "anchor": "head",
                    "text": "Look toward the camera",
                },
            ],
        }
        plan = PhotographyPlanner().plan(
            analysis,
            "Teach me to recreate this photo",
            IntentRouter().route("shoot"),
        )
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.jpg"
            output = Path(directory) / "overlay.png"
            Image.new("RGB", (640, 480), (70, 90, 80)).save(source)
            result = render_coaching_overlay(
                source,
                analysis,
                plan,
                output,
                segmenter=FakeSegmenter(),
            )
        self.assertEqual(
            result["action_tag_source"],
            "vlm+validated_fallback",
        )
        self.assertIn("Phone: lower it slightly", result["action_tags"])

    def test_intent_modes(self) -> None:
        router = IntentRouter()
        self.assertEqual(router.route("Please retouch and color grade")["task_type"], "photo_edit")
        self.assertEqual(router.route("Design a reshoot camera angle and pose")["task_type"], "shooting")
        self.assertEqual(router.route("Shoot first, then color grade")["task_type"], "hybrid")
        self.assertEqual(
            router.route("Only fix exposure and color")["task_type"], "photo_edit"
        )
        self.assertEqual(router.route("Make it feel natural")["task_type"], "shooting")

    def test_all_plan_modes_pass_critic(self) -> None:
        router = IntentRouter()
        planner = PhotographyPlanner()
        critic = PlanCritic()
        for request in ("Reshoot this", "Retouch this", "Reshoot and color grade this"):
            with self.subTest(request=request):
                intent = router.route(request)
                plan = planner.plan(ANALYSIS, request, intent)
                self.assertEqual(critic.review(ANALYSIS, plan)["status"], "pass")

    def test_critic_rejects_missing_evidence(self) -> None:
        review = PlanCritic().review({}, {"mode": "shooting"})
        self.assertEqual(review["status"], "needs_review")
        self.assertGreaterEqual(len(review["issues"]), 4)

    def test_composition_checker_has_evidence(self) -> None:
        result = check_composition(ANALYSIS)
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["actionability_score"], 100)
        self.assertGreater(result["evidence"]["composition_characters"], 20)

    def test_end_to_end_orchestrator_with_injected_vision(self) -> None:
        analyzer = SceneAnalyzer(vision=FakeVision())
        agent = PhotographerAgent(analyzer=analyzer)
        with tempfile.NamedTemporaryFile(suffix=".jpg") as image:
            result = agent.run(image.name, "Create a natural family portrait shooting plan.")
        self.assertEqual(result["schema_version"], "3.0")
        self.assertEqual(result["critic"]["status"], "pass")
        self.assertEqual(result["metrics"]["gpu"], "AMD Radeon Graphics")
        self.assertEqual(
            [step["node"] for step in result["agent_trace"]],
            [
                "intent_router",
                "vision_analyzer",
                "composition_checker",
                "photography_planner",
                "plan_critic",
                "pose_analyzer",
            ],
        )
        self.assertNotIn("_metrics", result["analysis"])
        self.assertEqual(
            [call["tool"] for call in result["tool_calls"]],
            [
                "intent_router",
                "vision_analyzer",
                "composition_checker",
                "photography_planner",
                "plan_critic",
                "pose_analyzer",
            ],
        )
        self.assertTrue(result["permission_audit"])
        self.assertFalse(result["privacy"]["external_network_allowed"])

    def test_agent_rejects_empty_request_and_missing_image(self) -> None:
        agent = PhotographerAgent(analyzer=SceneAnalyzer(vision=FakeVision()))
        with tempfile.NamedTemporaryFile(suffix=".jpg") as image:
            with self.assertRaisesRegex(ValueError, "cannot be empty"):
                agent.run(image.name, " ")
        with self.assertRaises(FileNotFoundError):
            agent.run("/does/not/exist.jpg", "shooting plan")

    def test_concept_generation_is_disabled(self) -> None:
        analyzer = SceneAnalyzer(vision=FakeVision())
        agent = PhotographerAgent(analyzer=analyzer)
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "reference.jpg"
            preview = Path(directory) / "preview.png"
            Image.new("RGB", (128, 96), (80, 120, 60)).save(image)
            with self.assertRaisesRegex(ValueError, "disabled"):
                agent.run(
                    image,
                    "Create a natural family portrait.",
                    generate_preview=True,
                    preview_path=preview,
                )
            self.assertFalse(preview.exists())

    def test_deterministic_ai_photography_execution_card(self) -> None:
        analyzer = SceneAnalyzer(vision=FakeVision())
        agent = PhotographerAgent(analyzer=analyzer)
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "reference.jpg"
            overlay = Path(directory) / "coaching.png"
            Image.new("RGB", (640, 480), (70, 110, 65)).save(image)
            with patch(
                "src.tools.person_segmenter.get_shared_person_segmenter",
                return_value=FakeSegmenter(),
            ):
                result = agent.run(
                    image,
                    "Teach me how to reshoot this portrait.",
                    generate_overlay=True,
                    overlay_path=overlay,
                )
            self.assertTrue(overlay.is_file())
            self.assertEqual(result["pose_card"]["status"], "generated")
            self.assertEqual(
                result["pose_card"]["render_mode"],
                "editorial_photography_execution_poster",
            )
            self.assertEqual((result["pose_card"]["width"], result["pose_card"]["height"]), (1600, 1100))
            self.assertTrue(result["pose_card"]["source_preserved"])
            self.assertTrue(result["pose_card"]["source_pixels_in_output"])
            self.assertFalse(result["pose_card"]["image_generation_model_used"])
            self.assertFalse(result["pose_card"]["vlm_generated_image"])
            self.assertEqual(
                result["pose_card"]["sections"],
                ["why_beautiful", "photographer", "subject_pose"],
            )
            self.assertEqual(
                result["pose_card"]["person_outline"]["people_matched"],
                1,
            )
            self.assertIn("body_pose", result["pose_json"])
            self.assertIn("photographer", result["pose_json"])
            self.assertEqual(result["preview"]["status"], "disabled")
            self.assertEqual(
                result["tool_calls"][-1]["tool"],
                "pose_card_renderer",
            )
            self.assertEqual(
                result["tool_calls"][-1]["status"],
                "completed",
            )

    def test_lens_and_direction_contract(self) -> None:
        plan = PhotographyPlanner().plan(
            ANALYSIS, "Create a portrait.", IntentRouter().route("shoot")
        )
        self.assertEqual(set(plan), set(PHOTO_PLAN_SCHEMA))
        self.assertIn("lens", plan["advanced_parameters"])
        self.assertEqual(len(plan["photographer_instruction"]["avoid"]), 2)
        broken = deepcopy(plan)
        broken["photographer_instruction"]["position"] = "To the subject's front-left"
        review = PlanCritic().review(ANALYSIS, broken)
        self.assertEqual(review["status"], "needs_review")

    def test_background_crowd_does_not_turn_single_portrait_into_group(self) -> None:
        analysis = {
            **ANALYSIS,
            "scene": "A single urban portrait with a blurred crowd in the background.",
            "subject": "One woman holding a phone.",
            "relationship": "The woman is the only primary subject; the crowd is environmental context.",
            "people_boxes": [[200, 150, 800, 950]],
            "visible_props": ["phone"],
        }
        plan = PhotographyPlanner().plan(analysis, "Teach me to reshoot this", IntentRouter().route("shoot"))
        direction = plan["subject_instruction"]
        self.assertIn("phone", direction["hand_action"].lower())
        self.assertNotIn("everyone", direction["interaction"].lower())

    def test_missing_visual_fields_trigger_one_retry(self) -> None:
        vision = RetryVision()
        agent = PhotographerAgent(analyzer=SceneAnalyzer(vision=vision))
        with tempfile.NamedTemporaryFile(suffix=".jpg") as image:
            result = agent.run(image.name, "Create a portrait plan.")
        self.assertEqual(vision.calls, 2)
        self.assertEqual(result["critic"]["status"], "pass")
        self.assertEqual(result["metrics"]["vision_attempts"], 2)
        self.assertIn(
            "vision_missing_field_retry",
            [step["node"] for step in result["agent_trace"]],
        )

if __name__ == "__main__":
    unittest.main()
