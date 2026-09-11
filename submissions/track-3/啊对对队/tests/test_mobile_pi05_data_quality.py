import unittest

from parcel_sorter.mobile_pi05_data_quality import (
    summarize_pi05_action_chunk_activity,
)


def _action(*, residual: float = 0.0, suction: float = -1.0, progress: float = 0.0):
    values = [0.0] * 14
    values[3] = residual
    values[9:12] = [1.0, -1.0, -1.0]
    values[12] = suction
    values[13] = progress
    return values


class MobilePI05DataQualityTests(unittest.TestCase):
    def test_constant_mode_logits_do_not_hide_idle_chunks(self) -> None:
        summary = summarize_pi05_action_chunk_activity(
            [[_action(), _action(), _action()]], chunk_size=3
        )
        self.assertEqual(summary["chunk_count"], 3)
        self.assertEqual(summary["informative_chunk_count"], 0)
        self.assertEqual(summary["largely_idle_chunk_fraction"], 1.0)

    def test_residual_and_progress_windows_are_informative(self) -> None:
        episode = [
            _action(progress=0.00),
            _action(progress=0.05),
            _action(residual=0.002, progress=0.10),
        ]
        summary = summarize_pi05_action_chunk_activity([episode], chunk_size=3)
        self.assertEqual(summary["informative_chunk_count"], 3)
        self.assertGreater(summary["transition_chunk_count"], 0)

    def test_rejects_non_residual_action_shape(self) -> None:
        with self.assertRaisesRegex(ValueError, "14-D"):
            summarize_pi05_action_chunk_activity([[[0.0] * 13]], chunk_size=1)


if __name__ == "__main__":
    unittest.main()
