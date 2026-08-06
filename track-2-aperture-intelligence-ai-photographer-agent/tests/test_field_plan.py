from __future__ import annotations

from copy import deepcopy
import unittest

from src.agent.critic import PlanCritic
from src.agent.field_plan import PHOTO_PLAN_SCHEMA
from src.agent.planner import PhotographyPlanner


SINGLE = {
    "scene": "An urban night portrait with ambient light reflected in a glass facade.",
    "subject": "A woman holding a phone stands in the foreground.",
    "environment": "The background contains a glass building and passing pedestrians.",
    "relationship": "The subject is the visual center while the city conveys an everyday story.",
    "composition": "A slightly angled half-body portrait preserves expression and urban depth.",
    "recommendation": "Use a slight side angle and preserve the glass reflections.",
    "people_boxes": [[230, 120, 790, 950]],
    "visible_props": ["phone"],
    "visual_risks": ["a background pedestrian touching the subject outline", "a building line crossing the subject's head"],
    "body_pose": {"body_rotation": "Keep the body slightly side-on", "head_direction": "Turn the head gently toward the photographer"},
    "hands": {"position": "Hold the phone near the waist"},
    "gaze": {"direction": "Look back as if you just noticed the photographer"},
    "photographer": {
        "position": "45 degrees to the subject's front-left",
        "distance": "About 1.5 meters",
        "angle": "Use a slight side angle",
        "height": "Close to the subject's eye level",
        "background": "Preserve the glass reflections",
    },
}

GROUP = {
    "scene": "A graduation group portrait outside a campus entrance.",
    "subject": "Three graduates in academic gowns stand in one row.",
    "environment": "A graduation banner hangs above the entrance with occasional pedestrians behind it.",
    "relationship": "The three people form the visual center while the banner establishes the graduation setting.",
    "composition": "The row creates a stable center and the building entrance provides a symmetrical frame.",
    "recommendation": "Keep the camera level and preserve the graduation banner.",
    "people_boxes": [[140, 200, 360, 900], [380, 160, 620, 900], [640, 190, 860, 900]],
    "visible_props": ["academic gowns", "graduation caps"],
    "visual_risks": ["a background pedestrian appearing between the three people", "the banner line overlapping a subject's head"],
    "body_pose": {"body_rotation": "Face all three bodies toward the photographer", "head_direction": "Keep each head upright"},
    "hands": {"position": "Rest arms at the sides"},
    "gaze": {"direction": "Look toward the photographer together"},
    "photographer": {
        "position": "Directly in front of the group",
        "distance": "About 3 meters",
        "angle": "Keep the camera level",
        "height": "Close to the center subject's eye level",
        "background": "Preserve the banner and entrance",
    },
}

LOW_ANGLE_FULL_BODY = {
    "scene": "An outdoor full-body portrait with a large area of blue sky above the subject.",
    "subject": "A girl is visible from head to toe in the center of the frame.",
    "environment": "The sky fills most of the background and the horizon sits near the bottom edge.",
    "relationship": "The subject is central while the low horizon and open sky emphasize vertical scale.",
    "composition": "A low upward full-body frame keeps the subject complete and preserves expansive sky.",
    "recommendation": "Place the camera near the ground, aim upward, and preserve the sky.",
    "people_boxes": [[380, 130, 650, 900]],
    "visible_props": ["bouquet"],
    "visual_risks": ["the bright sky making the subject's face too dark", "the subject's feet too close to the frame edge"],
    "body_pose": {"body_rotation": "Turn slightly toward the photographer", "head_direction": "Turn the head toward the distance"},
    "hands": {"position": "Shade the eyes with one hand and hold the bouquet with the other"},
    "gaze": {"direction": "Look into the distance"},
    "photographer": {
        "position": "Directly in front of the subject",
        "distance": "About 1 meter",
        "angle": "Keep the camera level",
        "height": "Close to the subject's eye level",
        "background": "Preserve the sky",
    },
    "shot_geometry": {
        "framing": "half_body",
        "camera_height": "ground",
        "camera_tilt": "up",
        "subject_frame_height_ratio": 0.77,
    },
}


class FieldPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.planner = PhotographyPlanner()
        self.critic = PlanCritic()

    def test_fixed_schema_and_critic_contract(self) -> None:
        plan = self.planner.plan(SINGLE, "Teach me to recreate this photo", {"task_type": "shooting"})
        self.assertEqual(set(plan), set(PHOTO_PLAN_SCHEMA))
        for section in ("why_this_photo_works", "photographer_instruction", "subject_instruction", "advanced_parameters"):
            self.assertEqual(set(plan[section]), set(PHOTO_PLAN_SCHEMA[section]))
        self.assertEqual(len(plan["shooting_sequence"]), 4)
        self.assertEqual(len(plan["photographer_instruction"]["avoid"]), 2)
        review = self.critic.review(SINGLE, plan)
        self.assertEqual(review["status"], "pass", review["issues"])
        self.assertEqual(len(review["checks_run"]), 7)

    def test_single_and_group_guidance_changes_with_image(self) -> None:
        single = self.planner.plan(SINGLE, "Teach me to recreate this photo", {"task_type": "shooting"})
        group = self.planner.plan(GROUP, "Teach me to recreate this photo", {"task_type": "shooting"})
        self.assertNotEqual(single["photo_intent"], group["photo_intent"])
        self.assertNotIn("position", single["photographer_instruction"])
        self.assertNotIn("position", group["photographer_instruction"])
        self.assertNotEqual(
            single["photographer_instruction"]["distance"],
            group["photographer_instruction"]["distance"],
        )
        self.assertIn("phone", single["subject_instruction"]["hand_action"].lower())
        self.assertIn("three people", group["subject_instruction"]["body_pose"].lower())
        self.assertNotIn("phone", group["subject_instruction"]["hand_action"].lower())
        self.assertNotEqual(
            single["photographer_instruction"]["avoid"],
            group["photographer_instruction"]["avoid"],
        )

    def test_group_without_props_explains_relationship_instead_of_inventing_object(self) -> None:
        no_prop_group = deepcopy(GROUP)
        no_prop_group.update(
            {
                "scene": "Two friends pose together in a park.",
                "subject": "Two people stand close together in the center.",
                "environment": "Trees and a path fill the background.",
                "relationship": "The two people are central while the park establishes the meeting place.",
                "composition": "Their close spacing forms a stable center and the path adds depth.",
                "recommendation": "Keep the camera level and preserve the park setting.",
                "visible_props": [],
            }
        )
        no_prop_group["people_boxes"] = [
            [220, 160, 480, 920],
            [500, 170, 760, 920],
        ]
        plan = self.planner.plan(no_prop_group, "Teach me to recreate this photo")
        prop_usage = plan["why_this_photo_works"]["prop_usage"]
        self.assertIn("No extra prop", prop_usage)
        self.assertIn("natural interaction", prop_usage)

    def test_short_no_prop_labels_become_complete_explanations(self) -> None:
        analysis = deepcopy(SINGLE)
        analysis.update(
            {
                "scene": "Outdoor portrait",
                "relationship": "The subject is centered",
                "composition": "Full-body framing",
                "visible_props": [
                    "black sleeveless shirt",
                    "black pants",
                    "black belt buckle",
                    "watch",
                    "tie",
                ],
            }
        )
        plan = self.planner.plan(analysis, "Teach me to recreate this photo")
        why = plan["why_this_photo_works"]
        self.assertTrue(all(len(str(value)) >= 8 for value in why.values()))
        self.assertIn("No extra prop", why["prop_usage"])
        self.assertNotIn("shirt", why["prop_usage"])
        self.assertEqual(self.critic.review(analysis, plan)["status"], "pass")

    def test_hallucinated_hand_object_is_rejected_without_visible_prop_evidence(self) -> None:
        analysis = deepcopy(SINGLE)
        analysis["visible_props"] = ["black sleeveless top", "black pants"]
        analysis["hands"] = {
            "object": "phone",
            "position": "Place the phone in a pocket",
        }
        plan = self.planner.plan(analysis, "Teach me to recreate this photo")
        self.assertIn("No extra prop", plan["why_this_photo_works"]["prop_usage"])
        self.assertNotIn("phone", plan["subject_instruction"]["hand_action"].lower())

    def test_critic_rejects_vague_contradictory_and_ungrounded_plan(self) -> None:
        broken = deepcopy(self.planner.plan(SINGLE, "Teach me to recreate this photo"))
        broken["why_this_photo_works"]["atmosphere"] = "Nice"
        broken["photographer_instruction"]["distance"] = "A suitable distance"
        broken["photographer_instruction"]["angle"] = "Adjust the camera"
        broken["photographer_instruction"]["avoid"] = ["Avoid ocean waves soaking shoes", "Avoid clouds hiding the snowy mountain"]
        broken["subject_instruction"]["body_pose"] = "Stand naturally"
        broken["subject_instruction"]["eye_direction"] = "Look at the camera"
        review = self.critic.review(SINGLE, broken)
        self.assertEqual(review["status"], "needs_review")
        joined = " ".join(review["issues"])
        for evidence in ("fully explain", "distance", "vague", "not grounded"):
            self.assertIn(evidence, joined)

    def test_public_plan_rejects_unreliable_relative_position_field(self) -> None:
        plan = self.planner.plan(SINGLE, "Teach me to recreate this photo")
        self.assertNotIn("position", plan["photographer_instruction"])
        broken = deepcopy(plan)
        broken["photographer_instruction"]["position"] = "45 degrees to the subject's front-left"
        review = self.critic.review(SINGLE, broken)
        self.assertEqual(review["status"], "needs_review")
        self.assertIn("fixed schema", " ".join(review["issues"]).lower())

    def test_one_bounded_refinement_repairs_invalid_plan(self) -> None:
        plan = self.planner.plan(GROUP, "Teach me to recreate this photo")
        broken = deepcopy(plan)
        broken["subject_instruction"] = {}
        broken["shooting_sequence"] = []
        review = self.critic.review(GROUP, broken)
        repaired = self.planner.refine(
            broken,
            review["issues"],
            analysis=GROUP,
            user_request="Teach me to recreate this photo",
        )
        self.assertEqual(self.critic.review(GROUP, repaired)["status"], "pass")

    def test_low_angle_full_body_geometry_is_calibrated(self) -> None:
        plan = self.planner.plan(
            LOW_ANGLE_FULL_BODY,
            "Teach me to recreate this style",
            {"task_type": "shooting"},
        )
        photographer = plan["photographer_instruction"]
        self.assertEqual(photographer["distance"], "About 3 to 4 meters")
        self.assertIn("near the ground", photographer["height"])
        self.assertIn("upward", photographer["angle"])
        self.assertNotIn("eye level", photographer["height"])
        self.assertEqual(
            self.critic.review(LOW_ANGLE_FULL_BODY, plan)["status"],
            "pass",
        )

    def test_half_body_level_view_does_not_become_low_angle_from_waist_label(self) -> None:
        analysis = deepcopy(SINGLE)
        analysis["shot_geometry"] = {
            "framing": "half_body",
            "camera_height": "waist",
            "camera_tilt": "level",
        }
        analysis["_local_person_geometry"] = {
            "people_count": 1,
            "full_body_candidate": False,
            "largest_height_ratio": 0.9,
        }
        analysis["photographer"]["height"] = "About 1 meter"
        plan = self.planner.plan(analysis, "Teach me to recreate this photo")
        photographer = plan["photographer_instruction"]
        self.assertEqual(photographer["height"], "Close to the subject's eye level")
        self.assertNotIn("upward", photographer["angle"])

    def test_half_body_vlm_distance_and_one_word_actions_are_calibrated(self) -> None:
        analysis = deepcopy(SINGLE)
        analysis["shot_geometry"] = {
            "framing": "half_body",
            "camera_height": "waist",
            "camera_tilt": "level",
        }
        analysis["_local_person_geometry"] = {
            "people_count": 1,
            "visible_people_count": 3,
            "largest_aspect_ratio": 1.0,
            "largest_height_ratio": 0.77,
            "full_body_candidate": False,
        }
        analysis["photographer"].update(
            {"distance": "1 meter", "angle": "level", "height": "waist"}
        )
        analysis["body_pose"] = {
            "body_rotation": "stay",
            "shoulder": "stay",
            "head_direction": "stay",
        }
        analysis["gaze"] = {"direction": "stay", "expression": "smile"}
        plan = self.planner.plan(analysis, "Teach me to recreate this photo")
        photographer = plan["photographer_instruction"]
        subject = plan["subject_instruction"]
        self.assertEqual(photographer["distance"], "About 1.5 to 2 meters")
        self.assertEqual(photographer["height"], "Close to the subject's eye level")
        self.assertGreaterEqual(len(subject["body_pose"].split()), 6)
        self.assertGreaterEqual(len(subject["head_direction"].split()), 6)
        self.assertGreaterEqual(len(subject["eye_direction"].split()), 6)
        self.assertEqual(self.critic.review(analysis, plan)["status"], "pass")

    def test_full_body_downward_tilt_does_not_force_low_angle(self) -> None:
        analysis = deepcopy(GROUP)
        analysis["shot_geometry"] = {
            "framing": "full_body",
            "camera_height": "knee",
            "camera_tilt": "down",
        }
        analysis["_local_person_geometry"] = {
            "people_count": 3,
            "full_body_candidate": True,
            "largest_height_ratio": 0.79,
        }
        plan = self.planner.plan(analysis, "Teach me to recreate this photo")
        photographer = plan["photographer_instruction"]
        self.assertEqual(photographer["height"], "Close to the center subject's eye level")
        self.assertNotIn("upward", photographer["angle"])

    def test_critic_rejects_low_angle_eye_height_and_near_distance(self) -> None:
        broken = deepcopy(
            self.planner.plan(LOW_ANGLE_FULL_BODY, "Teach me to recreate this photo")
        )
        broken["photographer_instruction"]["distance"] = "About 1 meter"
        broken["photographer_instruction"]["height"] = "Close to the subject's eye level"
        broken["photographer_instruction"]["angle"] = "Keep the camera level"
        review = self.critic.review(LOW_ANGLE_FULL_BODY, broken)
        self.assertEqual(review["status"], "needs_review")
        joined = " ".join(review["issues"])
        self.assertIn("eye-level camera height", joined)
        self.assertIn("too close", joined)
        self.assertIn("aim upward", joined)

    def test_local_mask_geometry_overrides_wrong_half_body_vlm_label(self) -> None:
        analysis = deepcopy(LOW_ANGLE_FULL_BODY)
        analysis["scene"] = "A girl stands outdoors against blue sky and distant mountains."
        analysis["subject"] = "One girl stands in the center of the frame."
        analysis["composition"] = "The subject is centered and the sky fills most of the background."
        analysis["recommendation"] = "Keep the low angle to emphasize both the subject and sky."
        analysis["shot_geometry"]["framing"] = "half_body"
        analysis["_local_person_geometry"] = {
            "people_count": 1,
            "largest_aspect_ratio": 2.45,
            "largest_height_ratio": 0.82,
            "full_body_candidate": True,
            "source": "local_mask_rcnn",
        }
        plan = self.planner.plan(analysis, "Teach me to recreate this effect")
        photographer = plan["photographer_instruction"]
        self.assertEqual(photographer["distance"], "About 3 to 4 meters")
        self.assertTrue(
            any(
                phrase in photographer["height"]
                for phrase in ("near the ground", "knee")
            )
        )
        self.assertEqual(
            self.critic.review(analysis, plan)["status"],
            "pass",
        )


if __name__ == "__main__":
    unittest.main()
