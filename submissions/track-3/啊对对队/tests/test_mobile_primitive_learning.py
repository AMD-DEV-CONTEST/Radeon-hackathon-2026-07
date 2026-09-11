import unittest

from parcel_sorter.mobile_dataset import MOBILE_ACTION_NAMES, MOBILE_STAGE_NAMES
from parcel_sorter.mobile_primitive_learning import (
    primitive_labels,
    primitive_progress,
    primitive_task_text,
    segment_mobile_actions,
    stage_agreement,
)


def _action(base_vx: float, tool: float) -> tuple[float, ...]:
    values = [0.0] * len(MOBILE_ACTION_NAMES)
    values[0] = base_vx
    values[MOBILE_ACTION_NAMES.index("left_gripper")] = tool
    values[MOBILE_ACTION_NAMES.index("right_gripper")] = 1.0
    return tuple(values)


class MobilePrimitiveLearningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.actions = (
            [_action(0.0, -1.0)] * 3
            + [_action(0.05, -1.0)] * 5
            + [_action(0.0, 1.0)] * 4
            + [_action(0.05, 1.0)] * 6
            + [_action(0.0, 1.0)] * 4
            + [_action(0.0, -1.0)] * 3
        )

    def test_event_segmentation_recovers_six_contiguous_primitives(self) -> None:
        segments = segment_mobile_actions(self.actions, min_motion_frames=2)
        self.assertEqual(tuple(item.primitive for item in segments), MOBILE_STAGE_NAMES)
        self.assertEqual(
            [(item.start_offset, item.end_offset) for item in segments],
            [(0, 2), (3, 7), (8, 11), (12, 17), (18, 21), (22, 24)],
        )

    def test_progress_resets_and_reaches_one_for_every_primitive(self) -> None:
        segments = segment_mobile_actions(self.actions, min_motion_frames=2)
        progress = primitive_progress(segments, frame_count=len(self.actions))
        for segment in segments:
            self.assertEqual(progress[segment.start_offset], 0.0)
            self.assertEqual(progress[segment.end_offset], 1.0)

    def test_stage_labels_are_audit_only_and_agree_with_fixture(self) -> None:
        segments = segment_mobile_actions(self.actions, min_motion_frames=2)
        labels = primitive_labels(segments, frame_count=len(self.actions))
        stage_ids = [
            MOBILE_STAGE_NAMES.index(label)
            for label in labels
        ]
        audit = stage_agreement(labels, stage_ids)
        self.assertEqual(audit["accuracy"], 1.0)
        self.assertFalse(audit["observed_stage_used_for_segmentation"])

    def test_missing_release_is_rejected(self) -> None:
        actions = list(self.actions)
        actions[-3:] = [_action(0.0, 1.0)] * 3
        with self.assertRaisesRegex(ValueError, "release transition"):
            segment_mobile_actions(actions, min_motion_frames=2)

    def test_primitive_prompt_retains_parent_task(self) -> None:
        text = primitive_task_text("Sort the parcel safely.", "lift")
        self.assertIn("Lift the attached parcel", text)
        self.assertIn("Sort the parcel safely", text)
        self.assertEqual(primitive_task_text(text, "lift"), text)


if __name__ == "__main__":
    unittest.main()
