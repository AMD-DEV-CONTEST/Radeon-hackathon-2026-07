from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from src.tools.image_orientation import normalize_image_orientation


class FakeSegmenter:
    def segment(self, image: Image.Image, primary_boxes: list[list[int]]) -> dict:
        mask = Image.new("L", image.size, 0)
        draw = ImageDraw.Draw(mask)
        draw.rectangle(
            (
                int(image.width * 0.4),
                int(image.height * 0.1),
                int(image.width * 0.6),
                int(image.height * 0.9),
            ),
            fill=255,
        )
        return {
            "masks": [mask],
            "detections": 1,
            "people_matched": 1,
        }


class BackgroundBystanderSegmenter:
    def segment(self, image: Image.Image, primary_boxes: list[list[int]]) -> dict:
        masks = []
        for bounds in (
            (220, 80, 650, 580),
            (25, 300, 95, 560),
            (690, 330, 755, 555),
        ):
            mask = Image.new("L", image.size, 0)
            ImageDraw.Draw(mask).rectangle(bounds, fill=255)
            masks.append(mask)
        return {"masks": masks, "detections": 3, "people_matched": 3}


class ImageOrientationTests(unittest.TestCase):
    def test_returns_local_person_geometry_for_planner_calibration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "portrait.jpg"
            Image.new("RGB", (800, 600), "white").save(path)
            result = normalize_image_orientation(
                path,
                segmenter=FakeSegmenter(),
            )
        geometry = result["person_geometry"]
        self.assertEqual(geometry["people_count"], 1)
        self.assertTrue(geometry["full_body_candidate"])
        self.assertGreater(geometry["largest_aspect_ratio"], 2)
        self.assertGreater(geometry["largest_height_ratio"], 0.7)

    def test_small_background_bystanders_do_not_change_subject_count(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "portrait-with-bystanders.jpg"
            Image.new("RGB", (800, 600), "white").save(path)
            result = normalize_image_orientation(
                path,
                segmenter=BackgroundBystanderSegmenter(),
            )
        geometry = result["person_geometry"]
        self.assertEqual(geometry["people_count"], 1)
        self.assertEqual(geometry["visible_people_count"], 3)
        self.assertEqual(len(geometry["person_boxes"]), 1)


if __name__ == "__main__":
    unittest.main()
