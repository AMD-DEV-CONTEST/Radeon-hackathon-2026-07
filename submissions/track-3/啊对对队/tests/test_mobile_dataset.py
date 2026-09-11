import unittest

import numpy as np

from parcel_sorter.mobile_dataset import (
    MOBILE_ACTION_NAMES,
    MOBILE_PRIVILEGED_STATE_NAMES,
    MOBILE_STAGE_NAMES,
    MOBILE_STATE_NAMES,
    MobileBimanualFrame,
    MobileBimanualLeRobotWriter,
    infer_mobile_policy_modality,
    mobile_policy_visual_keys,
)


class MobileDatasetContractTests(unittest.TestCase):
    def test_declares_smolvla_compatible_mobile_contract(self) -> None:
        self.assertEqual(len(MOBILE_STATE_NAMES), 43)
        self.assertEqual(len(MOBILE_ACTION_NAMES), 19)
        self.assertEqual(len(MOBILE_PRIVILEGED_STATE_NAMES), 7)
        self.assertEqual(len(MOBILE_STAGE_NAMES), 6)
        self.assertEqual(len(set(MOBILE_STATE_NAMES)), len(MOBILE_STATE_NAMES))

    def test_frame_rejects_wrong_feature_lengths(self) -> None:
        with self.assertRaisesRegex(ValueError, "43"):
            MobileBimanualFrame(0, 0.0, "pregrasp", (0.0,) * 42, (0.0,) * 19, (0.0,) * 7, "task")
        with self.assertRaisesRegex(ValueError, "19"):
            MobileBimanualFrame(0, 0.0, "pregrasp", (0.0,) * 43, (0.0,) * 18, (0.0,) * 7, "task")

    def test_frame_rejects_unknown_stage(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown mobile task stage"):
            MobileBimanualFrame(
                0, 0.0, "unknown", (0.0,) * 43, (0.0,) * 19, (0.0,) * 7, "task"
            )

    def test_declares_distinct_rgb_and_rgbd_policy_contracts(self) -> None:
        self.assertEqual(
            mobile_policy_visual_keys("rgb"),
            ("observation.images.overhead_rgb",),
        )
        self.assertEqual(
            mobile_policy_visual_keys("rgbd"),
            (
                "observation.images.overhead_rgb",
                "observation.images.overhead_depth_rgb",
            ),
        )
        with self.assertRaisesRegex(ValueError, "unsupported"):
            mobile_policy_visual_keys("depth-only")

    def test_infers_only_complete_policy_visual_contracts(self) -> None:
        self.assertEqual(
            infer_mobile_policy_modality(mobile_policy_visual_keys("rgbd")),
            "rgbd",
        )
        self.assertEqual(
            infer_mobile_policy_modality(mobile_policy_visual_keys("rgbd_wrist")),
            "rgbd_wrist",
        )
        with self.assertRaisesRegex(ValueError, "incomplete"):
            infer_mobile_policy_modality(
                (*mobile_policy_visual_keys("rgbd"), "observation.images.left_wrist_rgb")
            )

    def test_wrist_rgbd_writer_is_opt_in_and_complete(self) -> None:
        class FakeDataset:
            def __init__(self) -> None:
                self.frames = []

            def add_frame(self, payload) -> None:
                self.frames.append(payload)

        captured = {}

        def factory(**kwargs):
            captured.update(kwargs)
            return FakeDataset()

        writer = MobileBimanualLeRobotWriter(
            "unused",
            include_wrist_rgbd=True,
            dataset_factory=factory,
            image_size=(8, 8),
        )
        frame = MobileBimanualFrame(
            0,
            0.0,
            "pregrasp",
            (0.0,) * 43,
            (0.0,) * 19,
            (0.0,) * 7,
            "task",
            rgb=np.zeros((8, 8, 3), dtype=np.uint8),
            depth=np.ones((8, 8), dtype=np.float32),
            wrist_rgb=np.zeros((8, 8, 3), dtype=np.uint8),
            wrist_depth=np.ones((8, 8), dtype=np.float32),
        )

        writer.add_frame(frame)

        self.assertIn("observation.images.left_wrist_rgb", captured["features"])
        self.assertIn("observation.images.left_wrist_depth_rgb", captured["features"])
        self.assertIn(
            "observation.images.left_wrist_depth_rgb",
            writer._dataset.frames[0],
        )
        self.assertTrue(captured["use_videos"])
        self.assertEqual(captured["video_backend"], "pyav")
        self.assertEqual(captured["batch_encoding_size"], 1)
        self.assertEqual(writer.storage_format, "video")
        visual_features = {
            key: feature
            for key, feature in captured["features"].items()
            if key.startswith("observation.images.")
        }
        self.assertEqual(len(visual_features), 6)
        self.assertTrue(
            all(feature["dtype"] == "video" for feature in visual_features.values())
        )

    def test_image_parquet_writer_keeps_image_feature_types(self) -> None:
        captured = {}

        def factory(**kwargs):
            captured.update(kwargs)
            return object()

        writer = MobileBimanualLeRobotWriter(
            "unused",
            include_wrist_rgbd=True,
            use_videos=False,
            dataset_factory=factory,
            image_size=(8, 8),
        )

        visual_features = {
            key: feature
            for key, feature in captured["features"].items()
            if key.startswith("observation.images.")
        }
        self.assertEqual(len(visual_features), 6)
        self.assertTrue(
            all(feature["dtype"] == "image" for feature in visual_features.values())
        )
        self.assertFalse(captured["use_videos"])
        self.assertIsNone(captured["video_backend"])
        self.assertEqual(writer.storage_format, "image_parquet")


if __name__ == "__main__":
    unittest.main()
