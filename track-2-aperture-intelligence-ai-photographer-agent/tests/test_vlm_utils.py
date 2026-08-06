from __future__ import annotations

import unittest

from src.vision.vlm_inference import (
    COACHING_FIELDS,
    OUTPUT_FIELDS,
    _extract_json,
)


class VLMOutputTests(unittest.TestCase):
    def test_extract_plain_and_fenced_json(self) -> None:
        body = {
            "scene": "scene",
            "subject": "subject",
            "environment": "environment",
            "relationship": "relationship",
            "composition": "composition",
            "recommendation": "recommendation",
        }
        import json

        for wrapped in (json.dumps(body), f"```json\n{json.dumps(body)}\n```"):
            parsed = _extract_json(wrapped)
            self.assertEqual(
                {field: parsed[field] for field in OUTPUT_FIELDS}, body
            )
            self.assertEqual(parsed["people_boxes"], [])
            self.assertEqual(parsed["recommended_crop"], [50, 50, 950, 950])

    def test_extract_embedded_json_with_trailing_comma(self) -> None:
        text = (
            'Answer: {"scene":"s","subject":"p","environment":"e",'
            '"relationship":"r","composition":"c","recommendation":"x",}'
        )
        parsed = _extract_json(text)
        self.assertEqual(tuple(parsed), OUTPUT_FIELDS + COACHING_FIELDS)
        self.assertEqual(parsed["recommendation"], "x")

    def test_repairs_missing_comma_between_line_separated_fields(self) -> None:
        text = """{
  "scene": "Outdoor portrait",
  "subject": "One person"
  "environment": "Sky and distant mountains",
  "relationship": "The subject is the visual center",
  "composition": "Low-angle full-body composition",
  "recommendation": "Preserve the open sky"
}"""
        parsed = _extract_json(text)
        self.assertEqual(parsed["subject"], "One person")
        self.assertEqual(parsed["environment"], "Sky and distant mountains")

    def test_normalizes_coaching_geometry(self) -> None:
        import json

        parsed = _extract_json(
            json.dumps(
                {
                    "people_boxes": [[100, 200, 500, 900], ["bad"]],
                    "visible_props": [
                        "smartphone, backpack",
                        "smartphone",
                    ],
                    "action_labels": [
                        {
                            "person_indices": [0],
                            "anchor": "hands",
                            "text": "Lower the phone",
                        },
                        {
                            "person_indices": [8],
                            "anchor": "head",
                            "text": "Invalid person",
                        },
                    ],
                    "recommended_crop": [-20, 10, 1100, 980],
                    "avoid_regions": [[700, 100, 980, 500]],
                    "camera_move": "LEFT",
                    "subject_move": "right",
                    "light_direction": "soft",
                }
            )
        )
        self.assertEqual(parsed["people_boxes"], [[100, 200, 500, 900]])
        self.assertEqual(parsed["visible_props"], ["smartphone", "backpack"])
        self.assertEqual(
            parsed["action_labels"],
            [
                {
                    "person_indices": [0],
                    "anchor": "hands",
                    "text": "Lower the phone",
                }
            ],
        )
        self.assertEqual(parsed["recommended_crop"], [0, 10, 1000, 980])
        self.assertEqual(parsed["camera_move"], "left")

    def test_normalizes_shared_action_label(self) -> None:
        import json

        parsed = _extract_json(
            json.dumps(
                {
                    "people_boxes": [
                        [100, 100, 400, 900],
                        [430, 200, 700, 900],
                    ],
                    "action_labels": [
                        {
                            "person_indices": [0, 1],
                            "anchor": "between",
                            "text": "Hold hands naturally",
                        },
                        {
                            "person_index": 1,
                            "anchor": "head",
                            "text": "Child looks up",
                        },
                    ],
                },
                ensure_ascii=False,
            )
        )
        self.assertEqual(
            parsed["action_labels"],
            [
                {
                    "person_indices": [0, 1],
                    "anchor": "between",
                    "text": "Hold hands naturally",
                },
                {
                    "person_indices": [1],
                    "anchor": "head",
                    "text": "Child looks up",
                },
            ],
        )

    def test_filters_tiny_background_bystander_and_remaps_labels(self) -> None:
        import json

        parsed = _extract_json(
            json.dumps(
                {
                    "people_boxes": [
                        [190, 200, 780, 980],
                        [160, 630, 320, 850],
                    ],
                    "action_labels": [
                        {
                            "person_indices": [0],
                            "anchor": "hands",
                            "text": "Lower the phone",
                        },
                        {
                            "person_indices": [1],
                            "anchor": "body",
                            "text": "Background pedestrian action",
                        },
                    ],
                },
                ensure_ascii=False,
            )
        )
        self.assertEqual(parsed["people_boxes"], [[190, 200, 780, 980]])
        self.assertEqual(
            parsed["action_labels"],
            [
                {
                    "person_indices": [0],
                    "anchor": "hands",
                    "text": "Lower the phone",
                }
            ],
        )

    def test_deduplicates_repeated_person_box_and_remaps_labels(self) -> None:
        import json

        parsed = _extract_json(
            json.dumps(
                {
                    "people_boxes": [
                        [396, 87, 556, 558],
                        [396, 87, 556, 558],
                    ],
                    "action_labels": [
                        {
                            "person_indices": [1],
                            "anchor": "hands",
                            "text": "Lower the bouquet naturally",
                        }
                    ],
                },
                ensure_ascii=False,
            )
        )
        self.assertEqual(parsed["people_boxes"], [[396, 87, 556, 558]])
        self.assertEqual(
            parsed["action_labels"],
            [
                {
                    "person_indices": [0],
                    "anchor": "hands",
                    "text": "Lower the bouquet naturally",
                }
            ],
        )

    def test_rejects_vague_action_labels(self) -> None:
        import json

        parsed = _extract_json(
            json.dumps(
                {
                    "people_boxes": [[200, 150, 800, 950]],
                    "action_labels": [
                        {
                            "person_indices": [0],
                            "anchor": "body",
                            "text": "adjust the body pose",
                        },
                        {
                            "person_indices": [0],
                            "anchor": "hands",
                            "text": "Lower the phone",
                        },
                    ],
                },
                ensure_ascii=False,
            )
        )
        self.assertEqual(
            parsed["action_labels"],
            [
                {
                    "person_indices": [0],
                    "anchor": "hands",
                    "text": "Lower the phone",
                }
            ],
        )

    def test_infers_anchor_from_action_text(self) -> None:
        import json

        parsed = _extract_json(
            json.dumps(
                {
                    "people_boxes": [[200, 150, 800, 950]],
                    "action_labels": [
                        {
                            "person_indices": [0],
                            "anchor": "body",
                            "text": "Look to the left",
                        }
                    ],
                },
                ensure_ascii=False,
            )
        )
        self.assertEqual(parsed["action_labels"][0]["anchor"], "head")

    def test_converts_model_pixel_coordinates(self) -> None:
        import json

        parsed = _extract_json(
            json.dumps(
                {
                    "people_boxes": [[1024, 768, 3072, 2764]],
                    "recommended_crop": [800, 500, 3500, 2900],
                    "avoid_regions": [[0, 0, 4096, 3072]],
                }
            ),
            image_size=(4096, 3072),
        )
        self.assertEqual(parsed["people_boxes"], [[250, 250, 750, 899]])
        self.assertEqual(parsed["avoid_regions"], [])

    def test_reject_non_json(self) -> None:
        with self.assertRaisesRegex(ValueError, "did not return JSON"):
            _extract_json("This is prose.")

    def test_rejects_malformed_json_with_stable_retry_contract(self) -> None:
        malformed = '{"scene": "outdoor",\n"subject": "person"\nBROKEN}'
        with self.assertRaisesRegex(ValueError, "did not return JSON"):
            _extract_json(malformed)

    def test_strips_model_line_comments_outside_strings(self) -> None:
        parsed = _extract_json(
            """{
              "scene": "City // night",
              "people_boxes": [[100, 100, 700, 900]], // subject region
              "visible_props": []
            }"""
        )
        self.assertEqual(parsed["scene"], "City // night")
        self.assertEqual(parsed["people_boxes"], [[100, 100, 700, 900]])


if __name__ == "__main__":
    unittest.main()
