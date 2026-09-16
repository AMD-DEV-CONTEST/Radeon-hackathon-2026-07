from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from src.tools.pose_card_renderer import _guidance_copy, render_pose_card
from src.vision.pose_analyzer import PoseAnalyzer, normalize_pose_fields, pose_schema_complete


POSE = {
    "body_pose": {
        "body_rotation": "Turn the body 15 degrees toward the camera",
        "shoulder": "Lower the shoulders instead of shrugging",
        "head_direction": "Turn the head gently toward the camera",
    },
    "hands": {"object": "phone", "position": "Lower the phone naturally"},
    "gaze": {"direction": "Look as if you just noticed the photographer", "expression": "smile naturally"},
    "photographer": {
        "position": "Stand to the subject's front-left",
        "distance": "1.5 to 2 meters",
        "angle": "Keep the camera level",
        "height": "Slightly above eye level",
        "background": "Preserve the glass architecture lines",
        "purpose": "Preserve the profile and background relationship",
    },
}

ANALYSIS = {
    "scene": "A candid urban street portrait",
    "relationship": "The subject and glass building create an everyday city relationship",
    "composition": "The subject sits on the right while background lines create depth",
    "visible_props": ["phone"],
    "people_boxes": [[200, 100, 800, 950]],
    **POSE,
}

PLAN = {
    "model_direction": {},
    "photographer_direction": {},
}


class FakeSegmenter:
    def __init__(self, variant: int = 0) -> None:
        self.variant = variant
        self.primary_boxes: list[list[int]] = []

    def segment(self, image: Image.Image, primary_boxes: list[list[int]]) -> dict:
        self.primary_boxes = primary_boxes
        mask = Image.new("L", image.size, 0)
        draw = ImageDraw.Draw(mask)
        if self.variant:
            draw.rectangle((180, 35, 430, 450), fill=255)
        else:
            draw.ellipse((130, 25, 470, 460), fill=255)
        return {
            "status": "generated",
            "masks": [mask],
            "people_matched": 1,
            "model": "fake-local-mask",
            "inference_seconds": 0.01,
        }


class PoseCardTests(unittest.TestCase):
    def test_group_guidance_does_not_use_single_portrait_phone_copy(self) -> None:
        pose_json = PoseAnalyzer().build(ANALYSIS, PLAN)
        group_analysis = {
            **ANALYSIS,
            "scene": "A graduation ceremony group portrait",
            "subject": "Three graduates wearing academic gowns",
            "people_boxes": [
                [300, 500, 430, 950],
                [435, 500, 565, 950],
                [570, 500, 700, 950],
            ],
        }
        copy = _guidance_copy(pose_json, analysis=group_analysis)
        self.assertEqual(copy["pose"]["gaze"], "Everyone looks toward the photographer")
        self.assertEqual(copy["pose"]["hand_title"], "Hands")
        self.assertNotIn("phone", copy["pose"]["summary"].lower())
        self.assertNotIn("position", copy["photographer"])
        self.assertIn("graduation banner", copy["photographer"]["background"].lower())

    def test_local_primary_subject_count_ignores_background_bystanders(self) -> None:
        analysis = {
            **ANALYSIS,
            "people_boxes": [
                [100, 100, 700, 950],
                [10, 500, 80, 900],
                [800, 520, 880, 900],
            ],
            "_local_person_geometry": {
                "people_count": 1,
                "visible_people_count": 3,
            },
        }
        pose_json = PoseAnalyzer().build(analysis, PLAN)
        copy = _guidance_copy(pose_json, analysis=analysis)
        self.assertNotIn("everyone", copy["pose"]["gaze"].lower())
        self.assertNotIn("people", copy["pose"]["summary"].lower())

    def test_pose_schema_is_strict_and_complete(self) -> None:
        normalized = normalize_pose_fields({**POSE, "unexpected": "drop me"})
        self.assertNotIn("unexpected", normalized)
        self.assertTrue(pose_schema_complete(POSE))
        self.assertFalse(pose_schema_complete({"body_pose": {}}))

    def test_pose_analyzer_preserves_complete_vlm_json(self) -> None:
        result = PoseAnalyzer().build(ANALYSIS, PLAN)
        self.assertEqual(result["source"], "planner+vlm")
        self.assertEqual(result["hands"]["position"], "Lower the phone naturally")
        self.assertEqual(result["photographer"]["angle"], "Keep the camera level")

    def test_guidance_copy_preserves_low_camera_height(self) -> None:
        low_pose = PoseAnalyzer().build(ANALYSIS, PLAN)
        low_pose["photographer"].update(
            {
                "distance": "About 3 to 4 meters",
                "angle": "Aim the camera slightly upward",
                "height": "Place the camera near the ground and aim upward",
            }
        )
        copy = _guidance_copy(low_pose, analysis=ANALYSIS)
        self.assertEqual(
            copy["photographer"]["height"],
            "Place the camera near the ground and aim upward",
        )
        self.assertNotIn("eye level", copy["photographer"]["height"])

    def test_pose_schema_drops_legacy_relative_position(self) -> None:
        normalized = normalize_pose_fields(POSE)
        self.assertNotIn("position", normalized["photographer"])
        pose_json = PoseAnalyzer().build(ANALYSIS, PLAN)
        copy = _guidance_copy(pose_json, analysis=ANALYSIS)
        self.assertNotIn("position", copy["photographer"])

    def test_no_prop_becomes_concrete_hand_action_not_empty_object_label(self) -> None:
        no_prop_analysis = {
            **ANALYSIS,
            "visible_props": [],
            "hands": {
                "object": "No visible prop",
                "position": "Let one hand hang naturally and rest the other at the side",
            },
        }
        pose_json = PoseAnalyzer().build(no_prop_analysis, PLAN)
        copy = _guidance_copy(pose_json, analysis=no_prop_analysis)
        self.assertEqual(copy["pose"]["hand_title"], "Hands")
        self.assertEqual(
            copy["pose"]["hands"],
            "Let one hand hang naturally and rest the other at the side",
        )
        self.assertNotIn("No visible prop", copy["pose"].values())

    def test_renderer_does_not_show_hallucinated_phone_without_visible_evidence(self) -> None:
        analysis = {
            **ANALYSIS,
            "visible_props": ["black top", "black pants"],
            "hands": {
                "object": "phone",
                "position": "Give the hands a resting place behind the body",
            },
        }
        pose_json = PoseAnalyzer().build(analysis, PLAN)
        copy = _guidance_copy(pose_json, analysis=analysis)
        self.assertEqual(copy["pose"]["hand_title"], "Hands")
        self.assertNotIn("phone", copy["pose"]["hands"].lower())

    def test_renderer_is_deterministic_and_mask_specific(self) -> None:
        pose_json = PoseAnalyzer().build(ANALYSIS, PLAN)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.jpg"
            Image.new("RGB", (600, 480), (35, 70, 90)).save(source)
            outputs = [root / "first.png", root / "second.png", root / "variant.png"]
            for output in outputs[:2]:
                result = render_pose_card(
                    source, ANALYSIS, PLAN, pose_json, output, segmenter=FakeSegmenter()
                )
                self.assertEqual((result["width"], result["height"]), (1600, 1100))
                self.assertFalse(result["image_generation_model_used"])
                self.assertEqual(result["palette"], "morandi_dark")
                self.assertEqual(result["layout_style"], "editorial_morandi_poster")
                self.assertEqual(result["render_mode"], "editorial_photography_execution_poster")
                self.assertEqual(result["outline_style"], "high_contrast_dual_vector_contour_with_multiscale_details")
                self.assertEqual(result["label_anchor_mode"], "real_mask_intersection")
                self.assertEqual(result["detail_mode"], "multiscale_face_hand_emphasis")
                self.assertEqual(result["subject_scale"], 1.1)
            render_pose_card(
                source,
                ANALYSIS,
                PLAN,
                pose_json,
                outputs[2],
                segmenter=FakeSegmenter(variant=1),
            )
            hashes = [hashlib.sha256(path.read_bytes()).hexdigest() for path in outputs]
            self.assertEqual(hashes[0], hashes[1])
            self.assertNotEqual(hashes[0], hashes[2])

    def test_renderer_prefers_locally_calibrated_primary_boxes(self) -> None:
        pose_json = PoseAnalyzer().build(ANALYSIS, PLAN)
        analysis = {
            **ANALYSIS,
            "people_boxes": [[10, 10, 80, 200], [200, 100, 800, 950]],
            "_local_person_geometry": {
                "people_count": 1,
                "visible_people_count": 2,
                "person_boxes": [[200, 100, 800, 950]],
            },
        }
        segmenter = FakeSegmenter()
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.jpg"
            output = Path(directory) / "card.png"
            Image.new("RGB", (600, 480), (35, 70, 90)).save(source)
            render_pose_card(
                source,
                analysis,
                PLAN,
                pose_json,
                output,
                segmenter=segmenter,
            )
        self.assertEqual(segmenter.primary_boxes, [[200, 100, 800, 950]])


if __name__ == "__main__":
    unittest.main()
